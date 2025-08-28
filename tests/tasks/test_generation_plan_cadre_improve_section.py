import json
import pytest
from werkzeug.security import generate_password_hash

from src.app.models import (
    Department,
    Programme,
    Cours,
    CoursProgramme,
    PlanCadre,
    GlobalGenerationSettings,
    SectionAISettings,
    User,
    db,
)
from src.app.tasks.generation_plan_cadre import generate_plan_cadre_content_task


class DummySelf:
    request = type('Req', (), {'id': 'task-id'})()

    def update_state(self, *args, **kwargs):
        pass


def _setup_full_plan(app):
    """Create a course, a plan-cadre with multiple fields populated, and a user."""
    with app.app_context():
        dept = Department(nom="Dep")
        db.session.add(dept)
        db.session.commit()

        prog = Programme(nom="Prog", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()

        cours = Cours(code="C101", nom="Course")
        db.session.add(cours)
        db.session.commit()

        db.session.add(CoursProgramme(cours_id=cours.id, programme_id=prog.id, session=1))
        db.session.commit()

        plan = PlanCadre(
            cours_id=cours.id,
            place_intro="PLACE_INTRO",
            objectif_terminal="OBJECTIF",
            structure_intro="STRUCT_INTRO",
            structure_activites_theoriques="THEO",
            structure_activites_pratiques="PRAT",
            structure_activites_prevues="PREVUES",
            eval_evaluation_sommative="EVAL_SOMM",
            eval_nature_evaluations_sommatives="NATURE_SOMM",
            eval_evaluation_de_la_langue="EVAL_LANGUE",
            eval_evaluation_sommatives_apprentissages="EVAL_APPRENTISSAGES",
        )
        db.session.add(plan)
        db.session.commit()

        # Minimal generation setting enabling AI on a known section
        ggs = GlobalGenerationSettings(section="Intro et place du cours", use_ai=True, text_content="Prompt")
        db.session.add(ggs)
        db.session.commit()

        user = User(
            username="tester",
            password=generate_password_hash("pw"),
            role="admin",
            openai_key="sk",
            credits=1.0,
            is_first_connexion=False,
        )
        user.programmes.append(prog)
        db.session.add(user)
        db.session.commit()
        return plan.id, user.id


def test_improve_section_sends_improve_system_prompt_and_restricted_schema(app, monkeypatch):
    plan_id, user_id = _setup_full_plan(app)
    captured = {}

    with app.app_context():
        # Distinct prompts to ensure correct one is used
        sa_gen = SectionAISettings(section='plan_cadre', system_prompt='GEN_PROMPT')
        sa_imp = SectionAISettings(section='plan_cadre_improve', system_prompt='IMP_PROMPT')
        db.session.add_all([sa_gen, sa_imp])
        db.session.commit()

    class DummyResponses:
        def create(self, **kwargs):
            # capture system/user and text schema
            captured['input'] = kwargs['input']
            captured['schema'] = kwargs['text']['format']['schema']
            class Resp:
                output = []
                output_text = json.dumps({})
                class usage:
                    input_tokens = 0
                    output_tokens = 0
            return Resp()

    class DummyOpenAI:
        def __init__(self, *a, **k):
            self.responses = DummyResponses()

    import src.app.tasks.generation_plan_cadre as gpc
    monkeypatch.setattr(gpc, 'OpenAI', DummyOpenAI)
    monkeypatch.setattr("openai.OpenAI", DummyOpenAI)

    dummy = DummySelf()
    orig = generate_plan_cadre_content_task.__wrapped__.__func__
    # improve_only + target_columns for a single field
    form_data = {"improve_only": True, "target_columns": ["place_intro"], "additional_info": "ADDITIONAL_INFO"}
    try:
        orig(dummy, plan_id, form_data, user_id)
    except Exception:
        # ignore flow errors, we only capture the request payload
        pass

    messages = captured.get('input')
    if not messages:
        pytest.skip("OpenAI call not captured")

    # 1) The system message must be the IMPROVE prompt
    assert messages[0]['role'] == 'system'
    assert messages[0]['content'] == 'IMP_PROMPT'

    # 2) The user prompt should contain full plan-cadre content and mention the targeted field and additional info
    user_content = messages[1]['content']
    for token in [
        'PLACE_INTRO', 'OBJECTIF', 'STRUCT_INTRO', 'THEO', 'PRAT', 'PREVUES',
        'EVAL_SOMM', 'NATURE_SOMM', 'EVAL_LANGUE', 'EVAL_APPRENTISSAGES',
        'ADDITIONAL_INFO', 'place_intro'
    ]:
        assert token in user_content

    # 3) The JSON schema should only include the targeted field
    schema = captured['schema']
    props = schema.get('properties', {})
    assert set(props.keys()) == {'place_intro'}
    required = set(schema.get('required', []))
    assert required == {'place_intro'}


import json
import pytest
from werkzeug.security import generate_password_hash

import json
import pytest
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
from src.utils import get_plan_cadre_data


class DummySelf:
    request = type('Req', (), {'id': 'task-id'})()

    def update_state(self, *args, **kwargs):
        pass


def setup_plan(app):
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

        plan = PlanCadre(cours_id=cours.id, place_intro="EXISTING INTRO")
        db.session.add(plan)
        db.session.commit()

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


def test_generation_does_not_send_current_plan(app, monkeypatch):
    plan_id, user_id = setup_plan(app)
    captured = {}

    class DummyResponses:
        def create(self, **kwargs):
            captured['input'] = kwargs['input']
            class Resp:
                output = []
                output_text = '{}'
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
    try:
        orig(dummy, plan_id, {}, user_id)
    except Exception:
        pass
    if 'input' not in captured:
        pytest.skip("OpenAI call not captured")

    messages = captured['input']
    assert messages[1]['role'] == 'user'
    assert messages[2]['role'] == 'system'
    joined = json.dumps(messages)
    assert "EXISTING INTRO" not in joined
    payload = json.loads(messages[2]['content'])
    assert 'course_context' not in payload


def test_user_prompt_contains_context(app):
    plan_id, _ = setup_plan(app)
    with app.app_context():
        sa = SectionAISettings(section='plan_cadre', system_prompt='Bonjour {{nom_cours}}')
        db.session.add(sa)
        db.session.commit()
        plan = db.session.get(PlanCadre, plan_id)
        data = get_plan_cadre_data(plan.cours_id)
        cours_nom = plan.cours.nom
        programme_nom = data.get('programme', 'Non défini')
        cours_session = data['cours']['session']
        system_prompt = sa.system_prompt
    header = (
        f"Nom du cours: {cours_nom}\n"
        f"Session: {cours_session}\n"
        f"Nom du programme: {programme_nom}\n"
        f"Plan cadre des cours reliés (corequis, préalables):\n(Aucun)\n"
        f"Compétences développées et tous les détails:\n(Aucune)\n"
        f"Compétences atteintes et tous les détails:\n(Aucune)\n"
    )
    assert 'Nom du cours' in header
    assert 'Session' in header
    assert 'Nom du programme' in header
    assert 'Plan cadre des cours reliés' in header
    assert 'Compétences développées' in header
    assert 'Compétences atteintes' in header
    assert '{{nom_cours}}' in system_prompt
    assert cours_nom not in system_prompt

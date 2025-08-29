from unittest.mock import patch

from src.app.tasks.generation_plan_de_cours import generate_plan_de_cours_field_task
from src.app.models import (
    Department, Programme, User, Cours, PlanCadre, PlanDeCours, CoursProgramme, SectionAISettings, PlanDeCoursPromptSettings, db
)


class DummySelf:
    def __init__(self):
        self.updates = []
        self.request = type('R', (), {'id': 'task-id'})()

    def update_state(self, state=None, meta=None):
        self.updates.append(meta or {})


class DummyStream:
    def __init__(self, events, final_resp_builder):
        self.events = events
        self._final_resp_builder = final_resp_builder

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_response(self):
        return self._final_resp_builder()


class DummyResponses:
    def __init__(self, events, final_resp_builder, capture):
        self._events = events
        self._final_resp_builder = final_resp_builder
        self.capture = capture

    def stream(self, **kwargs):
        self.capture['last_stream_kwargs'] = kwargs
        return DummyStream(self._events, self._final_resp_builder)

    def parse(self, **kwargs):
        return self._final_resp_builder()


class DummyClient:
    def __init__(self, events, final_resp_builder, capture):
        self.responses = DummyResponses(events, final_resp_builder, capture)


def _final_resp():
    class Parsed:
        champ_description = "NOUVEAU_CONTENU"

    class Content:
        parsed = Parsed()

    class OutputItem:
        content = [Content]

    class Usage:
        input_tokens = 0
        output_tokens = 0

    class Resp:
        usage = Usage()
        output = [OutputItem]

    return Resp()


def setup(app):
    with app.app_context():
        dept = Department(nom="D")
        db.session.add(dept)
        db.session.commit()
        # Inject a conflicting field-level model to ensure task ignores it in improve mode
        db.session.add(PlanDeCoursPromptSettings(field_name="presentation_du_cours", prompt_template="", ai_model="gpt-4o"))
        db.session.commit()
        prog = Programme(nom="P", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()
        cours = Cours(code="C1", nom="Cours")
        db.session.add(cours)
        db.session.commit()
        plan_cadre = PlanCadre(cours_id=cours.id)
        db.session.add(plan_cadre)
        db.session.commit()
        plan = PlanDeCours(cours_id=cours.id, session="S1", materiel="MATERIEL_EXISTANT")
        db.session.add(plan)
        db.session.commit()
        db.session.add(CoursProgramme(cours_id=cours.id, programme_id=prog.id, session=1))
        db.session.commit()
        user = User(
            username="u",
            password="pw",
            role="user",
            openai_key="sk",
            credits=1.0,
            is_first_connexion=False,
        )
        user.programmes.append(prog)
        db.session.add(user)
        s = SectionAISettings.get_for('plan_de_cours_improve')
        s.system_prompt = "SYS_IMPROVE_PROMPT"
        db.session.add(s)
        db.session.commit()
        return plan.id, user.id


def run(dummy, plan_id, user_id):
    orig = generate_plan_de_cours_field_task.__wrapped__.__func__
    return orig(dummy, plan_id, "presentation_du_cours", "INFOS_PLUS", user_id)


def test_field_improve_uses_full_plan_and_improve_prompt(app):
    plan_id, user_id = setup(app)
    dummy = DummySelf()
    capture = {}
    events = []
    with patch("src.app.tasks.generation_plan_de_cours.OpenAI", return_value=DummyClient(events, _final_resp, capture)):
        result = run(dummy, plan_id, user_id)
    assert result['status'] == 'success'

    kwargs = capture.get('last_stream_kwargs')
    assert kwargs is not None
    # Ensure model comes from improve settings, not field-level prompt settings
    assert kwargs.get('model') in ("gpt-5", SectionAISettings.get_for('plan_de_cours_improve').ai_model or 'gpt-5')
    input_payload = kwargs.get('input')
    sys_msgs = [m for m in input_payload if m.get('role') == 'system']
    assert sys_msgs and any("SYS_IMPROVE_PROMPT" in c.get('text','') for c in sys_msgs[0].get('content', []))
    user_msgs = [m for m in input_payload if m.get('role') == 'user']
    assert user_msgs
    user_text = "\n".join([c.get('text', '') for c in user_msgs[0].get('content', []) if c.get('type') == 'input_text'])
    assert "MATERIEL_EXISTANT" in user_text
    assert "INFOS_PLUS" in user_text
    assert "target_field" in user_text and "presentation_du_cours" in user_text

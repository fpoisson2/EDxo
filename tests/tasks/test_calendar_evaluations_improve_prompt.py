from unittest.mock import patch
import json

from src.app.tasks.generation_plan_de_cours import (
    generate_plan_de_cours_calendar_task,
    generate_plan_de_cours_evaluations_task,
)
from src.app.models import (
    Department, Programme, User, Cours, PlanCadre, PlanDeCours, CoursProgramme, SectionAISettings, db
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


def _final_resp_calendar():
    class Parsed:
        calendriers = [
            type('E', (), {
                'semaine': 1,
                'sujet': 'Sujet',
                'activites': 'Act',
                'travaux_hors_classe': 'THC',
                'evaluations': 'Eval text'
            })()
        ]

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


def _final_resp_evals():
    class Cap:
        capacite = 'CapA'
        ponderation = '30%'

    class EvalItem:
        titre = 'Eval 1'
        description = 'Desc'
        semaine = 2
        capacites = [Cap()]

    class Parsed:
        evaluations = [EvalItem()]

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


def run_calendar(dummy, plan_id, user_id):
    orig = generate_plan_de_cours_calendar_task.__wrapped__.__func__
    return orig(dummy, plan_id, "INFOS_PLUS", user_id, None)


def run_evals(dummy, plan_id, user_id):
    orig = generate_plan_de_cours_evaluations_task.__wrapped__.__func__
    return orig(dummy, plan_id, "INFOS_PLUS", user_id, None)


def test_calendar_improve_uses_full_plan_and_improve_prompt(app):
    plan_id, user_id = setup(app)
    dummy = DummySelf()
    capture = {}
    events = []
    with patch("src.app.tasks.generation_plan_de_cours.OpenAI", return_value=DummyClient(events, _final_resp_calendar, capture)):
        result = run_calendar(dummy, plan_id, user_id)
    assert result['status'] == 'success'
    kwargs = capture.get('last_stream_kwargs')
    assert kwargs is not None
    input_payload = kwargs.get('input')
    sys_msgs = [m for m in input_payload if m.get('role') == 'system']
    assert sys_msgs and any("SYS_IMPROVE_PROMPT" in c.get('text','') for c in sys_msgs[0].get('content', []))
    user_msgs = [m for m in input_payload if m.get('role') == 'user']
    assert user_msgs
    user_text = "\n".join([c.get('text', '') for c in user_msgs[0].get('content', []) if c.get('type') == 'input_text'])
    assert "MATERIEL_EXISTANT" in user_text and "INFOS_PLUS" in user_text
    # Must constrain output to only calendriers and explicitly exclude unrelated sections
    assert '"only": "calendriers"' in user_text
    assert 'mediagraphies' in user_text and 'disponibilites' in user_text


def test_evaluations_improve_uses_full_plan_and_improve_prompt(app):
    plan_id, user_id = setup(app)
    dummy = DummySelf()
    capture = {}
    events = []
    with patch("src.app.tasks.generation_plan_de_cours.OpenAI", return_value=DummyClient(events, _final_resp_evals, capture)):
        result = run_evals(dummy, plan_id, user_id)
    assert result['status'] == 'success'
    kwargs = capture.get('last_stream_kwargs')
    assert kwargs is not None
    input_payload = kwargs.get('input')
    sys_msgs = [m for m in input_payload if m.get('role') == 'system']
    assert sys_msgs and any("SYS_IMPROVE_PROMPT" in c.get('text','') for c in sys_msgs[0].get('content', []))
    user_msgs = [m for m in input_payload if m.get('role') == 'user']
    assert user_msgs
    user_text = "\n".join([c.get('text', '') for c in user_msgs[0].get('content', []) if c.get('type') == 'input_text'])
    assert "MATERIEL_EXISTANT" in user_text and "INFOS_PLUS" in user_text
    # Must constrain output to only evaluations and explicitly exclude unrelated sections
    assert '"only": "evaluations"' in user_text
    assert 'mediagraphies' in user_text and 'disponibilites' in user_text

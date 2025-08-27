from unittest.mock import patch

from src.app.models import (
    Department,
    Programme,
    User,
    Cours,
    PlanCadre,
    PlanDeCours,
    CoursProgramme,
    SectionAISettings,
    AnalysePlanCoursPrompt,
    db,
)
from src.app.tasks.analyse_plan_de_cours import analyse_plan_de_cours_task
import pytest


class DummySelf:
    def __init__(self):
        self.updates = []
        self.request = type('R', (), {'id': 'task-id'})()

    def update_state(self, state=None, meta=None):
        self.updates.append(meta or {})


class DummyEvent:
    def __init__(self, name, delta=None, summary=None, use_event=False):
        if use_event:
            self.event = name
        else:
            self.type = name
        self.delta = delta
        self.summary = summary


class DummyStream:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_response(self):
        class Resp:
            class usage:
                input_tokens = 0
                output_tokens = 0

            output_text = '{}'

        return Resp()


class DummyResponses:
    def __init__(self, events):
        self._events = events

    def stream(self, **kwargs):
        s = DummyStream()
        s.events = self._events
        return s


class DummyClient:
    def __init__(self, events):
        self.responses = DummyResponses(events)


def setup_plan_user(app):
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
        plan = PlanDeCours(cours_id=cours.id, session="S1")
        db.session.add(plan)
        db.session.commit()
        db.session.add(CoursProgramme(cours_id=cours.id, programme_id=prog.id, session=1))
        db.session.commit()
        db.session.add(AnalysePlanCoursPrompt(prompt_template="Prompt"))
        db.session.add(SectionAISettings(section='analyse_plan_cours'))
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
        db.session.commit()
        return plan.id, user.id


@pytest.mark.parametrize("use_event", [False, True])
def test_analyse_plan_de_cours_stream_updates(app, use_event):
    plan_id, user_id = setup_plan_user(app)
    dummy = DummySelf()
    events = [
        DummyEvent(
            "response.output_text.delta",
            delta='{"compatibility_percentage": 0.5}',
            use_event=use_event,
        ),
        DummyEvent(
            "response.reasoning_summary_text.delta",
            delta="raisonnement",
            use_event=use_event,
        ),
        DummyEvent("response.completed", use_event=use_event),
    ]
    with patch("src.app.tasks.analyse_plan_de_cours.OpenAI", return_value=DummyClient(events)):
        orig = analyse_plan_de_cours_task.__wrapped__.__func__
        result = orig(dummy, plan_id, user_id)
    assert result["status"] == "success"
    assert result.get("reasoning_summary") == "raisonnement"
    # ensure streaming updates carry a message
    assert any(u.get("stream_chunk") and u.get("message") for u in dummy.updates)
    # reasoning summary updates should also include a message
    assert any(
        u.get("reasoning_summary") == "raisonnement" and u.get("message") == "Résumé du raisonnement"
        for u in dummy.updates
    )

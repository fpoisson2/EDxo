import json
from unittest.mock import patch

from src.app import db
from src.app.models import Programme, Department, User
from src.app.tasks.generation_logigramme import generate_programme_logigramme_task
import pytest


class DummySelf:
    def __init__(self):
        self.updates = []

    def update_state(self, state=None, meta=None):
        self.updates.append(meta or {})


class DummyEvent:
    def __init__(self, type, delta=None, summary=None):
        self.type = type
        self.delta = delta
        self.summary = summary


class DummyStream:
    def __iter__(self):
        return iter(self.events)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_final_response(self):
        class Resp:
            output_text = '{"links": []}'

            class usage:
                input_tokens = 0
                output_tokens = 0

        return Resp()


class DummyResponses:
    def __init__(self, events):
        self._events = events

    def stream(self, **kwargs):
        stream = DummyStream()
        stream.events = self._events
        return stream


class DummyClient:
    def __init__(self, events):
        self.responses = DummyResponses(events)


def setup_prog_user(app):
    with app.app_context():
        dept = Department(nom="D")
        db.session.add(dept)
        db.session.commit()
        prog = Programme(nom="P", department_id=dept.id)
        db.session.add(prog)
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
        return prog.id, user.id


def test_generate_logigramme_stream_updates(app):
    prog_id, user_id = setup_prog_user(app)
    dummy = DummySelf()
    events = [
        DummyEvent("response.output_text.delta", delta='{"links": []}'),
        DummyEvent("response.reasoning_summary_text.delta", delta="raisonnement"),
        DummyEvent("response.completed"),
    ]
    with patch("src.app.tasks.generation_logigramme.OpenAI", return_value=DummyClient(events)):
        orig = generate_programme_logigramme_task.__wrapped__.__func__
        result = orig(dummy, prog_id, user_id, {})
    assert result["status"] == "success"
    assert result["result"]["reasoning_summary"] == "raisonnement"
    assert any("stream_chunk" in u for u in dummy.updates)
    assert any(u.get("reasoning_summary") == "raisonnement" for u in dummy.updates)

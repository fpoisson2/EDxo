import json
from unittest.mock import patch

import pytest

from src.app import db
from src.app.models import Programme, Department, User
from src.app.tasks.generation_logigramme import generate_programme_logigramme_task


class DummySelf:
    def update_state(self, state=None, meta=None):
        pass


class DummyStream:
    def __iter__(self):
        return iter([])

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
    def stream(self, **kwargs):
        # Capture the exact payload sent to OpenAI
        DummyClient.last_kwargs = kwargs
        return DummyStream()


class DummyClient:
    last_kwargs = None

    def __init__(self, events=None):
        self.responses = DummyResponses()


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


def test_additional_info_is_sent_in_openai_input(app):
    prog_id, user_id = setup_prog_user(app)
    dummy = DummySelf()
    with patch("src.app.tasks.generation_logigramme.OpenAI", return_value=DummyClient()):
        # Call the underlying function synchronously
        orig = generate_programme_logigramme_task.__wrapped__.__func__
        additional_info = "Contraintes pédagogiques spécifiques à respecter"
        result = orig(dummy, prog_id, user_id, {"additional_info": additional_info})

    assert result["status"] == "success"
    # Ensure the SDK was called and we captured the input
    captured = DummyClient.last_kwargs
    assert captured is not None and "input" in captured
    messages = captured["input"]
    # Expect at least the system + data message; additional_info must be present as a separate user message
    assert isinstance(messages, list) and len(messages) >= 2
    user_texts = [m.get("content", "") for m in messages if m.get("role") == "user"]
    assert any(additional_info in (t or "") for t in user_texts), "Le texte info complémentaire doit être envoyé au modèle OpenAI"


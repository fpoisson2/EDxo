from unittest.mock import patch

import pytest
from src.app.tasks.generation_logigramme import generate_programme_logigramme_task
from .test_generation_logigramme_updates import (
    DummySelf,
    DummyEvent,
    DummyClient,
    setup_prog_user,
)


def test_generate_logigramme_parses_fenced_json_and_accents(app):
    prog_id, user_id = setup_prog_user(app)
    dummy = DummySelf()
    fenced_json = """```json
{"links": [{"cours_code": "420-ABC", "competence_code": "C1", "type": "développé"}]}
```"""
    events = [
        DummyEvent("response.output_text.delta", delta=fenced_json),
        DummyEvent("response.completed"),
    ]
    with patch("src.app.tasks.generation_logigramme.OpenAI", return_value=DummyClient(events)):
        orig = generate_programme_logigramme_task.__wrapped__.__func__
        result = orig(dummy, prog_id, user_id, {})
    assert result["result"]["links"] == [
        {"cours_code": "420-ABC", "competence_code": "C1", "type": "developpe"}
    ]

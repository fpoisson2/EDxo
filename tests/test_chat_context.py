import json
from types import SimpleNamespace

from src.app.models import User, db
from src.app.routes import chat as chat_routes


def test_context_after_tool_call(app, client, monkeypatch):
    # Create and log in user
    with app.app_context():
        user = User(username="u", password="p", role="user", openai_key="key", is_first_connexion=False)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)

    call_kwargs = []
    follow_kwargs = []

    # Dummy event classes
    class DummyResponseCreatedEvent:
        def __init__(self, response_id):
            self.response = SimpleNamespace(id=response_id)

    class DummyResponseOutputItemAddedEvent:
        def __init__(self, response_id, item):
            self.response = SimpleNamespace(id=response_id)
            self.item = item

    class DummyResponseOutputItemDoneEvent:
        def __init__(self, response_id, item):
            self.response = SimpleNamespace(id=response_id)
            self.item = item

    class DummyResponseFunctionCallArgumentsDeltaEvent:
        def __init__(self, response_id, delta):
            self.response = SimpleNamespace(id=response_id)
            self.delta = delta

    # Patch event classes in module
    monkeypatch.setattr(chat_routes, "ResponseCreatedEvent", DummyResponseCreatedEvent)
    monkeypatch.setattr(chat_routes, "ResponseOutputItemAddedEvent", DummyResponseOutputItemAddedEvent)
    monkeypatch.setattr(chat_routes, "ResponseOutputItemDoneEvent", DummyResponseOutputItemDoneEvent)
    monkeypatch.setattr(chat_routes, "ResponseFunctionCallArgumentsDeltaEvent", DummyResponseFunctionCallArgumentsDeltaEvent)

    def fake_safe_openai_stream(**kwargs):
        call_kwargs.append(kwargs)
        if len(call_kwargs) == 1:
            # First call triggers a tool
            def gen():
                yield DummyResponseCreatedEvent("id1")
                item = SimpleNamespace(type="function_call", name="list_all_plan_cadre", call_id="call1")
                yield DummyResponseOutputItemAddedEvent("id1", item)
                yield DummyResponseOutputItemDoneEvent("id1", SimpleNamespace(type="function_call"))
            return gen()
        else:
            # Second call just returns text
            def gen():
                yield DummyResponseCreatedEvent("id3")
                item = SimpleNamespace(type="message", text="final answer")
                event = DummyResponseOutputItemAddedEvent("id3", item)
                event.delta = "final answer"
                yield event
            return gen()

    monkeypatch.setattr(chat_routes, "safe_openai_stream", fake_safe_openai_stream)

    def fake_responses_create(**kwargs):
        follow_kwargs.append(kwargs)
        def gen():
            yield DummyResponseCreatedEvent("id2")
            item = SimpleNamespace(type="message", text="tool response")
            event = DummyResponseOutputItemAddedEvent("id2", item)
            event.delta = "tool response"
            yield event
        return gen()

    class DummyOpenAI:
        def __init__(self, api_key):
            self.api_key = api_key
            self.responses = SimpleNamespace(create=fake_responses_create)

    monkeypatch.setattr(chat_routes, "OpenAI", DummyOpenAI)

    # First message: triggers tool call
    resp1 = client.post("/chat/send", json={"message": "hi"})
    assert resp1.status_code == 200
    b"".join(resp1.response)

    with app.app_context():
        user = User.query.get(user_id)
        assert user.last_openai_response_id == "id2"
        assert user.last_openai_response_model == "gpt-4.1-mini"

    assert follow_kwargs and follow_kwargs[0]["model"] == "gpt-4.1-mini"

    # Second message: should use previous id and model
    resp2 = client.post("/chat/send", json={"message": "next"})
    assert resp2.status_code == 200
    b"".join(resp2.response)

    assert call_kwargs[1]["previous_response_id"] == "id2"
    assert call_kwargs[1]["model"] == "gpt-4.1-mini"

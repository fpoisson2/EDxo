import json
from types import SimpleNamespace
from werkzeug.security import generate_password_hash
from .test_app import get_model_by_name, fake_requests_post
import importlib
chat = importlib.import_module("src.app.routes.chat")


class FakeResponseCreatedEvent:
    def __init__(self, response_id):
        self.response = SimpleNamespace(id=response_id)


class FakeFunctionCallAddedEvent:
    def __init__(self, name, call_id, response_id):
        self.item = SimpleNamespace(type="function_call", name=name, call_id=call_id)
        self.response = SimpleNamespace(id=response_id)


class FakeFunctionCallArgumentsDeltaEvent:
    def __init__(self, delta, response_id):
        self.delta = delta
        self.response = SimpleNamespace(id=response_id)


class FakeFunctionCallDoneEvent:
    def __init__(self, response_id):
        self.item = SimpleNamespace(type="function_call")
        self.response = SimpleNamespace(id=response_id)


class FakeTextDeltaEvent:
    def __init__(self, text, response_id):
        self.delta = text
        self.response = SimpleNamespace(id=response_id)


def test_context_persisted_after_tool_call(client, app, monkeypatch):
    # Patch reCAPTCHA
    monkeypatch.setattr("requests.post", fake_requests_post)

    with app.app_context():
        from src.app import db
        User = get_model_by_name("User", db)
        ChatModelConfig = get_model_by_name("ChatModelConfig", db)
        user = User(
            username="u",
            password=generate_password_hash("p"),
            role="admin",
            credits=0.0,
            is_first_connexion=False,
            openai_key="test"
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        cfg = ChatModelConfig.get_current()
        cfg.chat_model = "model-chat"
        cfg.tool_model = "model-tool"
        db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    # Patch event classes
    monkeypatch.setattr(chat, "ResponseCreatedEvent", FakeResponseCreatedEvent)
    monkeypatch.setattr(chat, "ResponseOutputItemAddedEvent", FakeFunctionCallAddedEvent)
    monkeypatch.setattr(chat, "ResponseFunctionCallArgumentsDeltaEvent", FakeFunctionCallArgumentsDeltaEvent)
    monkeypatch.setattr(chat, "ResponseOutputItemDoneEvent", FakeFunctionCallDoneEvent)
    chat.OUTPUT_ITEM_EVENTS = (FakeFunctionCallAddedEvent, FakeFunctionCallDoneEvent)
    chat.TEXT_EVENTS = (FakeTextDeltaEvent, FakeFunctionCallAddedEvent)

    # Patch tool handler
    monkeypatch.setattr(chat, "handle_get_plan_de_cours", lambda args: {"ok": True})

    captured_follow_kwargs = {}

    class FakeOpenAI:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.responses = self

        def create(self, **kwargs):
            nonlocal captured_follow_kwargs
            captured_follow_kwargs = kwargs
            def gen():
                yield FakeResponseCreatedEvent("id2")
                yield FakeTextDeltaEvent("done", "id2")
            return gen()

    def fake_safe_openai_stream(**kwargs):
        def gen():
            yield FakeResponseCreatedEvent("id1")
            yield FakeFunctionCallAddedEvent("get_plan_de_cours", "call1", "id1")
            yield FakeFunctionCallArgumentsDeltaEvent("{}", "id1")
            yield FakeFunctionCallDoneEvent("id1")
        return gen()

    monkeypatch.setattr(chat, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(chat, "safe_openai_stream", fake_safe_openai_stream)

    response = client.post("/chat/send", json={"message": "hello"})
    assert response.status_code == 200
    response.get_data()
    assert captured_follow_kwargs["model"] == "model-chat"
    assert captured_follow_kwargs["previous_response_id"] == "id1"

    with app.app_context():
        from src.app import db
        User = get_model_by_name("User", db)
        user = User.query.filter_by(username="u").first()
        assert user.last_openai_response_id == "id2"
        assert user.last_openai_response_model == "model-chat"

    captured_second_kwargs = {}

    def fake_safe_openai_stream_second(**kwargs):
        nonlocal captured_second_kwargs
        captured_second_kwargs = kwargs
        def gen():
            yield FakeResponseCreatedEvent("id3")
            yield FakeTextDeltaEvent("next", "id3")
        return gen()

    monkeypatch.setattr(chat, "safe_openai_stream", fake_safe_openai_stream_second)

    response2 = client.post("/chat/send", json={"message": "again"})
    assert response2.status_code == 200
    response2.get_data()
    assert captured_second_kwargs["previous_response_id"] == "id2"
    assert captured_second_kwargs["model"] == "model-chat"

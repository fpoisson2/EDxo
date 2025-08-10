import json
from werkzeug.security import generate_password_hash


def get_model_by_name(model_name, db):
    for mapper in db.Model.registry.mappers:
        if mapper.class_.__name__ == model_name:
            return mapper.class_
    return None


def fake_requests_post(url, data, **kwargs):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True, "score": 1.0}

    return FakeResponse()


def login(client, app, monkeypatch):
    monkeypatch.setattr("requests.post", fake_requests_post)
    with app.app_context():
        from src.app import db

        User = get_model_by_name("User", db)
        if User.query.filter_by(username="admin").first() is None:
            user = User(
                username="admin",
                password=generate_password_hash("adminpass"),
                role="admin",
                credits=100.0,
                is_first_connexion=False,
            )
            db.session.add(user)
            db.session.commit()
    client.post(
        "/login",
        data={
            "username": "admin",
            "password": "adminpass",
            "recaptcha_token": "dummy",
            "submit": "Se connecter",
        },
        follow_redirects=True,
    )


def test_send_message_returns_assistant_response(client, app, monkeypatch):
    login(client, app, monkeypatch)
    resp = client.post("/chat/send", json={"message": "bonjour"})
    payloads = [line for line in resp.data.decode().split("\n") if line.startswith("data: ")]
    first = json.loads(payloads[0][len("data: "):])
    assert first["content"] != "bonjour"
    assert "bonjour" in first["content"]

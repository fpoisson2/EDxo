import pytest
from werkzeug.security import generate_password_hash
from src.app.models import User, db
from src.app.routes import routes as routes_module


def test_chat_resets_response_id(client, app, monkeypatch):
    """Ensure that visiting /chat resets any stored response ID."""
    with app.app_context():
        user = User(
            username="alice",
            password=generate_password_hash("password"),
            role="user",
            credits=0.0,
            is_first_connexion=False,
            last_openai_response_id="old-id",
        )
        db.session.add(user)
        db.session.commit()

    # Bypass reCAPTCHA verification during login
    monkeypatch.setattr(routes_module, "verify_recaptcha", lambda token: True)

    login_data = {
        "username": "alice",
        "password": "password",
        "recaptcha_token": "dummy",
        "submit": "Se connecter",
    }
    response = client.post("/login", data=login_data, follow_redirects=True)
    assert response.status_code == 200

    # Simulate existing session response id
    with client.session_transaction() as sess:
        sess["last_response_id"] = "old-id"
    # Enable CSRF so the ChatForm provides a csrf_token field
    app.config["WTF_CSRF_ENABLED"] = True
    response = client.get("/chat")
    assert response.status_code == 200

    # Session should be cleared
    with client.session_transaction() as sess:
        assert sess.get("last_response_id") is None

    # Database field should also be cleared
    with app.app_context():
        refreshed = User.query.filter_by(username="alice").first()
        assert refreshed.last_openai_response_id is None

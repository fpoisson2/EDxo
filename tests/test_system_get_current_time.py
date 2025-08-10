import pytest
from werkzeug.security import generate_password_hash
from .test_app import get_model_by_name, fake_requests_post


def create_admin(app):
    """Create an admin user with is_first_connexion disabled."""
    with app.app_context():
        from src.app import db
        User = get_model_by_name("User", db)
        admin = User(
            username="admin",
            password=generate_password_hash("adminpass"),
            role="admin",
            credits=0.0,
            is_first_connexion=False,
        )
        db.session.add(admin)
        db.session.commit()
        return admin.id


def test_get_current_time_requires_auth(client):
    """Unauthenticated users should be redirected."""
    response = client.get("/get_current_time")
    assert response.status_code == 302


def test_get_current_time_returns_json_for_admin(client, app, monkeypatch):
    """Authenticated admin should receive current time in JSON."""
    monkeypatch.setattr("requests.post", fake_requests_post)
    create_admin(app)

    login_data = {
        "username": "admin",
        "password": "adminpass",
        "recaptcha_token": "dummy",
        "submit": "Se connecter",
    }
    login_resp = client.post("/login", data=login_data, follow_redirects=True)
    assert login_resp.status_code == 200

    response = client.get("/get_current_time")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, dict)
    assert "current_time_utc" in data

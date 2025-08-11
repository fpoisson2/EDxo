import pytest
from flask import url_for
from uuid import uuid4
from werkzeug.security import generate_password_hash

from utils.decorator import ensure_profile_completed
from .test_app import get_model_by_name


@pytest.fixture
def protected_route(app):
    path = f"/ensure-protected-{uuid4().hex}"
    endpoint = f"ensure_protected_{uuid4().hex}"

    @app.route(path, endpoint=endpoint)
    @ensure_profile_completed
    def protected():
        return "accessible", 200

    return path


def create_user(app, username, first_connexion):
    with app.app_context():
        from src.app import db
        User = get_model_by_name("User", db)
        user = User(
            username=username,
            password=generate_password_hash("password"),
            role="user",
            credits=0.0,
            is_first_connexion=first_connexion,
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def login_client(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_redirect_when_profile_incomplete(client, app, protected_route):
    user_id = create_user(app, "newbie", True)
    login_client(client, user_id)

    response = client.get(protected_route, follow_redirects=False)
    assert response.status_code in (301, 302)
    with app.app_context():
        expected = url_for("main.welcome", _external=False)
    assert response.headers["Location"].endswith(expected)


def test_access_when_profile_completed(client, app, protected_route):
    user_id = create_user(app, "regular", False)
    login_client(client, user_id)

    response = client.get(protected_route)
    assert response.status_code == 200
    assert b"accessible" in response.data

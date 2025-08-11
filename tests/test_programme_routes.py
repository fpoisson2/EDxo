from flask import url_for
from werkzeug.security import generate_password_hash

from src.app import db
from src.app.models import User, Programme, Department, Competence

def create_programme_with_comp(app):
    """Create a programme with one competence for testing."""
    with app.app_context():
        department = Department(nom="DepTest")
        db.session.add(department)
        db.session.commit()

        programme = Programme(nom="ProgTest", department_id=department.id)
        db.session.add(programme)
        db.session.commit()

        competence = Competence(programme_id=programme.id, code="C1", nom="Comp 1")
        db.session.add(competence)
        programme.competences.append(competence)
        db.session.commit()

        return programme.id, competence.code, competence.nom

def create_user(app, username, role="user", programmes=None):
    """Create a user with optional programme associations."""
    with app.app_context():
        hashed = generate_password_hash("password")
        user = User(
            username=username,
            password=hashed,
            role=role,
            credits=0.0,
            is_first_connexion=False,
        )
        if programmes:
            for prog_id in programmes:
                programme = db.session.get(Programme, prog_id)
                if programme:
                    user.programmes.append(programme)
        db.session.add(user)
        db.session.commit()
        return user.id

def login_client(client, user_id):
    """Log a user in via session manipulation."""
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_authorized_user_access(app, client):
    """Authorized user should see programme competences."""
    programme_id, code, name = create_programme_with_comp(app)
    user_id = create_user(app, "authorized", programmes=[programme_id])
    login_client(client, user_id)

    response = client.get(f"/programme/{programme_id}/competences")
    assert response.status_code == 200
    assert code.encode() in response.data
    assert name.encode() in response.data


def test_unauthorized_user_redirect(app, client):
    """Non-member user should be redirected to main.index."""
    programme_id, _, _ = create_programme_with_comp(app)
    user_id = create_user(app, "unauthorized")
    login_client(client, user_id)

    response = client.get(f"/programme/{programme_id}/competences", follow_redirects=False)
    assert response.status_code in (301, 302)
    with app.app_context():
        assert response.headers["Location"].endswith(url_for("main.index", _external=False))

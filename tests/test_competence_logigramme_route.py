from flask import url_for
from werkzeug.security import generate_password_hash

from src.app import db
from src.app.models import User, Programme, Department


def create_programme(app):
    with app.app_context():
        dept = Department(nom="DepLogi")
        db.session.add(dept)
        db.session.commit()
        prog = Programme(nom="ProgLogigramme", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()
        return prog.id


def create_user(app, username, role="user", programmes=None):
    with app.app_context():
        user = User(
            username=username,
            password=generate_password_hash("password"),
            role=role,
            credits=0.0,
            is_first_connexion=False,
        )
        if programmes:
            for pid in programmes:
                p = db.session.get(Programme, pid)
                if p:
                    user.programmes.append(p)
        db.session.add(user)
        db.session.commit()
        return user.id


def login_client(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_logigramme_authorized(app, client):
    prog_id = create_programme(app)
    user_id = create_user(app, "auth", programmes=[prog_id])
    login_client(client, user_id)

    resp = client.get(f"/programme/{prog_id}/competences/logigramme")
    assert resp.status_code == 200
    # Should include page title text
    assert b"Logigramme des comp\xc3\xa9tences" in resp.data


def test_logigramme_unauthorized_redirect(app, client):
    prog_id = create_programme(app)
    user_id = create_user(app, "unauth")
    login_client(client, user_id)

    resp = client.get(f"/programme/{prog_id}/competences/logigramme", follow_redirects=False)
    assert resp.status_code in (301, 302)
    with app.app_context():
        assert resp.headers["Location"].endswith(url_for("main.index", _external=False))


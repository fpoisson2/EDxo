from werkzeug.security import generate_password_hash
from src.app import db
from src.app.models import (
    Programme,
    Department,
    Cours,
    CoursProgramme,
    User,
)


def create_programme_with_courses(app):
    with app.app_context():
        dept = Department(nom="Dep")
        db.session.add(dept)
        db.session.commit()

        prog = Programme(nom="Prog", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()

        c1 = Cours(code="C1", nom="Course 1")
        c2 = Cours(code="C2", nom="Course 2")
        db.session.add_all([c1, c2])
        db.session.commit()

        a1 = CoursProgramme(cours_id=c1.id, programme_id=prog.id, session=1)
        a2 = CoursProgramme(cours_id=c2.id, programme_id=prog.id, session=2)
        db.session.add_all([a1, a2])
        db.session.commit()
        return prog.id


def create_user(app, programme_id):
    with app.app_context():
        user = User(
            username="tester",
            password=generate_password_hash("password"),
            role="user",
            credits=0.0,
            is_first_connexion=False,
        )
        programme = db.session.get(Programme, programme_id)
        user.programmes.append(programme)
        db.session.add(user)
        db.session.commit()
        return user.id


def login_client(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_export_grille_pdf(app, client):
    programme_id = create_programme_with_courses(app)
    user_id = create_user(app, programme_id)
    login_client(client, user_id)
    resp = client.get(f"/programme/{programme_id}/grille/pdf")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/pdf"
    assert len(resp.data) > 100

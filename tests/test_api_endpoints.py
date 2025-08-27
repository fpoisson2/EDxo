from datetime import datetime, timedelta, timezone
import pytest
from werkzeug.security import generate_password_hash
from src.app import db
from src.app.models import (
    Programme,
    Department,
    Cours,
    PlanCadre,
    PlanDeCours,
    Competence,
    User,
)


def setup_data(app):
    with app.app_context():
        dept = Department(nom="Dep")
        db.session.add(dept)
        db.session.commit()

        programme = Programme(nom="Prog", department_id=dept.id)
        db.session.add(programme)
        db.session.commit()

        cours = Cours(code="C101", nom="Course", heures_theorie=0,
                      heures_laboratoire=0, heures_travail_maison=0)
        db.session.add(cours)
        db.session.commit()
        cours.programmes.append(programme)
        db.session.commit()

        plan_cadre = PlanCadre(cours_id=cours.id)
        db.session.add(plan_cadre)
        plan_de_cours = PlanDeCours(cours_id=cours.id, session="A25")
        db.session.add(plan_de_cours)

        comp = Competence(programme_id=programme.id, code="COMP1", nom="Comp 1")
        db.session.add(comp)
        db.session.commit()

        return programme.id, cours.id, plan_cadre.id, plan_de_cours.id, comp.id


def create_user(app, programmes=None, token="api-token", expires_in_days=1):
    with app.app_context():
        user = User(
            username="tester",
            password=generate_password_hash("password"),
            role="admin",
            credits=0.0,
            is_first_connexion=False,
            api_token=token,
            api_token_expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
        )
        if programmes:
            for pid in programmes:
                programme = db.session.get(Programme, pid)
                if programme:
                    user.programmes.append(programme)
        db.session.add(user)
        db.session.commit()
        return user.id, token


def test_api_endpoints(app, client):
    prog_id, cours_id, plan_cadre_id, plan_de_cours_id, comp_id = setup_data(app)
    user_id, token = create_user(app, programmes=[prog_id])

    # unauthorized request without token
    resp = client.get("/api/programmes")
    assert resp.status_code == 401

    headers = {"X-API-Token": token}

    resp = client.get("/api/programmes", headers=headers)
    assert resp.status_code == 200
    assert any(p["id"] == prog_id for p in resp.get_json())

    resp = client.get(f"/api/programmes/{prog_id}/cours", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()[0]["id"] == cours_id

    resp = client.get(f"/api/programmes/{prog_id}/competences", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()[0]["code"] == "COMP1"

    resp = client.get(f"/api/competences/{comp_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["id"] == comp_id

    resp = client.get("/api/cours", headers=headers)
    assert resp.status_code == 200
    assert any(c["id"] == cours_id for c in resp.get_json())

    resp = client.get(f"/api/cours/{cours_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["code"] == "C101"

    resp = client.get(f"/api/cours/{cours_id}/plan_cadre", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["id"] == plan_cadre_id

    resp = client.get(f"/api/cours/{cours_id}/plans_de_cours", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()[0]["id"] == plan_de_cours_id

    resp = client.get(f"/api/plan_cadre/{plan_cadre_id}/section/place_intro", headers=headers)
    assert resp.status_code == 200
    assert "place_intro" in resp.get_json()


def test_api_token_lifecycle(app, client, monkeypatch):
    # allow login without real recaptcha
    from src.app.routes import routes as routes_module

    monkeypatch.setattr(routes_module, "verify_recaptcha", lambda token: True)

    user_id, _ = create_user(app, token=None)

    # login to obtain session
    client.post(
        "/login",
        data={"username": "tester", "password": "password", "recaptcha_token": "dummy"},
        follow_redirects=True,
    )

    # no token yet
    resp = client.get("/api/token")
    assert resp.status_code == 201
    token = resp.get_json()["token"]

    headers = {"X-API-Token": token}
    assert client.get("/api/programmes", headers=headers).status_code == 200

    # create an immediately expired token
    resp = client.post("/api/token?ttl=0")
    expired_token = resp.get_json()["token"]
    headers = {"X-API-Token": expired_token}
    assert client.get("/api/programmes", headers=headers).status_code == 401


def test_developer_page_token_generation(app, client, monkeypatch):
    from src.app.routes import routes as routes_module
    monkeypatch.setattr(routes_module, "verify_recaptcha", lambda token: True)

    user_id, _ = create_user(app, token=None)

    client.post(
        "/login",
        data={"username": "tester", "password": "password", "recaptcha_token": "dummy"},
        follow_redirects=True,
    )

    resp = client.get("/settings/developer")
    assert resp.status_code == 200

    resp = client.post("/settings/developer", data={"ttl": "1"}, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.api_token is not None

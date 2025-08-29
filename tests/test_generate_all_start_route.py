import json
from werkzeug.security import generate_password_hash


def setup_basic_plan(app):
    from src.app import db
    from src.app.models import Department, Programme, Cours, PlanCadre, PlanDeCours

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
        db.session.commit()

        return cours.id, plan_de_cours.session, plan_de_cours.id


def login_admin(app, client):
    from src.app import db
    from src.app.models import User
    from src.app.routes import routes as routes_module

    # Bypass recaptcha
    def _ok(_):
        return True
    import types
    routes_module.verify_recaptcha = types.SimpleNamespace(__call__=_ok)
    # in tests, the login route uses routes.verify_recaptcha(token)
    routes_module.verify_recaptcha = lambda token: True

    with app.app_context():
        user = User.query.filter_by(username="admin").first()
        if not user:
            user = User(
                username="admin",
                password=generate_password_hash("adminpass"),
                role="admin",
                credits=100.0,
                is_first_connexion=False,
                openai_key="sk-test",  # not required by this route but good to have
            )
            db.session.add(user)
            db.session.commit()

    resp = client.post(
        "/login",
        data={"username": "admin", "password": "adminpass", "recaptcha_token": "dummy"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_generate_all_start_passes_improve_only_flag(app, client, monkeypatch):
    cours_id, session, plan_id = setup_basic_plan(app)
    login_admin(app, client)

    captured = {}

    def fake_delay(pid, prompt, ai_model, uid, improve_only=False):
        captured["pid"] = pid
        captured["prompt"] = prompt
        captured["ai_model"] = ai_model
        captured["uid"] = uid
        captured["improve_only"] = improve_only

        class Dummy:
            id = "tid-123"

        return Dummy()

    monkeypatch.setattr(
        "src.app.tasks.generation_plan_de_cours.generate_plan_de_cours_all_task.delay",
        fake_delay,
    )

    # 1) With improve_only true
    resp = client.post(
        "/generate_all_start",
        json={
            "cours_id": cours_id,
            "session": session,
            "ai_model": "gpt-5",
            "additional_info": "Infos",
            "improve_only": True,
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["task_id"] == "tid-123"
    assert captured["pid"] == plan_id
    assert captured["uid"] is not None
    assert captured["improve_only"] is True

    # 2) Without the flag, defaults to False
    resp2 = client.post(
        "/generate_all_start",
        json={
            "cours_id": cours_id,
            "session": session,
            "ai_model": "gpt-5",
            "additional_info": "Infos",
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["success"] is True
    assert captured["improve_only"] is False


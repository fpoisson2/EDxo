import pytest
from werkzeug.security import generate_password_hash
from src.app.models import User, Department, Programme, Cours, PlanCadre, db


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _setup_minimal_course_plan(app):
    with app.app_context():
        dept = Department(nom="D")
        db.session.add(dept)
        db.session.commit()
        prog = Programme(nom="P", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()
        cours = Cours(code="C1", nom="Cours")
        db.session.add(cours)
        db.session.commit()
        plan = PlanCadre(cours_id=cours.id)
        db.session.add(plan)
        db.session.commit()
        return cours.id, plan.id


def test_plan_cadre_import_uses_no_success_highlight_flag(app, client):
    # Create admin
    with app.app_context():
        admin = User(
            username="admin",
            password=generate_password_hash("pw"),
            role="admin",
            is_first_connexion=False,
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    cours_id, plan_id = _setup_minimal_course_plan(app)
    # Access the plan-cadre view which embeds the orchestrator integration
    resp = client.get(f"/cours/{cours_id}/plan_cadre/{plan_id}")
    assert resp.status_code == 200
    # The file-import orchestrator call should not disable the green highlight
    assert b"noSuccessHighlight: true" not in resp.data

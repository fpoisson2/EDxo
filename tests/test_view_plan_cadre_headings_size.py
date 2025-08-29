from werkzeug.security import generate_password_hash
from src.app.models import User, Department, Programme, Cours, PlanCadre, db


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _setup_minimal_course_plan(app):
    with app.app_context():
        dept = Department(nom="Dept")
        db.session.add(dept)
        db.session.commit()
        prog = Programme(nom="Prog", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()
        cours = Cours(code="C-101", nom="Cours Test")
        db.session.add(cours)
        db.session.commit()
        plan = PlanCadre(cours_id=cours.id)
        db.session.add(plan)
        db.session.commit()
        return cours.id, plan.id


def test_partie_2_and_3_headings_use_smaller_h6(app, client):
    # Create an admin and login
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

    resp = client.get(f"/cours/{cours_id}/plan_cadre/{plan_id}")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    # Partie 2: ensure section headings are rendered as h6 (smaller)
    assert '<h6 class="fw-bold d-flex align-items-center gap-2">Compétences développées' in html
    assert '<h6 class="fw-bold d-flex align-items-center gap-2">Objets cibles' in html

    # Partie 3: Capacités heading also uses h6
    assert '<h6 class="fw-bold d-flex align-items-center gap-2">Capacités' in html

    # Ensure no lingering h3 for these specific headings
    assert '<h3 class="fw-bold d-flex align-items-center gap-2">Compétences développées' not in html
    assert '<h3 class="fw-bold d-flex align-items-center gap-2">Objets cibles' not in html
    assert '<h3 class="fw-bold d-flex align-items-center gap-2">Capacités' not in html


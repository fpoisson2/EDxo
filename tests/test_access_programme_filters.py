import pytest
from werkzeug.security import generate_password_hash

from src.app import db
from src.app.models import User, Programme, Department, Cours, FilConducteur


def create_department_and_programmes(app):
    with app.app_context():
        dept = Department(nom="DepTest")
        db.session.add(dept)
        db.session.commit()
        p1 = Programme(nom="Prog A", department_id=dept.id)
        p2 = Programme(nom="Prog B", department_id=dept.id)
        db.session.add_all([p1, p2])
        db.session.commit()
        return p1.id, p2.id


def create_courses_for_programmes(app, prog_a_id, prog_b_id):
    with app.app_context():
        c1 = Cours(code="A-101", nom="Cours A")
        c2 = Cours(code="B-201", nom="Cours B")
        db.session.add_all([c1, c2])
        db.session.commit()
        # Associer via la table d'association
        db.session.execute(
            db.text("INSERT INTO Cours_Programme(cours_id, programme_id, session) VALUES (:c, :p, :s)"),
            {"c": c1.id, "p": prog_a_id, "s": 1}
        )
        db.session.execute(
            db.text("INSERT INTO Cours_Programme(cours_id, programme_id, session) VALUES (:c, :p, :s)"),
            {"c": c2.id, "p": prog_b_id, "s": 1}
        )
        db.session.commit()
        return c1.id, c2.id


def create_user_with_role(app, username, role, programmes=None):
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


@pytest.mark.parametrize("role", ["coordo", "cp", "professeur"])
def test_evaluation_get_courses_filters_by_user_programmes(app, client, role):
    prog_a_id, prog_b_id = create_department_and_programmes(app)
    c1_id, c2_id = create_courses_for_programmes(app, prog_a_id, prog_b_id)
    user_id = create_user_with_role(app, f"user_{role}", role, programmes=[prog_a_id])
    login_client(client, user_id)

    resp = client.get("/evaluation/get_courses")
    assert resp.status_code == 200
    data = resp.get_json()
    # Must only contain course A (belonging to prog A)
    codes = {item["code"] for item in data}
    assert codes == {"A-101"}


def test_add_fil_conducteur_programme_choices_filtered_for_coordo(app, client):
    prog_a_id, prog_b_id = create_department_and_programmes(app)
    user_id = create_user_with_role(app, "coordo_user", "coordo", programmes=[prog_a_id])
    login_client(client, user_id)

    resp = client.get("/add_fil_conducteur")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    # Should see only programme A name
    assert "Prog A" in html
    assert "Prog B" not in html


def test_edit_fil_conducteur_restricted_to_assigned_programmes(app, client):
    prog_a_id, prog_b_id = create_department_and_programmes(app)
    with app.app_context():
        fil_a = FilConducteur(programme_id=prog_a_id, description="Fil A", couleur="#000000")
        fil_b = FilConducteur(programme_id=prog_b_id, description="Fil B", couleur="#111111")
        db.session.add_all([fil_a, fil_b])
        db.session.commit()
        fil_a_id, fil_b_id = fil_a.id, fil_b.id

    user_id = create_user_with_role(app, "coordo_user2", "coordo", programmes=[prog_a_id])
    login_client(client, user_id)

    # Cannot edit fil B (not assigned programme) -> redirect away or forbidden
    resp = client.get(f"/edit_fil_conducteur/{fil_b_id}", follow_redirects=False)
    assert resp.status_code in (301, 302, 403)

    # Can edit fil A, but the programme choices should be limited to assigned programmes
    resp2 = client.get(f"/edit_fil_conducteur/{fil_a_id}")
    assert resp2.status_code == 200
    html2 = resp2.data.decode("utf-8")
    assert "Prog A" in html2
    assert "Prog B" not in html2

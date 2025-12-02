from werkzeug.security import generate_password_hash

from src.app import db
from src.app.models import (
    Cours,
    CoursProgramme,
    Department,
    PlanCadre,
    PlanCadreCapacites,
    PlanDeCours,
    PlanDeCoursEvaluations,
    PlanDeCoursEvaluationsCapacites,
    Programme,
    User,
)


def test_export_docx_handles_missing_capacite(client, app, monkeypatch):
    """Ensure export_docx skips evaluation links without a capacity instead of crashing."""
    from src.app.routes import routes as main_routes

    monkeypatch.setattr("src.utils.recaptcha.verify_recaptcha", lambda token: True)
    monkeypatch.setattr(main_routes, "verify_recaptcha", lambda token: True)

    with app.app_context():
        user = User(
            username="teacher",
            password=generate_password_hash("secret123"),
            role="admin",
            is_first_connexion=False,
        )

        department = Department(nom="Sciences")
        programme = Programme(nom="Programme Test", department=department)
        course = Cours(
            code="TEST101",
            nom="Test Course",
            nombre_unites=1,
            heures_theorie=0,
            heures_laboratoire=0,
            heures_travail_maison=0,
        )
        course_assoc = CoursProgramme(cours=course, programme=programme, session="H26")

        plan_cadre = PlanCadre(cours=course)
        capacite = PlanCadreCapacites(
            plan_cadre=plan_cadre,
            capacite="Capacité 1",
            description_capacite="Description",
        )

        plan_de_cours = PlanDeCours(cours=course, session="H26")
        evaluation = PlanDeCoursEvaluations(
            plan_de_cours=plan_de_cours,
            titre_evaluation="Épreuve 1",
        )
        # Missing capacity association should be ignored gracefully.
        association_without_cap = PlanDeCoursEvaluationsCapacites(
            evaluation=evaluation,
            capacite=None,
            ponderation="30%",
        )
        # Valid association remains supported.
        association_with_cap = PlanDeCoursEvaluationsCapacites(
            evaluation=evaluation,
            capacite=capacite,
            ponderation="70%",
        )

        db.session.add_all(
            [
                user,
                department,
                programme,
                course,
                course_assoc,
                plan_cadre,
                capacite,
                plan_de_cours,
                evaluation,
                association_without_cap,
                association_with_cap,
            ]
        )
        db.session.commit()

        course_id = course.id
        plan_session = plan_de_cours.session

    login_response = client.post(
        "/login",
        data={
            "username": "teacher",
            "password": "secret123",
            "recaptcha_token": "token",
            "submit": "Se connecter",
        },
        follow_redirects=True,
    )
    assert login_response.status_code == 200

    response = client.get(
        f"/cours/{course_id}/plan_de_cours/{plan_session}/export_docx",
    )

    assert response.status_code == 200
    assert response.headers.get("Content-Type") == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.headers.get("Content-Disposition", "").startswith("attachment;")
    assert response.data  # docx bytes

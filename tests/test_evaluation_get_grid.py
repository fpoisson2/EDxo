from werkzeug.security import generate_password_hash

from src.app import db
from src.app.models import (
    User,
    Cours,
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreCapaciteSavoirsFaire,
    PlanDeCours,
    PlanDeCoursEvaluations,
    PlanDeCoursEvaluationsCapacites,
)


def test_get_grid_filters_by_selected_evaluation(client, app, monkeypatch):
    """Ensure /evaluation/get_grid loads only the requested evaluation's skills."""
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
        db.session.add(user)

        course = Cours(
            code="TEST101",
            nom="Test Course",
            nombre_unites=1,
            heures_theorie=0,
            heures_laboratoire=0,
            heures_travail_maison=0,
        )

        plan_cadre = PlanCadre(cours=course)
        capacity_one = PlanCadreCapacites(
            plan_cadre=plan_cadre,
            capacite="Capacité 1",
            description_capacite="Description 1",
        )
        capacity_two = PlanCadreCapacites(
            plan_cadre=plan_cadre,
            capacite="Capacité 2",
            description_capacite="Description 2",
        )
        sf_one = PlanCadreCapaciteSavoirsFaire(
            capacite=capacity_one,
            texte="Savoir-faire A",
        )
        sf_two = PlanCadreCapaciteSavoirsFaire(
            capacite=capacity_two,
            texte="Savoir-faire B",
        )

        plan_de_cours = PlanDeCours(cours=course, session="Automne 2024")
        evaluation_one = PlanDeCoursEvaluations(
            plan_de_cours=plan_de_cours,
            titre_evaluation="Évaluation 1",
        )
        evaluation_two = PlanDeCoursEvaluations(
            plan_de_cours=plan_de_cours,
            titre_evaluation="Évaluation 2",
        )

        assoc_one = PlanDeCoursEvaluationsCapacites(
            evaluation=evaluation_one,
            capacite=capacity_one,
        )
        assoc_two = PlanDeCoursEvaluationsCapacites(
            evaluation=evaluation_two,
            capacite=capacity_two,
        )

        db.session.add_all([
            course,
            plan_cadre,
            capacity_one,
            capacity_two,
            sf_one,
            sf_two,
            plan_de_cours,
            evaluation_one,
            evaluation_two,
            assoc_one,
            assoc_two,
        ])

        db.session.commit()

        evaluation_id = evaluation_one.id

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

    response = client.post(
        "/evaluation/get_grid",
        data={"evaluation_id": str(evaluation_id)},
    )
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "Savoir-faire A" in html
    assert "Savoir-faire B" not in html

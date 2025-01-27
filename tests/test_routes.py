# tests/test_routes.py

from app.models import User, Programme, Cours, PlanCadre, PlanDeCours, Department
from flask import url_for
from flask_login import login_user

import logging

logging.basicConfig(level=logging.DEBUG)

def test_plan_cadre_coordo_permission_denied(client, test_db):
    """ Test where a coordo is NOT attached to the programme => should return 403 """
    # Create Department
    department = Department(id=1, nom="Test Department")
    test_db.session.add(department)
    test_db.session.commit()

    # Create Programme
    programme = Programme(nom="Test", department_id=department.id)
    test_db.session.add(programme)
    test_db.session.commit()

    # Create Coordonateur
    coordo = User(username="test_coordo", password="password123", role="coordo")
    test_db.session.add(coordo)  # Not attaching to the programme
    test_db.session.commit()

    # Create Cours
    cours = Cours(programme_id=programme.id, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
    test_db.session.add(cours)
    test_db.session.commit()

    # Create PlanCadre
    plan = PlanCadre(cours_id=cours.id)
    test_db.session.add(plan)
    test_db.session.commit()

    with client:
        client.get('/')
        with client.session_transaction() as sess:
            login_user(coordo)
            sess['_fresh'] = True

        response = client.post(
            url_for('cours.view_plan_cadre', cours_id=cours.id, plan_id=plan.id),
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )

    assert response.status_code == 403  # Should NOT have access


def test_plan_cadre_coordo_permission_allowed(client, test_db):
    """ Test where a coordo HAS access to the programme => should return 200 OK """
    # Create Department
    department = Department(id=1, nom="Test Department")
    test_db.session.add(department)
    test_db.session.commit()

    # Create Programme
    programme = Programme(nom="Test", department_id=department.id)
    test_db.session.add(programme)
    test_db.session.commit()

    # Create Coordonateur
    coordo = User(username="test_coordo", password="password123", role="coordo")
    coordo.programmes.append(programme)  # Now attaching to the programme
    test_db.session.add(coordo)
    test_db.session.commit()

    # Create Cours
    cours = Cours(programme_id=programme.id, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
    test_db.session.add(cours)
    test_db.session.commit()

    # Create PlanCadre
    plan = PlanCadre(cours_id=cours.id)
    test_db.session.add(plan)
    test_db.session.commit()

    with client:
        client.get('/')
        with client.session_transaction() as sess:
            login_user(coordo)
            sess['_fresh'] = True

        response = client.post(
            url_for('cours.view_plan_cadre', cours_id=cours.id, plan_id=plan.id),
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )

    assert response.status_code == 200  # Should have access


def test_plan_cours_enseignant_permission_denied(client, test_db):
    """ Test where a teacher is NOT attached to the programme => should return 403 """
    # Create Department
    department = Department(id=1, nom="Test Department")
    test_db.session.add(department)
    test_db.session.commit()

    # Create Programme
    programme = Programme(nom="Test", department_id=department.id)
    test_db.session.add(programme)
    test_db.session.commit()

    # Create Teacher
    enseignant = User(username="test_prof", password="password123", role="professeur")
    test_db.session.add(enseignant)  # Not attaching to the programme
    test_db.session.commit()

    # Create Cours
    cours = Cours(programme_id=programme.id, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
    test_db.session.add(cours)
    test_db.session.commit()

    # Create PlanDeCours
    plan = PlanDeCours(cours_id=cours.id, session="A2023")
    test_db.session.add(plan)
    test_db.session.commit()

    # Create PlanCadre
    plan = PlanCadre(cours_id=cours.id)
    test_db.session.add(plan)
    test_db.session.commit()

    with client:
        client.get('/')
        with client.session_transaction() as sess:
            login_user(enseignant)
            sess['_fresh'] = True

        response = client.post(
            f'/cours/{cours.id}/plan_de_cours/A2023/',
            headers={'X-Requested-With': 'XMLHttpRequest'},
            json={}
        )
    assert response.status_code == 403  # Should NOT have access


# def test_plan_cours_enseignant_permission_allowed(client, test_db, login_user_helper):
#     """ Test where a teacher IS attached to the programme => should return 200 """
#     # Setup: Create Department, Programme, Teacher, Cours, PlanCadre, PlanDeCours
#     department = Department(nom="Test Department")
#     test_db.session.add(department)
#     test_db.session.commit()

#     programme = Programme(nom="Test Programme", department=department)
#     test_db.session.add(programme)
#     test_db.session.commit()

#     # Create Teacher and attach to Programme
#     enseignant = User(username="test_prof", password="password123", role="professeur")
#     enseignant.programmes.append(programme)
#     test_db.session.add(enseignant)
#     test_db.session.commit()

#     # Create Cours
#     cours = Cours(programme=programme, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
#     test_db.session.add(cours)
#     test_db.session.commit()

#     # Create PlanCadre
#     plan_cadre = PlanCadre(cours=cours)
#     test_db.session.add(plan_cadre)
#     test_db.session.commit()

#     # Create PlanDeCours
#     plan_de_cours = PlanDeCours(cours=cours, session="A2023")
#     test_db.session.add(plan_de_cours)
#     test_db.session.commit()

#     # Create Capacite
#     capacite = Capacite(capacite="Capacité 1", ponderation_min=10, ponderation_max=50)
#     test_db.session.add(capacite)
#     test_db.session.commit()

#     # Login as Teacher
#     login_user_helper(enseignant)

#     # Prepare Form Data
#     form_data = {
#         'campus': 'Main Campus',
#         'session': 'A2023',
#         'presentation_du_cours': 'Course Presentation',
#         'objectif_terminal_du_cours': 'Course Objectives',
#         'organisation_et_methodes': 'Organization and Methods',
#         'accomodement': 'Accommodations',
#         'evaluation_formative_apprentissages': 'Formative Evaluations',
#         'evaluation_expression_francais': 'French Expression Evaluations',
#         'seuil_reussite': '60%',
#         'materiel': 'Required Materials',
#         'nom_enseignant': 'Dr. John Doe',
#         'telephone_enseignant': '123-456-7890',
#         'courriel_enseignant': 'johndoe@example.com',
#         'bureau_enseignant': 'Room 101',
#         # Calendriers
#         'calendriers-0-semaine': '1',
#         'calendriers-0-sujet': 'Introduction',
#         'calendriers-0-activites': 'Activities Description',
#         'calendriers-0-travaux_hors_classe': 'Homework Description',
#         'calendriers-0-evaluations': 'Evaluation Description',
#         # Médiagraphies
#         'mediagraphies-0-reference_bibliographique': 'Doe, J. (2023). Course Material.',
#         # Disponibilités
#         'disponibilites-0-jour_semaine': 'Monday',
#         'disponibilites-0-plage_horaire': '09:00-11:00',
#         'disponibilites-0-lieu': 'Office 202',
#         # Évaluations
#         'evaluations-0-titre_evaluation': 'Midterm Exam',
#         'evaluations-0-semaine': '5',
#         'evaluations-0-texte_description': 'Midterm examination covering chapters 1-5.',
#         # Capacités évaluées
#         'evaluations-0-capacites-0-capacite_id': str(capacite.id),
#         'evaluations-0-capacites-0-ponderation': '50',
#     }

#     # POST Request
#     response = client.post(
#         url_for('plan_de_cours.view_plan_de_cours', cours_id=cours.id, session=plan_de_cours.session),
#         headers={'X-Requested-With': 'XMLHttpRequest'},
#         data=form_data
#     )

#     assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"


# def test_plan_cours_coordo_permission_always_allowed(client, test_db, login_user_helper):
#     """ Test that a coordo ALWAYS has access, even without being attached to the programme """
#     # Setup: Create Department, Programme, Coordonateur, Cours, PlanCadre, PlanDeCours
#     department = Department(nom="Test Department")
#     test_db.session.add(department)
#     test_db.session.commit()

#     programme = Programme(nom="Test Programme", department=department)
#     test_db.session.add(programme)
#     test_db.session.commit()

#     # Create Coordonateur (not attached to Programme)
#     coordo = User(username="test_coordo", password="password123", role="coordo")
#     test_db.session.add(coordo)
#     test_db.session.commit()

#     # Create Cours
#     cours = Cours(programme=programme, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
#     test_db.session.add(cours)
#     test_db.session.commit()

#     # Create PlanCadre
#     plan_cadre = PlanCadre(cours=cours)
#     test_db.session.add(plan_cadre)
#     test_db.session.commit()

#     # Create PlanDeCours
#     plan_de_cours = PlanDeCours(cours=cours, session="A2023")
#     test_db.session.add(plan_de_cours)
#     test_db.session.commit()

#     # Create Capacite
#     capacite = Capacite(capacite="Capacité 1", ponderation_min=10, ponderation_max=50)
#     test_db.session.add(capacite)
#     test_db.session.commit()

#     # Login as Coordonateur
#     login_user_helper(coordo)

#     # Prepare Form Data
#     form_data = {
#         'campus': 'Main Campus',
#         'session': 'A2023',
#         'presentation_du_cours': 'Course Presentation',
#         'objectif_terminal_du_cours': 'Course Objectives',
#         'organisation_et_methodes': 'Organization and Methods',
#         'accomodement': 'Accommodations',
#         'evaluation_formative_apprentissages': 'Formative Evaluations',
#         'evaluation_expression_francais': 'French Expression Evaluations',
#         'seuil_reussite': '60%',
#         'materiel': 'Required Materials',
#         'nom_enseignant': 'Dr. John Doe',
#         'telephone_enseignant': '123-456-7890',
#         'courriel_enseignant': 'johndoe@example.com',
#         'bureau_enseignant': 'Room 101',
#         # Calendriers
#         'calendriers-0-semaine': '1',
#         'calendriers-0-sujet': 'Introduction',
#         'calendriers-0-activites': 'Activities Description',
#         'calendriers-0-travaux_hors_classe': 'Homework Description',
#         'calendriers-0-evaluations': 'Evaluation Description',
#         # Médiagraphies
#         'mediagraphies-0-reference_bibliographique': 'Doe, J. (2023). Course Material.',
#         # Disponibilités
#         'disponibilites-0-jour_semaine': 'Monday',
#         'disponibilites-0-plage_horaire': '09:00-11:00',
#         'disponibilites-0-lieu': 'Office 202',
#         # Évaluations
#         'evaluations-0-titre_evaluation': 'Midterm Exam',
#         'evaluations-0-semaine': '5',
#         'evaluations-0-texte_description': 'Midterm examination covering chapters 1-5.',
#         # Capacités évaluées
#         'evaluations-0-capacites-0-capacite_id': str(capacite.id),
#         'evaluations-0-capacites-0-ponderation': '50',
#     }

#     # POST Request
#     response = client.post(
#         url_for('plan_de_cours.view_plan_de_cours', cours_id=cours.id, session=plan_de_cours.session),
#         headers={'X-Requested-With': 'XMLHttpRequest'},
#         data=form_data
#     )

#     assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"




# def test_plan_cours_admin_permission_always_allowed(client, test_db, login_user_helper):
#     """ Test that an admin ALWAYS has access """
#     # Setup: Create Department, Programme, Admin, Cours, PlanCadre, PlanDeCours
#     department = Department(nom="Test Department")
#     test_db.session.add(department)
#     test_db.session.commit()

#     programme = Programme(nom="Test Programme", department=department)
#     test_db.session.add(programme)
#     test_db.session.commit()

#     admin = User(username="test_admin", password="password123", role="admin")
#     test_db.session.add(admin)
#     test_db.session.commit()

#     cours = Cours(programme=programme, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
#     test_db.session.add(cours)
#     test_db.session.commit()

#     plan_cadre = PlanCadre(cours=cours)
#     test_db.session.add(plan_cadre)
#     test_db.session.commit()

#     plan_de_cours = PlanDeCours(cours=cours, session="A2023")
#     test_db.session.add(plan_de_cours)
#     test_db.session.commit()

#     # Login as Admin
#     login_user_helper(admin)

#     # Prepare Form Data
#     form_data = {
#         'campus': 'Main Campus',
#         'session': 'A2023',
#         'presentation_du_cours': 'Course Presentation',
#         'objectif_terminal_du_cours': 'Course Objectives',
#         'organisation_et_methodes': 'Organization and Methods',
#         'accomodement': 'Accommodations',
#         'evaluation_formative_apprentissages': 'Formative Evaluations',
#         'evaluation_expression_francais': 'French Expression Evaluations',
#         'seuil_reussite': '60%',
#         'materiel': 'Required Materials',
#         'nom_enseignant': 'Dr. John Doe',
#         'telephone_enseignant': '123-456-7890',
#         'courriel_enseignant': 'johndoe@example.com',
#         'bureau_enseignant': 'Room 101',
#         # FieldList Entries (Calendriers)
#         'calendriers-0-semaine': '1',
#         'calendriers-0-sujet': 'Introduction',
#         'calendriers-0-activites': 'Activities Description',
#         'calendriers-0-travaux_hors_classe': 'Homework Description',
#         'calendriers-0-evaluations': 'Evaluation Description',
#         # FieldList Entries (Médiagraphie)
#         'mediagraphies-0-reference_bibliographique': 'Doe, J. (2023). Course Material.',
#         # FieldList Entries (Disponibilités)
#         'disponibilites-0-jour_semaine': 'Monday',
#         'disponibilites-0-plage_horaire': '09:00-11:00',
#         'disponibilites-0-lieu': 'Office 202',
#         # FieldList Entries (Évaluations)
#         'evaluations-0-titre_evaluation': 'Midterm Exam',
#         'evaluations-0-semaine': '5',
#         'evaluations-0-texte_description': 'Midterm examination covering chapters 1-5.',
#         # Nested FieldList Entries (Capacités évaluées)
#         'evaluations-0-capacites-0-capacite_id': '1',  # Assuming capacity with ID 1 exists
#         'evaluations-0-capacites-0-ponderation': '50',
#     }

#     # POST Request
#     response = client.post(
#         url_for('plan_de_cours.view_plan_de_cours', cours_id=cours.id, session=plan_de_cours.session),
#         headers={'X-Requested-With': 'XMLHttpRequest'},
#         data=form_data
#     )

#     assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"

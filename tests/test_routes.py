# tests/test_routes.py

from app.models import User, Programme, Cours, PlanCadre, PlanDeCours, Department, PlanCadreCapacites
from flask import url_for
from flask_login import login_user
from app.models import User, Programme, Cours, PlanCadre, PlanDeCours, Department, PlanCadreCapacites
from flask import url_for
import re
from bs4 import BeautifulSoup

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

def test_plan_cours_enseignant_permission_allowed(client, test_db):
    """ Test where a teacher IS attached to the programme => should succeed """
    # Create Department
    department = Department(id=1, nom="Test Department")
    test_db.session.add(department)
    test_db.session.commit()
    
    # Create Programme
    programme = Programme(nom="Test", department_id=department.id)
    test_db.session.add(programme)
    test_db.session.commit()
    
    # Create Teacher and attach to Programme
    enseignant = User(username="test_prof", password="password123", role="professeur")
    enseignant.programmes.append(programme)  # This is the key difference
    test_db.session.add(enseignant)
    test_db.session.commit()
    
    # Create Cours
    cours = Cours(programme_id=programme.id, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
    test_db.session.add(cours)
    test_db.session.commit()
    
    # Create PlanDeCours
    plan_de_cours = PlanDeCours(cours_id=cours.id, session="A2023")
    test_db.session.add(plan_de_cours)
    test_db.session.commit()
    
    # Create PlanCadre
    plan_cadre = PlanCadre(cours_id=cours.id)
    test_db.session.add(plan_cadre)
    test_db.session.commit()
    
    # Create Capacite for evaluations
    capacite = PlanCadreCapacites(plan_cadre_id=plan_cadre.id, capacite="Capacité 1",
                                 ponderation_min=10, ponderation_max=50)
    test_db.session.add(capacite)
    test_db.session.commit()

    with client:
        client.get('/')
        with client.session_transaction() as sess:
            login_user(enseignant)
            sess['_fresh'] = True
            
        # Form data for the plan de cours
        form_data = {
            'campus': 'Main Campus',
            'session': 'A2023',
            'presentation_du_cours': 'Course Presentation',
            'objectif_terminal_du_cours': 'Course Objectives',
            'organisation_et_methodes': 'Organization and Methods',
            'accomodement': 'Accommodations',
            'evaluation_formative_apprentissages': 'Formative Evaluations',
            'evaluation_expression_francais': 'French Expression Evaluations',
            'seuil_reussite': '60%',
            'materiel': 'Required Materials',
            'nom_enseignant': 'Dr. John Doe',
            'telephone_enseignant': '123-456-7890',
            'courriel_enseignant': 'johndoe@example.com',
            'bureau_enseignant': 'Room 101',
            'evaluations': [{
                'titre_evaluation': 'Midterm Exam',
                'semaine': '5',
                'texte_description': 'Midterm examination covering chapters 1-5',
                'capacites': [{
                    'capacite_id': capacite.id,
                    'ponderation': 50
                }]
            }]
        }

        response = client.post(
            f'/cours/{cours.id}/plan_de_cours/A2023/',
            headers={'X-Requested-With': 'XMLHttpRequest'},
            json=form_data
        )
        
        assert response.status_code == 200
        assert response.is_json
        response_data = response.get_json()
        assert response_data['success'] is True


def test_plan_cours_coordo_permission_always_allowed(client, test_db):
    """ Test where a teacher IS attached to the programme => should succeed """
    # Create Department
    department = Department(id=1, nom="Test Department")
    test_db.session.add(department)
    test_db.session.commit()
    
    # Create Programme
    programme = Programme(nom="Test", department_id=department.id)
    test_db.session.add(programme)
    test_db.session.commit()
    
    # Create Teacher and attach to Programme
    enseignant = User(username="test_prof", password="password123", role="coordo")
    test_db.session.add(enseignant)
    test_db.session.commit()
    
    # Create Cours
    cours = Cours(programme_id=programme.id, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
    test_db.session.add(cours)
    test_db.session.commit()
    
    # Create PlanDeCours
    plan_de_cours = PlanDeCours(cours_id=cours.id, session="A2023")
    test_db.session.add(plan_de_cours)
    test_db.session.commit()
    
    # Create PlanCadre
    plan_cadre = PlanCadre(cours_id=cours.id)
    test_db.session.add(plan_cadre)
    test_db.session.commit()
    
    # Create Capacite for evaluations
    capacite = PlanCadreCapacites(plan_cadre_id=plan_cadre.id, capacite="Capacité 1",
                                 ponderation_min=10, ponderation_max=50)
    test_db.session.add(capacite)
    test_db.session.commit()

    with client:
        client.get('/')
        with client.session_transaction() as sess:
            login_user(enseignant)
            sess['_fresh'] = True
            
        # Form data for the plan de cours
        form_data = {
            'campus': 'Main Campus',
            'session': 'A2023',
            'presentation_du_cours': 'Course Presentation',
            'objectif_terminal_du_cours': 'Course Objectives',
            'organisation_et_methodes': 'Organization and Methods',
            'accomodement': 'Accommodations',
            'evaluation_formative_apprentissages': 'Formative Evaluations',
            'evaluation_expression_francais': 'French Expression Evaluations',
            'seuil_reussite': '60%',
            'materiel': 'Required Materials',
            'nom_enseignant': 'Dr. John Doe',
            'telephone_enseignant': '123-456-7890',
            'courriel_enseignant': 'johndoe@example.com',
            'bureau_enseignant': 'Room 101',
            'evaluations': [{
                'titre_evaluation': 'Midterm Exam',
                'semaine': '5',
                'texte_description': 'Midterm examination covering chapters 1-5',
                'capacites': [{
                    'capacite_id': capacite.id,
                    'ponderation': 50
                }]
            }]
        }

        response = client.post(
            f'/cours/{cours.id}/plan_de_cours/A2023/',
            headers={'X-Requested-With': 'XMLHttpRequest'},
            json=form_data
        )
        
        assert response.status_code == 200
        assert response.is_json
        response_data = response.get_json()
        assert response_data['success'] is True

def test_plan_cours_admin_permission_always_allowed(client, test_db):
    """ Test where a teacher IS attached to the programme => should succeed """
    # Create Department
    department = Department(id=1, nom="Test Department")
    test_db.session.add(department)
    test_db.session.commit()
    
    # Create Programme
    programme = Programme(nom="Test", department_id=department.id)
    test_db.session.add(programme)
    test_db.session.commit()
    
    # Create Teacher and attach to Programme
    enseignant = User(username="test_prof", password="password123", role="admin")
    test_db.session.add(enseignant)
    test_db.session.commit()
    
    # Create Cours
    cours = Cours(programme_id=programme.id, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
    test_db.session.add(cours)
    test_db.session.commit()
    
    # Create PlanDeCours
    plan_de_cours = PlanDeCours(cours_id=cours.id, session="A2023")
    test_db.session.add(plan_de_cours)
    test_db.session.commit()
    
    # Create PlanCadre
    plan_cadre = PlanCadre(cours_id=cours.id)
    test_db.session.add(plan_cadre)
    test_db.session.commit()
    
    # Create Capacite for evaluations
    capacite = PlanCadreCapacites(plan_cadre_id=plan_cadre.id, capacite="Capacité 1",
                                 ponderation_min=10, ponderation_max=50)
    test_db.session.add(capacite)
    test_db.session.commit()

    with client:
        client.get('/')
        with client.session_transaction() as sess:
            login_user(enseignant)
            sess['_fresh'] = True
            
        # Form data for the plan de cours
        form_data = {
            'campus': 'Main Campus',
            'session': 'A2023',
            'presentation_du_cours': 'Course Presentation',
            'objectif_terminal_du_cours': 'Course Objectives',
            'organisation_et_methodes': 'Organization and Methods',
            'accomodement': 'Accommodations',
            'evaluation_formative_apprentissages': 'Formative Evaluations',
            'evaluation_expression_francais': 'French Expression Evaluations',
            'seuil_reussite': '60%',
            'materiel': 'Required Materials',
            'nom_enseignant': 'Dr. John Doe',
            'telephone_enseignant': '123-456-7890',
            'courriel_enseignant': 'johndoe@example.com',
            'bureau_enseignant': 'Room 101',
            'evaluations': [{
                'titre_evaluation': 'Midterm Exam',
                'semaine': '5',
                'texte_description': 'Midterm examination covering chapters 1-5',
                'capacites': [{
                    'capacite_id': capacite.id,
                    'ponderation': 50
                }]
            }]
        }

        response = client.post(
            f'/cours/{cours.id}/plan_de_cours/A2023/',
            headers={'X-Requested-With': 'XMLHttpRequest'},
            json=form_data
        )
        
        assert response.status_code == 200
        assert response.is_json
        response_data = response.get_json()
        assert response_data['success'] is True
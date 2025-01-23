# programme.py
from flask import Blueprint, Flask, render_template, redirect, url_for, request, flash, send_file, jsonify
from forms import (
    ProgrammeForm,
    CompetenceForm,
    ElementCompetenceForm,
    FilConducteurForm,
    CoursForm,
    CoursPrealableForm,
    CoursCorequisForm,
    CompetenceParCoursForm,
    ElementCompetenceParCoursForm,
    DeleteForm,
    MultiCheckboxField,
    PlanCadreForm,
    SavoirEtreForm,
    CompetenceDeveloppeeForm,
    ObjetCibleForm,
    CoursRelieForm,
    CoursPrealableForm,
    DuplicatePlanCadreForm,
    ImportPlanCadreForm,
    PlanCadreCompetenceCertifieeForm,
    PlanCadreCoursCorequisForm,
    GenerateContentForm,
    GlobalGenerationSettingsForm, 
    GenerationSettingForm
)
from flask_ckeditor import CKEditor
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3
import json
import logging
from collections import defaultdict
from openai import OpenAI
from openai import OpenAIError
from decorator import role_required, roles_required
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import os
import markdown
from jinja2 import Template
import bleach
from docxtpl import DocxTemplate
from io import BytesIO 
from werkzeug.security import generate_password_hash, check_password_hash
from utils import get_db_connection, parse_html_to_list, parse_html_to_nested_list, get_plan_cadre_data, replace_tags_jinja2, process_ai_prompt, generate_docx_with_template
from models import User
from routes.plan_de_cours import plan_de_cours_bp

programme_bp = Blueprint('programme', __name__, url_prefix='/programme')


@programme_bp.route('/<int:programme_id>')
@login_required
def view_programme(programme_id):
    conn = get_db_connection()
    
    # Récupérer le programme
    programme = conn.execute('SELECT * FROM Programme WHERE id = ?', (programme_id,)).fetchone()
    
    if not programme:
        flash('Programme non trouvé.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))
    
    # Récupérer les compétences associées au programme
    competences = conn.execute('SELECT * FROM Competence WHERE programme_id = ?', (programme_id,)).fetchall()
    
    # Récupérer les fils conducteurs associés au programme
    fil_conducteurs = conn.execute('SELECT * FROM FilConducteur WHERE programme_id = ?', (programme_id,)).fetchall()
    
    # Récupérer les cours associés au programme avec les informations du fil conducteur
    cours = conn.execute('''
        SELECT c.*, fc.id AS fil_conducteur_id, fc.description AS fil_description, fc.couleur AS fil_couleur
        FROM Cours c
        LEFT JOIN FilConducteur fc ON c.fil_conducteur_id = fc.id
        WHERE c.programme_id = ?
        ORDER BY c.session ASC
    ''', (programme_id,)).fetchall()
    
    # Regrouper les cours par session
    cours_par_session = defaultdict(list)
    for c in cours:
        session = c['session']
        cours_par_session[session].append(c)
    
    # Récupérer les prérequis et co-requis avec les codes des cours
    prerequisites = {}
    corequisites = {}
    for c in cours:
        # Récupérer les cours préalables avec leurs codes
        prereqs = conn.execute(''' 
            SELECT c_p.nom, c_p.code, cp.note_necessaire 
            FROM CoursPrealable cp
            JOIN Cours c_p ON cp.cours_prealable_id = c_p.id
            WHERE cp.cours_id = ?
        ''', (c['id'],)).fetchall()

        # Inclure la note dans les prérequis
        prerequisites[c['id']] = [(f"{p['code']} - {p['nom']}", p['note_necessaire']) for p in prereqs]

        
        # Récupérer les cours corequis avec leurs codes
        coreqs = conn.execute(''' 
            SELECT c_c.nom, c_c.code 
            FROM CoursCorequis cc
            JOIN Cours c_c ON cc.cours_corequis_id = c_c.id
            WHERE cc.cours_id = ?
        ''', (c['id'],)).fetchall()
        corequisites[c['id']] = [f"{c_core['code']} - {c_core['nom']}" for c_core in coreqs]
    
    # Récupérer les codes des compétences par cours
    competencies_codes = {}
    for c in cours:
        comps = conn.execute(''' 
            SELECT DISTINCT c.code AS competence_code
FROM ElementCompetenceParCours ecp
JOIN ElementCompetence ec ON ecp.element_competence_id = ec.id
JOIN Competence c ON ec.competence_id = c.id
WHERE ecp.cours_id = ?
  AND ecp.status IN ('Développé significativement', 'Atteint');
        ''', (c['id'],)).fetchall()
        competencies_codes[c['id']] = [comp['competence_code'] for comp in comps]
    
    # Calcul des totaux
    total_heures_theorie = sum(c['heures_theorie'] for c in cours)
    total_heures_laboratoire = sum(c['heures_laboratoire'] for c in cours)
    total_heures_travail_maison = sum(c['heures_travail_maison'] for c in cours)
    total_unites = sum(c['nombre_unites'] for c in cours)
    
    # Créer des dictionnaires de formulaires de suppression pour les compétences et les cours
    delete_forms_competences = {competence['id']: DeleteForm(prefix=f"competence-{competence['id']}") for competence in competences}
    delete_forms_cours = {c['id']: DeleteForm(prefix=f"cours-{c['id']}") for c in cours}

    programmes = conn.execute('SELECT * FROM Programme').fetchall()

    conn.close()
    
    return render_template('view_programme.html', 
                           programme=programme, 
                           programmes=programmes,
                           competences=competences, 
                           fil_conducteurs=fil_conducteurs, 
                           cours_par_session=cours_par_session,  # Groupement par session
                           delete_forms_competences=delete_forms_competences,
                           delete_forms_cours=delete_forms_cours,
                           prerequisites=prerequisites,
                           corequisites=corequisites,
                           competencies_codes=competencies_codes,  # Codes des compétences
                           total_heures_theorie=total_heures_theorie,
                           total_heures_laboratoire=total_heures_laboratoire,
                           total_heures_travail_maison=total_heures_travail_maison,
                           total_unites=total_unites
                           )

@programme_bp.route('/competence/<int:competence_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
def edit_competence(competence_id):
    form = CompetenceForm()
    conn = get_db_connection()
    competence = conn.execute('SELECT * FROM Competence WHERE id = ?', (competence_id,)).fetchone()
    programmes = conn.execute('SELECT id, nom FROM Programme').fetchall()
    conn.close()

    if competence is None:
        flash('Compétence non trouvée.', 'danger')
        return redirect(url_for('main.index'))

    form.programme.choices = [(p['id'], p['nom']) for p in programmes]

    if request.method == 'POST' and form.validate_on_submit():
        programme_id = form.programme.data
        code = form.code.data
        nom = form.nom.data
        criteria_de_performance = form.criteria_de_performance.data
        contexte_de_realisation = form.contexte_de_realisation.data

        try:
            conn = get_db_connection()
            conn.execute('''
                UPDATE Competence
                SET programme_id = ?, code = ?, nom = ?, criteria_de_performance = ?, contexte_de_realisation = ?
                WHERE id = ?
            ''', (programme_id, code, nom, criteria_de_performance, contexte_de_realisation, competence_id))
            conn.commit()
            conn.close()
            flash('Compétence mise à jour avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=programme_id))
        except sqlite3.Error as e:
            flash(f'Erreur lors de la mise à jour de la compétence : {e}', 'danger')
            return redirect(url_for('main.edit_competence', competence_id=competence_id))
    else:
        # Pré-remplir le formulaire avec les données existantes
        form.programme.data = competence['programme_id']
        form.code.data = competence['code'] if competence['code'] else ''
        form.nom.data = competence['nom']
        form.criteria_de_performance.data = competence['criteria_de_performance']
        form.contexte_de_realisation.data = competence['contexte_de_realisation']

    return render_template('edit_competence.html', form=form, competence=competence)

@programme_bp.route('/competence/<int:competence_id>/delete', methods=['POST'])
@role_required('admin')
def delete_competence(competence_id):
    # Instancier le formulaire avec le préfixe correspondant
    delete_form = DeleteForm(prefix=f"competence-{competence_id}")
    
    if delete_form.validate_on_submit():
        conn = get_db_connection()
        
        # Récupérer le programme_id avant de supprimer la compétence
        competence = conn.execute('SELECT programme_id FROM Competence WHERE id = ?', (competence_id,)).fetchone()
        
        if not competence:
            flash('Compétence non trouvée.', 'danger')
            conn.close()
            return redirect(url_for('main.index'))
        
        programme_id = competence['programme_id']
        
        try:
            # Supprimer la compétence
            conn.execute('DELETE FROM Competence WHERE id = ?', (competence_id,))
            conn.commit()
            flash('Compétence supprimée avec succès!', 'success')
        except sqlite3.IntegrityError as e:
            # Gérer les erreurs de contraintes de clés étrangères
            flash(f'Erreur de contrainte de clé étrangère : {e}', 'danger')
        except sqlite3.Error as e:
            # Gérer d'autres erreurs SQLite
            flash(f'Erreur lors de la suppression de la compétence : {e}', 'danger')
        finally:
            conn.close()
        
        # Rediriger vers la vue du programme
        return redirect(url_for('programme.view_programme', programme_id=programme_id))
    else:
        flash('Formulaire de suppression invalide.', 'danger')
        return redirect(url_for('main.index'))


@programme_bp.route('/competence/code/<string:competence_code>')
@role_required('admin')
def view_competence_by_code(competence_code):
    conn = get_db_connection()
    competence = conn.execute('SELECT id FROM Competence WHERE code = ?', (competence_code,)).fetchone()
    conn.close()

    if not competence:
        flash('Compétence non trouvée.', 'danger')
        return redirect(url_for('main.index'))

    # Rediriger vers la route existante avec competence_id
    return redirect(url_for('programme.view_competence', competence_id=competence['id']))


@programme_bp.route('/competence/<int:competence_id>')
@login_required
def view_competence(competence_id):
    conn = get_db_connection()
    competence = conn.execute('''
        SELECT Competence.*, Programme.nom as programme_nom
        FROM Competence
        JOIN Programme ON Competence.programme_id = Programme.id
        WHERE Competence.id = ?
    ''', (competence_id,)).fetchone()

    if not competence:
        flash('Compétence non trouvée.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))

    # Définir les balises et attributs autorisés pour le nettoyage
    allowed_tags = [
        'ul', 'ol', 'li', 'strong', 'em', 'p', 'br', 'a', 
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
    ]
    allowed_attributes = {
        'a': ['href', 'title', 'target']
    }

    # Nettoyer les contenus principaux
    criteria_content = competence['criteria_de_performance'] or ""
    context_content = competence['contexte_de_realisation'] or ""

    if not isinstance(criteria_content, str):
        criteria_content = str(criteria_content)
    if not isinstance(context_content, str):
        context_content = str(context_content)

    try:
        criteria_html = bleach.clean(
            criteria_content,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True
        )
        context_html = bleach.clean(
            context_content,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True
        )
    except Exception as e:
        flash(f'Erreur lors du nettoyage du contenu : {e}', 'danger')
        criteria_html = ""
        context_html = ""

    # Récupérer les éléments de compétence et leurs critères de performance
    elements = conn.execute('''
        SELECT e.id, e.nom, ec.criteria
        FROM ElementCompetence e
        LEFT JOIN ElementCompetenceCriteria ec ON e.id = ec.element_competence_id
        WHERE e.competence_id = ?
    ''', (competence_id,)).fetchall()

    # Organiser les critères par élément de compétence
    elements_dict = {}
    for row in elements:
        element_id = row['id']
        element_nom = row['nom']
        criteria = row['criteria']
        if element_id not in elements_dict:
            elements_dict[element_id] = {
                'nom': element_nom,
                'criteres': []
            }
        if criteria:
            elements_dict[element_id]['criteres'].append(criteria)

    

    conn.close()

    # Instancier le formulaire de suppression pour cette compétence
    delete_form = DeleteForm(prefix=f"competence-{competence['id']}")

    return render_template(
        'view_competence.html',
        competence=competence,
        criteria_html=criteria_html,
        context_html=context_html,
        elements_competence=elements_dict,
        delete_form=delete_form
    )
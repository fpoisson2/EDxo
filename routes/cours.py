# plan_cadre.py
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
    CapaciteItemForm,
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
from dotenv import load_dotenv
from decorator import role_required, roles_required
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
from flask_wtf.csrf import validate_csrf, CSRFError


cours_bp = Blueprint('cours', __name__, url_prefix='/cours')


@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>/import_json', methods=['POST'])
@role_required('admin')
def import_plan_cadre_json(cours_id, plan_id):
    form = ImportPlanCadreForm()
    if form.validate_on_submit():
        json_file = form.json_file.data

        try:
            # Lire le contenu du fichier JSON
            file_content = json_file.read().decode('utf-8')
            data = json.loads(file_content)

            # Valider la structure du JSON
            required_keys = ['plan_cadre', 'competences_developpees', 'objets_cibles', 
                             'cours_relies', 'cours_prealables', 'capacites', 'savoir_etre']
            for key in required_keys:
                if key not in data:
                    flash(f'Clé manquante dans le JSON: {key}', 'danger')
                    return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))

            # Extraire les données
            plan_cadre_data = data['plan_cadre']
            competences_developpees_data = data['competences_developpees']
            objets_cibles_data = data['objets_cibles']
            cours_relies_data = data['cours_relies']
            cours_prealables_data = data['cours_prealables']
            capacites_data = data['capacites']
            savoir_etre_data = data['savoir_etre']

            # Vérifier que le plan_cadre_id dans JSON correspond à celui de l'URL
            if plan_cadre_data['id'] != plan_id:
                flash('L\'ID du plan-cadre dans le JSON ne correspond pas à l\'ID de l\'URL.', 'danger')
                return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))

            # Ouvrir une connexion à la base de données
            conn = get_db_connection()
            cursor = conn.cursor()

            # Démarrer une transaction
            cursor.execute('BEGIN')

            # Mettre à jour les champs principaux du plan_cadre
            cursor.execute("""
                UPDATE PlanCadre 
                SET place_intro = ?, objectif_terminal = ?, structure_intro = ?, 
                    structure_activites_theoriques = ?, structure_activites_pratiques = ?, 
                    structure_activites_prevues = ?, eval_evaluation_sommative = ?, 
                    eval_nature_evaluations_sommatives = ?, eval_evaluation_de_la_langue = ?, 
                    eval_evaluation_sommatives_apprentissages = ?
                WHERE id = ? AND cours_id = ?
            """, (
                plan_cadre_data['place_intro'],
                plan_cadre_data['objectif_terminal'],
                plan_cadre_data['structure_intro'],
                plan_cadre_data['structure_activites_theoriques'],
                plan_cadre_data['structure_activites_pratiques'],
                plan_cadre_data['structure_activites_prevues'],
                plan_cadre_data['eval_evaluation_sommative'],
                plan_cadre_data['eval_nature_evaluations_sommatives'],
                plan_cadre_data['eval_evaluation_de_la_langue'],
                plan_cadre_data['eval_evaluation_sommatives_apprentissages'],
                plan_id,
                cours_id
            ))

            # Remplacer les données des compétences développées
            cursor.execute('DELETE FROM PlanCadreCompetencesDeveloppees WHERE plan_cadre_id = ?', (plan_id,))
            for competence in competences_developpees_data:
                # Validation des champs
                if 'texte' not in competence or 'description' not in competence:
                    raise ValueError('Les compétences développées doivent contenir "texte" et "description".')
                cursor.execute('''
                    INSERT INTO PlanCadreCompetencesDeveloppees (plan_cadre_id, texte, description) 
                    VALUES (?, ?, ?)
                ''', (plan_id, competence['texte'], competence['description']))

            # Remplacer les données des objets cibles
            cursor.execute('DELETE FROM PlanCadreObjetsCibles WHERE plan_cadre_id = ?', (plan_id,))
            for objet in objets_cibles_data:
                if 'texte' not in objet or 'description' not in objet:
                    raise ValueError('Les objets cibles doivent contenir "texte" et "description".')
                cursor.execute('''
                    INSERT INTO PlanCadreObjetsCibles (plan_cadre_id, texte, description) 
                    VALUES (?, ?, ?)
                ''', (plan_id, objet['texte'], objet['description']))

            # Remplacer les données des cours reliés
            cursor.execute('DELETE FROM PlanCadreCoursRelies WHERE plan_cadre_id = ?', (plan_id,))
            for cr in cours_relies_data:
                if 'texte' not in cr or 'description' not in cr:
                    raise ValueError('Les cours reliés doivent contenir "texte" et "description".')
                cursor.execute('''
                    INSERT INTO PlanCadreCoursRelies (plan_cadre_id, texte, description) 
                    VALUES (?, ?, ?)
                ''', (plan_id, cr['texte'], cr['description']))

            # Remplacer les données des cours préalables
            cursor.execute('DELETE FROM PlanCadreCoursPrealables WHERE plan_cadre_id = ?', (plan_id,))
            for cp in cours_prealables_data:
                if 'texte' not in cp or 'description' not in cp:
                    raise ValueError('Les cours préalables doivent contenir "texte" et "description".')
                cursor.execute('''
                    INSERT INTO PlanCadreCoursPrealables (plan_cadre_id, texte, description) 
                    VALUES (?, ?, ?)
                ''', (plan_id, cp['texte'], cp['description']))

            # Remplacer les données des capacités
            cursor.execute('DELETE FROM PlanCadreCapacites WHERE plan_cadre_id = ?', (plan_id,))
            for cap in capacites_data:
                required_cap_keys = ['capacite', 'description_capacite', 'ponderation_min', 'ponderation_max']
                if not all(k in cap for k in required_cap_keys):
                    raise ValueError(f'Chaque capacité doit contenir {required_cap_keys}')
                cursor.execute('''
                    INSERT INTO PlanCadreCapacites (plan_cadre_id, capacite, description_capacite, ponderation_min, ponderation_max)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    plan_id,
                    cap['capacite'],
                    cap['description_capacite'],
                    cap['ponderation_min'],
                    cap['ponderation_max']
                ))
                new_cap_id = cursor.lastrowid

                # Insérer les savoirs nécessaires (liste de chaînes)
                for sav in cap.get('savoirs_necessaires', []):
                    # Modification ici : sav est une chaîne de caractères, pas un dict
                    if not isinstance(sav, str) or not sav.strip():
                        raise ValueError('Chaque savoir nécessaire doit contenir "texte".')
                    cursor.execute('''
                        INSERT INTO PlanCadreCapaciteSavoirsNecessaires (capacite_id, texte)
                        VALUES (?, ?)
                    ''', (new_cap_id, sav))

                # Insérer les savoirs faire
                for sf in cap.get('savoirs_faire', []):
                    required_sf_keys = ['texte', 'cible', 'seuil_reussite']
                    if not all(k in sf for k in required_sf_keys):
                        raise ValueError(f'Chaque savoir faire doit contenir {required_sf_keys}')
                    cursor.execute('''
                        INSERT INTO PlanCadreCapaciteSavoirsFaire (capacite_id, texte, cible, seuil_reussite)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        new_cap_id,
                        sf['texte'],
                        sf['cible'],
                        sf['seuil_reussite']
                    ))

                # Insérer les moyens d'évaluation (liste de chaînes)
                for me in cap.get('moyens_evaluation', []):
                    if not isinstance(me, str) or not me.strip():
                        raise ValueError('Chaque moyen d\'évaluation doit contenir "texte".')
                    cursor.execute('''
                        INSERT INTO PlanCadreCapaciteMoyensEvaluation (capacite_id, texte)
                        VALUES (?, ?)
                    ''', (new_cap_id, me))

            # Remplacer les données du savoir-être
            cursor.execute('DELETE FROM PlanCadreSavoirEtre WHERE plan_cadre_id = ?', (plan_id,))
            for se in savoir_etre_data:
                if 'texte' not in se:
                    raise ValueError('Chaque savoir-être doit contenir "texte".')
                cursor.execute('''
                    INSERT INTO PlanCadreSavoirEtre (plan_cadre_id, texte) 
                    VALUES (?, ?)
                ''', (plan_id, se['texte']))

            # Valider et committer la transaction
            conn.commit()
            conn.close()

            flash('Importation JSON réussie et données du Plan Cadre mises à jour avec succès!', 'success')
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))

        except json.JSONDecodeError:
            flash('Le fichier importé n\'est pas un fichier JSON valide.', 'danger')
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        except ValueError as ve:
            flash(f'Erreur de validation des données : {ve}', 'danger')
            conn.rollback()
            conn.close()
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        except sqlite3.Error as e:
            flash(f'Erreur de base de données lors de l\'importation : {e}', 'danger')
            conn.rollback()
            conn.close()
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
    else:
        # Gérer les erreurs de validation de formulaire
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'Erreur dans le champ "{getattr(form, field).label.text}": {error}', 'danger')
        return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))


@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>/export_json', methods=['GET'])
@login_required
def export_plan_cadre_json(cours_id, plan_id):
    conn = get_db_connection()
    
    # Vérifier que le plan-cadre appartient au cours spécifié
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ? AND cours_id = ?', (plan_id, cours_id)).fetchone()
    if not plan:
        flash('Plan Cadre non trouvé pour ce cours.', 'danger')
        conn.close()
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    
    # Récupérer les sections
    competences_developpees = conn.execute(
        'SELECT texte, description FROM PlanCadreCompetencesDeveloppees WHERE plan_cadre_id = ?', 
        (plan_id,)
    ).fetchall()
    objets_cibles = conn.execute(
        'SELECT texte, description FROM PlanCadreObjetsCibles WHERE plan_cadre_id = ?', 
        (plan_id,)
    ).fetchall()
    cours_relies = conn.execute(
        'SELECT texte, description FROM PlanCadreCoursRelies WHERE plan_cadre_id = ?', 
        (plan_id,)
    ).fetchall()
    cours_prealables = conn.execute(
        'SELECT texte, description FROM PlanCadreCoursPrealables WHERE plan_cadre_id = ?', 
        (plan_id,)
    ).fetchall()
    capacites = conn.execute(
        'SELECT * FROM PlanCadreCapacites WHERE plan_cadre_id = ?', 
        (plan_id,)
    ).fetchall()
    savoir_etre = conn.execute(
        'SELECT texte FROM PlanCadreSavoirEtre WHERE plan_cadre_id = ?', 
        (plan_id,)
    ).fetchall()
    
    # Récupérer les détails des capacités
    capacites_detail = []
    for cap in capacites:
        cap_id = cap['id']
        sav_necessaires = conn.execute(
            'SELECT texte FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?', 
            (cap_id,)
        ).fetchall()
        sav_faire = conn.execute(
            'SELECT texte, cible, seuil_reussite FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?', 
            (cap_id,)
        ).fetchall()
        moyens_eval = conn.execute(
            'SELECT texte FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?', 
            (cap_id,)
        ).fetchall()
        
        capacites_detail.append({
            'id': cap['id'],
            'capacite': cap['capacite'],
            'description_capacite': cap['description_capacite'],
            'ponderation_min': cap['ponderation_min'],
            'ponderation_max': cap['ponderation_max'],
            'savoirs_necessaires': [sav['texte'] for sav in sav_necessaires],
            'savoirs_faire': [
                {
                    'texte': sf['texte'],
                    'cible': sf['cible'],
                    'seuil_reussite': sf['seuil_reussite']
                } for sf in sav_faire
            ],
            'moyens_evaluation': [me['texte'] for me in moyens_eval]
        })
    
    # Structurer les données
    data = {
        'plan_cadre': {
            'id': plan['id'],
            'cours_id': plan['cours_id'],
            'place_intro': plan['place_intro'],
            'objectif_terminal': plan['objectif_terminal'],
            'structure_intro': plan['structure_intro'],
            'structure_activites_theoriques': plan['structure_activites_theoriques'],
            'structure_activites_pratiques': plan['structure_activites_pratiques'],
            'structure_activites_prevues': plan['structure_activites_prevues'],
            'eval_evaluation_sommative': plan['eval_evaluation_sommative'],
            'eval_nature_evaluations_sommatives': plan['eval_nature_evaluations_sommatives'],
            'eval_evaluation_de_la_langue': plan['eval_evaluation_de_la_langue'],
            'eval_evaluation_sommatives_apprentissages': plan['eval_evaluation_sommatives_apprentissages']
        },
        'competences_developpees': [
            {'texte': c['texte'], 'description': c['description']} for c in competences_developpees
        ],
        'objets_cibles': [
            {'texte': o['texte'], 'description': o['description']} for o in objets_cibles
        ],
        'cours_relies': [
            {'texte': cr['texte'], 'description': cr['description']} for cr in cours_relies
        ],
        'cours_prealables': [
            {'texte': cp['texte'], 'description': cp['description']} for cp in cours_prealables
        ],
        'capacites': capacites_detail,
        'savoir_etre': [
            {'texte': se['texte']} for se in savoir_etre
        ]
    }
    
    conn.close()
    
    # Convertir les données en JSON avec une indentation pour une meilleure lisibilité
    json_data = json.dumps(data, indent=4, ensure_ascii=False)
    
    # Envoyer le fichier JSON à l'utilisateur
    return send_file(
        BytesIO(json_data.encode('utf-8')),
        mimetype='application/json',
        as_attachment=True,
        download_name=f'Plan_Cadre_{plan_id}.json'
    )

# Route pour ajouter un Plan Cadre à un cours
@cours_bp.route('/<int:cours_id>/plan_cadre/add', methods=['GET', 'POST'])
@login_required
def add_plan_cadre(cours_id):
    conn = get_db_connection()
    try:
        # Créer un plan-cadre avec des valeurs par défaut
        cursor = conn.execute("""
            INSERT INTO PlanCadre 
            (cours_id, place_intro, objectif_terminal, structure_intro, structure_activites_theoriques, 
            structure_activites_pratiques, structure_activites_prevues, eval_evaluation_sommative, 
            eval_nature_evaluations_sommatives, eval_evaluation_de_la_langue, eval_evaluation_sommatives_apprentissages)
            VALUES (?, '', '', '', '', '', '', '', '', '', '')
        """, (cours_id,))
        conn.commit()
        
        # Récupérer l'ID du plan-cadre nouvellement créé
        plan_cadre_id = cursor.lastrowid
        
        flash('Plan Cadre créé avec succès!', 'success')
        # Rediriger vers la page view_plan_cadre
        return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_cadre_id))
    except sqlite3.IntegrityError:
        flash('Un Plan Cadre existe déjà pour ce cours.', 'danger')
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    except sqlite3.Error as e:
        flash(f'Erreur lors de l\'ajout du Plan Cadre : {e}', 'danger')
    finally:
        conn.close()
def get_plan_cadre(conn, plan_id, cours_id):
    plan_row = conn.execute(
        'SELECT * FROM PlanCadre WHERE id = ? AND cours_id = ?',
        (plan_id, cours_id)
    ).fetchone()
    return plan_row

def get_cours_details(conn, cours_id):
    cours = conn.execute('''
        SELECT Cours.*, Programme.nom as programme_nom 
        FROM Cours 
        JOIN Programme ON Cours.programme_id = Programme.id 
        WHERE Cours.id = ?
    ''', (cours_id,)).fetchone()
    return cours

def get_related_courses(conn, cours_id, relation_table, relation_field):
    related = conn.execute(f'SELECT {relation_field} FROM {relation_table} WHERE cours_id = ?', (cours_id,)).fetchall()
    related_ids = [item[0] for item in related]  # Access the first column of each result
    
    details = []
    if related_ids:
        placeholders = ','.join(['?'] * len(related_ids))
        details = conn.execute(f'''
            SELECT id, nom, code 
            FROM Cours 
            WHERE id IN ({placeholders})
        ''', related_ids).fetchall()
    return details


def get_competences(conn, cours_id, type_competence):
    if type_competence == 'developpees':
        query = '''
            SELECT Competence.nom 
            FROM CompetenceParCours
            JOIN Competence ON CompetenceParCours.competence_developpee_id = Competence.id
            WHERE CompetenceParCours.cours_id = ? AND CompetenceParCours.competence_developpee_id IS NOT NULL
        '''
    elif type_competence == 'atteintes':
        query = '''
            SELECT Competence.nom 
            FROM CompetenceParCours
            JOIN Competence ON CompetenceParCours.competence_atteinte_id = Competence.id
            WHERE CompetenceParCours.cours_id = ? AND CompetenceParCours.competence_atteinte_id IS NOT NULL
        '''
    else:
        return []
    
    competences = conn.execute(query, (cours_id,)).fetchall()
    return competences

def get_elements_competence(conn, cours_id):
    elements = conn.execute('''
        SELECT 
            c.id AS competence_id,
            ec.nom AS element_competence_nom, 
            c.code AS competence_code,
            c.nom AS competence_nom,
            ecp.status
        FROM ElementCompetenceParCours ecp
        JOIN ElementCompetence ec ON ecp.element_competence_id = ec.id
        JOIN Competence c ON ec.competence_id = c.id
        WHERE ecp.cours_id = ?
    ''', (cours_id,)).fetchall()
    
    grouped = {}
    for ec in elements:
        competence_id = ec['competence_id']
        if competence_id not in grouped:
            grouped[competence_id] = {
                'nom': ec['competence_nom'],
                'code': ec['competence_code'],
                'elements': []
            }
        grouped[competence_id]['elements'].append({
            'element_competence_nom': ec['element_competence_nom'],
            'status': ec['status']
        })
    return grouped

# --- Form Preparation Helpers ---

def prepare_plan_form(plan_row):
    plan_data = {
        'place_intro': plan_row['place_intro'] or "",
        'objectif_terminal': plan_row['objectif_terminal'] or "",
        'structure_intro': plan_row['structure_intro'] or "",
        'structure_activites_theoriques': plan_row['structure_activites_theoriques'] or "",
        'structure_activites_pratiques': plan_row['structure_activites_pratiques'] or "",
        'structure_activites_prevues': plan_row['structure_activites_prevues'] or "",
        'eval_evaluation_sommative': plan_row['eval_evaluation_sommative'] or "",
        'eval_nature_evaluations_sommatives': plan_row['eval_nature_evaluations_sommatives'] or "",
        'eval_evaluation_de_la_langue': plan_row['eval_evaluation_de_la_langue'] or "",
        'eval_evaluation_sommatives_apprentissages': plan_row['eval_evaluation_sommatives_apprentissages'] or ""
    }
    plan_form = PlanCadreForm(data=plan_data)
    return plan_form

def populate_field_lists(conn, plan_id, plan_form):
    # Define the mapping between form fields and database tables
    field_mappings = {
        'competences_developpees': 'PlanCadreCompetencesDeveloppees',
        'objets_cibles': 'PlanCadreObjetsCibles',
        'competences_certifiees': 'PlanCadreCompetencesCertifiees',
        'cours_corequis': 'PlanCadreCoursCorequis',
        'cours_prealables': 'PlanCadreCoursPrealables',
        'cours_relies': 'PlanCadreCoursRelies',
        'savoir_etre': 'PlanCadreSavoirEtre'
    }
    
    # Map database columns to WTForms fields if names differ
    column_to_field_map = {
        'texte': 'texte',
        'description': 'texte_description'
    }
    
    for field, table in field_mappings.items():
        rows = conn.execute(
            f'SELECT * FROM {table} WHERE plan_cadre_id = ?',
            (plan_id,)
        ).fetchall()
        for row in rows:
            entry = getattr(plan_form, field).append_entry()
            for column_name in row.keys():
                # Map database column to WTForms field name
                field_name = column_to_field_map.get(column_name, column_name)
                if hasattr(entry, field_name) and hasattr(getattr(entry, field_name), 'data'):
                    setattr(getattr(entry, field_name), 'data', row[column_name])  # Set data attribute



def prepare_capacites(conn, plan_id):
    capacites_rows = conn.execute(
        'SELECT * FROM PlanCadreCapacites WHERE plan_cadre_id = ?',
        (plan_id,)
    ).fetchall()
    
    capacites_data = []
    for cap_row in capacites_rows:
        cap_id = cap_row['id']
        cap_form = CapaciteItemForm(prefix=f'cap_{cap_id}')
        cap_form.capacite.data = cap_row['capacite']
        cap_form.description_capacite.data = cap_row['description_capacite']
        cap_form.ponderation_min.data = cap_row['ponderation_min']
        cap_form.ponderation_max.data = cap_row['ponderation_max']
        
        # Populate Savoirs Nécessaires
        sav_necessaires = conn.execute(
            'SELECT * FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?',
            (cap_id,)
        ).fetchall()
        for sn in sav_necessaires:
            cap_form.savoirs_necessaires.append_entry(sn['texte'])
        
        # Populate Savoirs Faire
        sav_faire = conn.execute(
            'SELECT * FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?',
            (cap_id,)
        ).fetchall()
        for sf in sav_faire:
            entry_sf = cap_form.savoirs_faire.append_entry()
            entry_sf.texte.data = sf['texte']
            entry_sf.cible.data = sf['cible']
            entry_sf.seuil_reussite.data = sf['seuil_reussite']
        
        # Populate Moyens d'Evaluation
        moyens_eval = conn.execute(
            'SELECT * FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?',
            (cap_id,)
        ).fetchall()
        for me in moyens_eval:
            cap_form.moyens_evaluation.append_entry(me['texte'])
        
        capacites_data.append({
            'capacite_obj': cap_row,
            'form': cap_form
        })
    
    return capacites_data

def prepare_delete_forms(capacites_rows):
    delete_forms_capacites = {
        cap_row['id']: DeleteForm(prefix=f"capacite-{cap_row['id']}")
        for cap_row in capacites_rows
    }
    return delete_forms_capacites

# --- Update Helpers ---

def update_main_plan_cadre(cursor, plan_form, plan_id, cours_id):
    cursor.execute("""
        UPDATE PlanCadre
        SET place_intro = ?,
            objectif_terminal = ?,
            structure_intro = ?,
            structure_activites_theoriques = ?,
            structure_activites_pratiques = ?,
            structure_activites_prevues = ?,
            eval_evaluation_sommative = ?,
            eval_nature_evaluations_sommatives = ?,
            eval_evaluation_de_la_langue = ?,
            eval_evaluation_sommatives_apprentissages = ?
        WHERE id = ? AND cours_id = ?
    """, (
        plan_form.place_intro.data,
        plan_form.objectif_terminal.data,
        plan_form.structure_intro.data,
        plan_form.structure_activites_theoriques.data,
        plan_form.structure_activites_pratiques.data,
        plan_form.structure_activites_prevues.data,
        plan_form.eval_evaluation_sommative.data,
        plan_form.eval_nature_evaluations_sommatives.data,
        plan_form.eval_evaluation_de_la_langue.data,
        plan_form.eval_evaluation_sommatives_apprentissages.data,
        plan_id,
        cours_id
    ))

def update_list_items(cursor, table_name, form_data, plan_id):
    try:
        print(f"\n=== Debug for {table_name} ===")
        print(f"Form data type: {type(form_data)}")
        print(f"Raw form_data: {form_data}")
        print(f"Number of entries: {len(form_data) if form_data else 0}")
        
        # Delete existing entries
        cursor.execute(f"DELETE FROM {table_name} WHERE plan_cadre_id = ?", (plan_id,))
        rows_deleted = cursor.rowcount
        print(f"Deleted {rows_deleted} existing rows")
        
        # Insert new entries
        insert_count = 0
        seen_entries = set()
        
        for entry in form_data:
            # Handle different form field types
            if hasattr(entry, 'texte'):
                # Direct field access
                texte = entry.texte.data if entry.texte.data else None
            elif hasattr(entry, 'form') and hasattr(entry.form, 'texte'):
                # Nested form access
                texte = entry.form.texte.data if entry.form.texte.data else None
            elif hasattr(entry, 'data') and isinstance(entry.data, dict) and 'texte' in entry.data:
                # Dictionary data access
                texte = entry.data['texte']
            else:
                print(f"Skipping entry - unexpected structure: {entry}")
                continue
                
            # Process valid text
            if texte and isinstance(texte, str):
                texte = texte.strip()
                if texte and texte not in seen_entries:
                    seen_entries.add(texte)
                    print(f"Inserting entry: {texte}")
                    
                    if 'description' in [row[1] for row in cursor.execute(f"PRAGMA table_info({table_name});").fetchall()]:
                        # Handle tables with description field
                        description = None
                        if hasattr(entry, 'texte_description'):
                            description = entry.texte_description.data
                        elif hasattr(entry, 'form') and hasattr(entry.form, 'texte_description'):
                            description = entry.form.texte_description.data
                        elif hasattr(entry, 'data') and isinstance(entry.data, dict) and 'texte_description' in entry.data:
                            description = entry.data['texte_description']
                            
                        cursor.execute(
                            f"INSERT INTO {table_name} (plan_cadre_id, texte, description) VALUES (?, ?, ?)",
                            (plan_id, texte, description)
                        )
                    else:
                        # Handle tables without description field
                        cursor.execute(
                            f"INSERT INTO {table_name} (plan_cadre_id, texte) VALUES (?, ?)",
                            (plan_id, texte)
                        )
                    
                    insert_count += 1
                else:
                    print(f"Skipping entry - empty, None, or duplicate: {texte}")
            else:
                print(f"Skipping entry - invalid texte: {texte}")
        
        print(f"Total entries inserted: {insert_count}")
        return True
        
    except Exception as e:
        print(f"Error in update_list_items for {table_name}: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        traceback.print_exc()
        raise

def handle_update_capacity(conn, cursor, cap_form, cap_id, plan_id):
    try:
        # Récupérer les valeurs de pondération depuis le formulaire
        ponderation_min = cap_form.ponderation_min.data
        ponderation_max = cap_form.ponderation_max.data

        # Validation: la pondération minimale ne doit pas dépasser la pondération maximale
        if ponderation_min > ponderation_max:
            raise ValueError("La pondération minimale ne peut pas être supérieure à la pondération maximale.")
        
        # Mettre à jour les champs principaux de la capacité
        cursor.execute("""
            UPDATE PlanCadreCapacites
            SET capacite = ?,
                description_capacite = ?,
                ponderation_min = ?,
                ponderation_max = ?
            WHERE id = ? AND plan_cadre_id = ?
        """, (
            cap_form.capacite.data.strip(),
            cap_form.description_capacite.data.strip(),
            ponderation_min,
            ponderation_max,
            cap_id,
            plan_id
        ))
        
        # Mettre à jour les Savoirs Nécessaires
        cursor.execute("DELETE FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?", (cap_id,))
        for sn in cap_form.savoirs_necessaires.entries:
            sn_txt = sn.data.strip()
            if sn_txt:
                cursor.execute("""
                    INSERT INTO PlanCadreCapaciteSavoirsNecessaires (capacite_id, texte)
                    VALUES (?, ?)
                """, (cap_id, sn_txt))
        
        # Mettre à jour les Savoirs Faire
        cursor.execute("DELETE FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?", (cap_id,))
        for sf in cap_form.savoirs_faire.entries:
            sf_txt = sf.texte.data.strip() if sf.texte.data else None
            sf_cible = sf.cible.data.strip() if sf.cible.data else None
            sf_seuil = sf.seuil_reussite.data.strip() if sf.seuil_reussite.data else None
            if sf_txt:
                cursor.execute("""
                    INSERT INTO PlanCadreCapaciteSavoirsFaire (capacite_id, texte, cible, seuil_reussite)
                    VALUES (?, ?, ?, ?)
                """, (cap_id, sf_txt, sf_cible, sf_seuil))
        
        # Mettre à jour les Moyens d'Evaluation
        cursor.execute("DELETE FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?", (cap_id,))
        for me in cap_form.moyens_evaluation.entries:
            # Accéder directement au champ 'texte' de chaque entrée
            me_txt = me.texte.data.strip() if me.texte.data else None
            if me_txt:
                cursor.execute("""
                    INSERT INTO PlanCadreCapaciteMoyensEvaluation (capacite_id, texte)
                    VALUES (?, ?)
                """, (cap_id, me_txt))
        
        # Valider la transaction
        conn.commit()
        return True

    except Exception as e:
        # Annuler la transaction en cas d'erreur
        conn.rollback()
        print(f"Erreur lors de la mise à jour de la capacité {cap_id}: {e}")
        raise
        
def handle_delete_capacity(cursor, cap_id, plan_id):
    try:
        # Delete capacity and related entries
        cursor.execute("DELETE FROM PlanCadreCapacites WHERE id = ? AND plan_cadre_id = ?", (cap_id, plan_id))
        cursor.execute("DELETE FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?", (cap_id,))
        cursor.execute("DELETE FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?", (cap_id,))
        cursor.execute("DELETE FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?", (cap_id,))
        return True
    except Exception as e:
        print(f"Error deleting capacity {cap_id}: {e}")
        raise

# --- Utility Helpers ---

def initialize_delete_forms(capacites_rows):
    return {
        cap_row['id']: DeleteForm(prefix=f"capacite-{cap_row['id']}")
        for cap_row in capacites_rows
    }
@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>', methods=['GET', 'POST'])
@login_required
def view_plan_cadre(cours_id, plan_id):
    print("DEBUG => request.method:", request.method)
    print("DEBUG => request.form:", request.form.to_dict())

    conn = get_db_connection()

    # Initialisation des formulaires
    import_form = ImportPlanCadreForm()

    try:
        if request.method == 'GET':
            # Récupération des détails du plan-cadre et du cours
            plan_row = get_plan_cadre(conn, plan_id, cours_id)
            cours = get_cours_details(conn, cours_id)
            
            if not plan_row or not cours:
                flash('Plan Cadre ou Cours non trouvé.', 'danger')
                return redirect(url_for('cours.view_cours', cours_id=cours_id))

            # Ajout de la récupération des cours reliés
            cours_relies = conn.execute('''
                SELECT texte, description 
                FROM PlanCadreCoursRelies 
                WHERE plan_cadre_id = ?
            ''', (plan_id,)).fetchall()

            # Récupération des détails des cours préalables et corequis
            prealables_details = get_related_courses(conn, cours_id, 'CoursPrealable', 'cours_prealable_id')
            corequisites_details = get_related_courses(conn, cours_id, 'CoursCorequis', 'cours_corequis_id')
            
            # Récupération des compétences
            competences_developpees_from_cours = get_competences(conn, cours_id, 'developpees')
            competences_atteintes = get_competences(conn, cours_id, 'atteintes')
            elements_competence_par_cours = get_elements_competence(conn, cours_id)

            # Préparation du formulaire principal
            plan_form = prepare_plan_form(plan_row)
            populate_field_lists(conn, plan_id, plan_form)
            generate_form = GenerateContentForm(
                additional_info=plan_row['additional_info'],
                ai_model=plan_row['ai_model']
            )

            # Récupération des données des capacités
            capacites_data = []
            capacites_rows = conn.execute(
                'SELECT * FROM PlanCadreCapacites WHERE plan_cadre_id = ? ORDER BY id',
                (plan_id,)
            ).fetchall()

            for cap_row in capacites_rows:
                cap_id = cap_row['id']
                
                # Récupération des savoirs nécessaires pour chaque capacité
                savoirs_necessaires = conn.execute(
                    'SELECT texte FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?',
                    (cap_id,)
                ).fetchall()
                
                # Récupération des savoirs faire pour chaque capacité
                savoirs_faire = conn.execute(
                    'SELECT texte, cible, seuil_reussite FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?',
                    (cap_id,)
                ).fetchall()
                
                # Récupération des moyens d'évaluation pour chaque capacité
                moyens_evaluation = conn.execute(
                    'SELECT texte FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?',
                    (cap_id,)
                ).fetchall()

                capacites_data.append({
                    'capacite': {
                        'id': cap_id,
                        'capacite': cap_row['capacite'],
                        'description_capacite': cap_row['description_capacite'],
                        'ponderation_min': cap_row['ponderation_min'],
                        'ponderation_max': cap_row['ponderation_max']
                    },
                    'savoirs_necessaires': [{'texte': sn['texte']} for sn in savoirs_necessaires],
                    'savoirs_faire': [{
                        'texte': sf['texte'],
                        'cible': sf['cible'],
                        'seuil_reussite': sf['seuil_reussite']
                    } for sf in savoirs_faire],
                    'moyens_evaluation': [{'texte': me['texte']} for me in moyens_evaluation]
                })

            # Mise à jour du formulaire avec les données des capacités
            for cap_data in capacites_data:
                form_cap = plan_form.capacites.append_entry()
                form_cap.capacite.data = cap_data['capacite']['capacite']
                form_cap.description_capacite.data = cap_data['capacite']['description_capacite']
                form_cap.ponderation_min.data = cap_data['capacite']['ponderation_min']
                form_cap.ponderation_max.data = cap_data['capacite']['ponderation_max']
                
                # Ajout des savoirs nécessaires
                for sn in cap_data['savoirs_necessaires']:
                    form_cap.savoirs_necessaires.append_entry(sn['texte'])
                
                # Ajout des savoirs faire
                for sf in cap_data['savoirs_faire']:
                    sf_entry = form_cap.savoirs_faire.append_entry()
                    sf_entry.texte.data = sf['texte']
                    sf_entry.cible.data = sf['cible']
                    sf_entry.seuil_reussite.data = sf['seuil_reussite']
                
                # Ajout des moyens d'évaluation
                for me in cap_data['moyens_evaluation']:
                    form_cap.moyens_evaluation.append_entry(me['texte'])

            return render_template(
                'view_plan_cadre.html',
                cours=cours,
                plan=plan_row,
                prealables_details=prealables_details,
                corequisites_details=corequisites_details,
                cours_relies=cours_relies,
                plan_form=plan_form,
                capacites_data=capacites_data,  # Pass the capacities data to the template
                generate_form=generate_form,
                import_form=import_form,
                competences_developpees_from_cours=competences_developpees_from_cours,
                competences_atteintes=competences_atteintes,
                elements_competence_par_cours=elements_competence_par_cours
            )

        elif request.method == 'POST':
            print("DEBUG - Form data:", request.form)  # Pour voir les données reçues
            plan_form = prepare_plan_form(request.form)
            if plan_form.validate_on_submit():
                cursor = conn.cursor()
                try:
                    # Démarrer une transaction
                    cursor.execute('BEGIN')

                    # Mise à jour du plan-cadre principal
                    update_main_plan_cadre(cursor, plan_form, plan_id, cours_id)

                    # Mise à jour des listes associées
                    update_list_items(cursor, 'PlanCadreCompetencesDeveloppees', 
                                    plan_form.competences_developpees, plan_id)
                    update_list_items(cursor, 'PlanCadreObjetsCibles', 
                                    plan_form.objets_cibles, plan_id)
                    update_list_items(cursor, 'PlanCadreCompetencesCertifiees', 
                                    plan_form.competences_certifiees, plan_id)
                    update_list_items(cursor, 'PlanCadreCoursCorequis', 
                                    plan_form.cours_corequis, plan_id)
                    update_list_items(cursor, 'PlanCadreCoursPrealables', 
                                    plan_form.cours_prealables, plan_id)
                    update_list_items(cursor, 'PlanCadreCoursRelies',   # Ajout de cette ligne
                                    plan_form.cours_relies, plan_id)     # pour les cours reliés
                    update_list_items(cursor, 'PlanCadreSavoirEtre', 
                                    plan_form.savoir_etre, plan_id)

                    # Mise à jour des capacités
                    cursor.execute('DELETE FROM PlanCadreCapacites WHERE plan_cadre_id = ?', (plan_id,))
                    
                    # Récupérer toutes les clés du formulaire qui concernent les capacités
                    capacite_keys = [key for key in request.form.keys() if key.startswith('capacites-') and key.endswith('-capacite')]
                    capacite_indices = set()
                    for key in capacite_keys:
                        try:
                            index = int(key.split('-')[1])  # Extraire l'index du nom du champ
                            capacite_indices.add(index)
                        except (ValueError, IndexError):
                            continue

                    print("DEBUG - Capacité indices trouvés:", capacite_indices)  # Debug

                    for index in sorted(capacite_indices):
                        prefix = f'capacites-{index}'
                        capacite = request.form.get(f'{prefix}-capacite', '').strip()
                        
                        if capacite:  # Seulement traiter si une capacité est présente
                            description = request.form.get(f'{prefix}-description_capacite', '').strip()
                            ponderation_min = request.form.get(f'{prefix}-ponderation_min', 0)
                            ponderation_max = request.form.get(f'{prefix}-ponderation_max', 100)

                            print(f"DEBUG - Insertion capacité: {capacite}, {description}, {ponderation_min}, {ponderation_max}")  # Debug

                            # Insérer la capacité
                            cursor.execute("""
                                INSERT INTO PlanCadreCapacites 
                                (plan_cadre_id, capacite, description_capacite, ponderation_min, ponderation_max)
                                VALUES (?, ?, ?, ?, ?)
                            """, (plan_id, capacite, description, ponderation_min, ponderation_max))
                            
                            capacite_id = cursor.lastrowid
                            print(f"DEBUG - Nouvelle capacité ID: {capacite_id}")  # Debug

                            # Traiter les savoirs nécessaires
                            savoirs_keys = [k for k in request.form.keys() if k.startswith(f'{prefix}-savoirs_necessaires-')]
                            for sav_key in savoirs_keys:
                                savoir = request.form.get(sav_key, '').strip()
                                if savoir:
                                    cursor.execute("""
                                        INSERT INTO PlanCadreCapaciteSavoirsNecessaires (capacite_id, texte)
                                        VALUES (?, ?)
                                    """, (capacite_id, savoir))

                            # Traiter les savoirs faire
                            savoirs_faire_keys = [k for k in request.form.keys() if k.startswith(f'{prefix}-savoirs_faire-') and k.endswith('-texte')]
                            for sf_key in savoirs_faire_keys:
                                base_key = sf_key[:-6]  # Enlever '-texte'
                                texte = request.form.get(sf_key, '').strip()
                                if texte:
                                    cible = request.form.get(f'{base_key}-cible', '').strip()
                                    seuil = request.form.get(f'{base_key}-seuil_reussite', '').strip()
                                    cursor.execute("""
                                        INSERT INTO PlanCadreCapaciteSavoirsFaire 
                                        (capacite_id, texte, cible, seuil_reussite)
                                        VALUES (?, ?, ?, ?)
                                    """, (capacite_id, texte, cible, seuil))

                            # Traiter les moyens d'évaluation
                            moyens_keys = [k for k in request.form.keys() if k.startswith(f'{prefix}-moyens_evaluation-')]
                            for moyen_key in moyens_keys:
                                moyen = request.form.get(moyen_key, '').strip()
                                if moyen:
                                    cursor.execute("""
                                        INSERT INTO PlanCadreCapaciteMoyensEvaluation (capacite_id, texte)
                                        VALUES (?, ?)
                                    """, (capacite_id, moyen))

                    conn.commit()
                    success_message = "Plan-cadre et capacités mis à jour avec succès."

                    # Détection de la nature de la requête
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        # Requête AJAX
                        return jsonify({'success': True, 'message': success_message}), 200
                    else:
                        # Requête traditionnelle
                        flash(success_message, "success")

                except Exception as e:
                    conn.rollback()
                    error_message = f"Erreur lors de la mise à jour : {str(e)}"
                    print(f"Error updating plan-cadre: {e}")  # Debug
                    traceback.print_exc()  # Pour avoir le traceback complet

                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        # Requête AJAX
                        return jsonify({'success': False, 'message': error_message}), 500
                    else:
                        # Requête traditionnelle
                        flash(error_message, "danger")
            else:
                error_message = "Formulaire invalide. Veuillez vérifier vos entrées."
                print(f"DEBUG - Form validation failed: {plan_form.errors}")  # Debug

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    # Requête AJAX
                    return jsonify({'success': False, 'message': error_message, 'errors': plan_form.errors}), 400
                else:
                    # Requête traditionnelle
                    flash(error_message, "danger")

            # Redirection après POST pour les requêtes traditionnelles
            if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
                return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))

    finally:
        conn.close()





@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>/update_intro', methods=['POST'])
@login_required
def update_intro(cours_id, plan_id):
    try:
        # Validate CSRF token
        csrf_token = request.headers.get('X-CSRFToken')
        validate_csrf(csrf_token)

        data = request.get_json()
        new_intro = data.get('place_intro', '').strip()

        if not new_intro:
            return jsonify({'success': False, 'message': 'Le texte de l\'introduction ne peut pas être vide.'}), 400

        conn = get_db_connection()
        # Update the place_intro field
        conn.execute('UPDATE PlanCadre SET place_intro = ? WHERE id = ? AND cours_id = ?', (new_intro, plan_id, cours_id))
        conn.commit()
        conn.close()

        return jsonify({'success': True}), 200
    except CSRFError:
        return jsonify({'success': False, 'message': 'CSRF token invalide.'}), 400
    except Exception as e:
        # Log the error as needed
        return jsonify({'success': False, 'message': 'Une erreur est survenue.'}), 500

@cours_bp.route('/<int:cours_id>/plan_cadre', methods=['GET'])
@login_required
def view_or_add_plan_cadre(cours_id):
    conn = get_db_connection()
    try:
        # Vérifier si un plan-cadre existe
        plan_cadre = conn.execute("SELECT id FROM PlanCadre WHERE cours_id = ?", (cours_id,)).fetchone()
        if plan_cadre:
            # Rediriger vers la page du plan-cadre existant
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_cadre['id']))
        else:
            # Créer un plan-cadre vide
            cursor = conn.execute("""
                INSERT INTO PlanCadre 
                (cours_id, place_intro, objectif_terminal, structure_intro, structure_activites_theoriques, 
                structure_activites_pratiques, structure_activites_prevues, eval_evaluation_sommative, 
                eval_nature_evaluations_sommatives, eval_evaluation_de_la_langue, eval_evaluation_sommatives_apprentissages)
                VALUES (?, '', '', '', '', '', '', '', '', '', '')
            """, (cours_id,))
            conn.commit()
            new_plan_cadre_id = cursor.lastrowid
            flash('Plan-Cadre créé avec succès.', 'success')
            # Rediriger vers le nouveau plan-cadre
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=new_plan_cadre_id))
    except sqlite3.Error as e:
        flash(f'Erreur : {e}', 'danger')
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    finally:
        conn.close()

@cours_bp.route('/<int:cours_id>')
@login_required
def view_cours(cours_id):
    conn = get_db_connection()
    
    # Récupérer les détails du cours avec le nom du programme
    cours = conn.execute('''
        SELECT Cours.*, Programme.nom as programme_nom 
        FROM Cours 
        JOIN Programme ON Cours.programme_id = Programme.id 
        WHERE Cours.id = ?
    ''', (cours_id,)).fetchone()
    
    if not cours:
        flash('Cours non trouvé.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))
    
    # Récupérer les compétences développées
    competences_developpees = conn.execute('''
        SELECT Competence.nom 
        FROM CompetenceParCours
        JOIN Competence ON CompetenceParCours.competence_developpee_id = Competence.id
        WHERE CompetenceParCours.cours_id = ? AND CompetenceParCours.competence_developpee_id IS NOT NULL
    ''', (cours_id,)).fetchall()
    
    # Récupérer les compétences atteintes
    competences_atteintes = conn.execute('''
        SELECT Competence.nom 
        FROM CompetenceParCours
        JOIN Competence ON CompetenceParCours.competence_atteinte_id = Competence.id
        WHERE CompetenceParCours.cours_id = ? AND CompetenceParCours.competence_atteinte_id IS NOT NULL
    ''', (cours_id,)).fetchall()
    
    elements_competence_par_cours = conn.execute('''
        SELECT 
            c.id AS competence_id,
            ec.nom AS element_competence_nom, 
            c.code AS competence_code,
            c.nom AS competence_nom,
            ecp.status
        FROM ElementCompetenceParCours ecp
        JOIN ElementCompetence ec ON ecp.element_competence_id = ec.id
        JOIN Competence c ON ec.competence_id = c.id
        WHERE ecp.cours_id = ?
    ''', (cours_id,)).fetchall()

    elements_competence_grouped = {}
    for ec in elements_competence_par_cours:
        competence_id = ec['competence_id']
        competence_nom = ec['competence_nom']
        if competence_id not in elements_competence_grouped:
            elements_competence_grouped[competence_id] = {
                'nom': competence_nom,
                'code': ec['competence_code'],
                'elements': []
            }
        elements_competence_grouped[competence_id]['elements'].append({
            'element_competence_nom': ec['element_competence_nom'],
            'status': ec['status']
        })

    # Récupérer les cours préalables
    prealables = conn.execute('SELECT cours_prealable_id FROM CoursPrealable WHERE cours_id = ?', (cours_id,)).fetchall()
    prealables_ids = [p['cours_prealable_id'] for p in prealables]
    
    prealables_details = []
    if prealables_ids:
        placeholders = ','.join(['?'] * len(prealables_ids))
        prealables_details = conn.execute(f'''
            SELECT id, nom, code 
            FROM Cours 
            WHERE id IN ({placeholders})
        ''', prealables_ids).fetchall()
    
    # Récupérer les cours corequis
    corequisites = conn.execute('SELECT cours_corequis_id FROM CoursCorequis WHERE cours_id = ?', (cours_id,)).fetchall()
    corequisites_ids = [c['cours_corequis_id'] for c in corequisites]
    
    corequisites_details = []
    if corequisites_ids:
        placeholders = ','.join(['?'] * len(corequisites_ids))
        corequisites_details = conn.execute(f'''
            SELECT id, nom, code 
            FROM Cours 
            WHERE id IN ({placeholders})
        ''', corequisites_ids).fetchall()

    plans_cadres = conn.execute('SELECT * FROM PlanCadre WHERE cours_id = ?', (cours_id,)).fetchall()
    
    delete_forms_plans = {plan['id']: DeleteForm(prefix=f"plan_cadre-{plan['id']}") for plan in plans_cadres}
    
    conn.close()
    
    # Instancier le formulaire de suppression pour ce cours
    delete_form = DeleteForm(prefix=f"cours-{cours['id']}")
    
    return render_template('view_cours.html', 
                           cours=cours, 
                           plans_cadres=plans_cadres,
                           competences_developpees=competences_developpees, 
                           competences_atteintes=competences_atteintes,
                           elements_competence_par_cours=elements_competence_grouped,
                           prealables_details=prealables_details,
                           corequisites_details=corequisites_details,
                           delete_form=delete_form,
                           delete_forms_plans=delete_forms_plans)



@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>/capacite/<int:capacite_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
def edit_capacite(cours_id, plan_id, capacite_id):
    form = CapaciteItemForm()
    conn = get_db_connection()

    # Récupérer la capacité
    capacite = conn.execute('SELECT * FROM PlanCadreCapacites WHERE id = ?', (capacite_id,)).fetchone()
    if not capacite or capacite['plan_cadre_id'] != plan_id:
        flash('Capacité non trouvée pour ce Plan Cadre.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))

    # Récupérer le plan (pour validation et redirection)
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ?', (plan_id,)).fetchone()
    if not plan:
        flash('Plan Cadre non trouvé.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))

    # Récupérer les savoirs nécessaires
    savoirs_necessaires = conn.execute('SELECT * FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?', (capacite_id,)).fetchall()

    # Récupérer les savoirs faire
    savoirs_faire = conn.execute('SELECT * FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?', (capacite_id,)).fetchall()

    # Récupérer les moyens d'évaluation
    moyens_evaluation = conn.execute('SELECT * FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?', (capacite_id,)).fetchall()

    conn.close()

    if request.method == 'GET':
        # Pré-remplir le formulaire
        form.capacite.data = capacite['capacite']
        form.description_capacite.data = capacite['description_capacite']
        form.ponderation_min.data = capacite['ponderation_min']
        form.ponderation_max.data = capacite['ponderation_max']

        # Vider les entrées existantes
        form.savoirs_necessaires.entries = []
        form.savoirs_faire.entries = []
        form.moyens_evaluation.entries = []

        # Ajouter les savoirs nécessaires existants
        for sav in savoirs_necessaires:
            entry_form = form.savoirs_necessaires.append_entry()
            entry_form.data = sav['texte']

        # Ajouter les savoirs faire existants
        for sf in savoirs_faire:
            entry_form = form.savoirs_faire.append_entry()
            entry_form.texte.data = sf['texte']
            entry_form.cible.data = sf['cible'] if sf['cible'] else ''
            entry_form.seuil_reussite.data = sf['seuil_reussite'] if sf['seuil_reussite'] else ''

        # Ajouter les moyens d'évaluation existants
        for me in moyens_evaluation:
            entry_form = form.moyens_evaluation.append_entry()
            entry_form.texte.data = me['texte']

    if form.validate_on_submit():
        capacite_text = form.capacite.data
        description = form.description_capacite.data
        ponderation_min = form.ponderation_min.data
        ponderation_max = form.ponderation_max.data

        if ponderation_min > ponderation_max:
            flash('La pondération minimale ne peut pas être supérieure à la pondération maximale.', 'danger')
            return redirect(url_for('cours_bp.edit_capacite', cours_id=cours_id, plan_id=plan_id, capacite_id=capacite_id))

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Mise à jour de la capacité
            cursor.execute("""
                UPDATE PlanCadreCapacites
                SET capacite = ?, description_capacite = ?, ponderation_min = ?, ponderation_max = ?
                WHERE id = ?
            """, (capacite_text, description, ponderation_min, ponderation_max, capacite_id))

            # Supprimer les anciens savoirs nécessaires, savoirs faire, et moyens d'évaluation
            cursor.execute('DELETE FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?', (capacite_id,))
            cursor.execute('DELETE FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?', (capacite_id,))
            cursor.execute('DELETE FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?', (capacite_id,))

            # Réinsérer les savoirs nécessaires
            for sav in form.savoirs_necessaires.data:
                if sav.strip():
                    cursor.execute("""
                        INSERT INTO PlanCadreCapaciteSavoirsNecessaires (capacite_id, texte)
                        VALUES (?, ?)
                    """, (capacite_id, sav.strip()))


            # Réinsérer les savoirs faire
            for sf_form in form.savoirs_faire.entries:
                if sf_form.texte.data.strip():
                    cursor.execute("""
                        INSERT INTO PlanCadreCapaciteSavoirsFaire (capacite_id, texte, cible, seuil_reussite)
                        VALUES (?, ?, ?, ?)
                    """, (capacite_id, sf_form.texte.data.strip(), 
                          sf_form.cible.data.strip() if sf_form.cible.data else None, 
                          sf_form.seuil_reussite.data.strip() if sf_form.seuil_reussite.data else None))

            # Réinsérer les moyens d'évaluation
            for me_form in form.moyens_evaluation.entries:
                if me_form.texte.data.strip():
                    cursor.execute("""
                        INSERT INTO PlanCadreCapaciteMoyensEvaluation (capacite_id, texte)
                        VALUES (?, ?)
                    """, (capacite_id, me_form.texte.data.strip()))

            conn.commit()
            flash('Capacité mise à jour avec succès!', 'success')
            conn.close()
            return redirect(url_for('cours.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        except sqlite3.Error as e:
            conn.rollback()
            flash(f'Erreur lors de la mise à jour de la capacité : {e}', 'danger')
            conn.close()
            return redirect(url_for('cours_bp.edit_capacite', cours_id=cours_id, plan_id=plan_id, capacite_id=capacite_id))

    return render_template('edit_capacite.html', form=form, plan_id=plan_id, capacite_id=capacite_id, cours_id=cours_id)



# Nouvelle Route pour Supprimer un Cours
@cours_bp.route('/<int:cours_id>/delete', methods=['POST'])
@role_required('admin')
def delete_cours(cours_id):
    form = DeleteForm(prefix=f"cours-{cours_id}")
    
    if form.validate_on_submit():
        conn = get_db_connection()
        # Récupérer le programme_id avant de supprimer le cours
        cours = conn.execute('SELECT programme_id FROM Cours WHERE id = ?', (cours_id,)).fetchone()
        if cours is None:
            conn.close()
            flash('Cours non trouvé.')
            return redirect(url_for('main.index'))
        programme_id = cours['programme_id']
        try:
            conn.execute('DELETE FROM Cours WHERE id = ?', (cours_id,))
            conn.commit()
            flash('Cours supprimé avec succès!')
        except sqlite3.Error as e:
            flash(f'Erreur lors de la suppression du cours : {e}')
        finally:
            conn.close()
        return redirect(url_for('main.view_programme', programme_id=programme_id))
    else:
        flash('Erreur lors de la soumission du formulaire de suppression.')
        return redirect(url_for('main.index'))
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
    CapaciteForm,
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


cours_bp = Blueprint('cours', __name__, url_prefix='/cours')


@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>/import_json', methods=['POST'])
@login_required
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



    
@cours_bp.route('/<int:cours_id>/plan_cadre/<int:plan_id>', methods=['GET', 'POST'])
@login_required
def view_plan_cadre(cours_id, plan_id):

    conn = get_db_connection()
    # On récupère d'abord le Plan Cadre en s'assurant qu'il correspond au cours_id
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ? AND cours_id = ?', (plan_id, cours_id)).fetchone()
    cours = conn.execute('SELECT * FROM Cours WHERE id = ?', (cours_id,)).fetchone()
    
    if not plan:
        flash('Plan Cadre non trouvé pour ce cours.', 'danger')
        conn.close()
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    
    # Récupérer les sections
    competences_developpees = conn.execute('SELECT * FROM PlanCadreCompetencesDeveloppees WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    objets_cibles = conn.execute('SELECT * FROM PlanCadreObjetsCibles WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    cours_relies = conn.execute('SELECT * FROM PlanCadreCoursRelies WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    cours_prealables = conn.execute('SELECT * FROM PlanCadreCoursPrealables WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    competences_certifiees = conn.execute('SELECT texte, description FROM PlanCadreCompetencesCertifiees WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    cours_corequis = conn.execute('SELECT texte, description FROM PlanCadreCoursCorequis WHERE plan_cadre_id = ?', (plan_id,)).fetchall()

    # Récupérer les capacités
    capacites = conn.execute('SELECT * FROM PlanCadreCapacites WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    capacites_detail = []
    for cap in capacites:

        cap_id = cap['id']
        print("cap id:", cap_id)
        sav_necessaires = conn.execute('SELECT * FROM PlanCadreCapaciteSavoirsNecessaires WHERE capacite_id = ?', (cap_id,)).fetchall()
        sav_faire = conn.execute('SELECT * FROM PlanCadreCapaciteSavoirsFaire WHERE capacite_id = ?', (cap_id,)).fetchall()
        moyens_eval = conn.execute('SELECT * FROM PlanCadreCapaciteMoyensEvaluation WHERE capacite_id = ?', (cap_id,)).fetchall()
        
        capacites_detail.append({
            'capacite': cap,  # cap est un Row contenant les infos de la capacité
            'savoirs_necessaires': sav_necessaires,
            'savoirs_faire': sav_faire,
            'moyens_evaluation': moyens_eval
        })
    
    # Récupérer le savoir-être
    savoir_etre = conn.execute('SELECT * FROM PlanCadreSavoirEtre WHERE plan_cadre_id = ?', (plan_id,)).fetchall()
    
    # Instancier les formulaires de suppression pour chaque capacité
    delete_forms_capacites = {cap['id']: DeleteForm(prefix=f"capacite-{cap['id']}") for cap in capacites}
    
    # Instancier le formulaire d'importation JSON
    import_form = ImportPlanCadreForm()
    
    conn.close()
    
    return render_template(
        'view_plan_cadre.html',
        plan=plan,
        cours=cours,
        competences_developpees=competences_developpees,
        competences_certifiees=competences_certifiees,
        cours_corequis=cours_corequis,
        objets_cibles=objets_cibles,
        cours_relies=cours_relies,
        cours_prealables=cours_prealables,
        capacites=capacites_detail,
        savoir_etre=savoir_etre,
        delete_forms_capacites=delete_forms_capacites,
        cours_id=cours_id,
        plan_id=plan_id,
        import_form=import_form  # Passer le formulaire au template
    )

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
@login_required
def edit_capacite(cours_id, plan_id, capacite_id):
    form = CapaciteForm()
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
@login_required
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
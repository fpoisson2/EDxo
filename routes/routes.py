# app.py
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


main = Blueprint('main', __name__)

logger = logging.getLogger(__name__)

# Define the markdown filter
@main.app_template_filter('markdown')
def markdown_filter(text):
    return markdown.markdown(text)


@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM User WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            login_user(User(user['id'], user['username'], user['password'], user['role']))
            flash('Connexion réussie !', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.index'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect.', 'danger')

    return render_template('login.html')


# Route pour la déconnexion
@main.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnexion réussie.', 'success')
    return redirect(url_for('main.login'))

@main.route('/cours/<int:cours_id>/plan_cadre/<int:plan_id>/import_json', methods=['POST'])
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
                    return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))

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
                return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))

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
            return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))

        except json.JSONDecodeError:
            flash('Le fichier importé n\'est pas un fichier JSON valide.', 'danger')
            return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        except ValueError as ve:
            flash(f'Erreur de validation des données : {ve}', 'danger')
            conn.rollback()
            conn.close()
            return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        except sqlite3.Error as e:
            flash(f'Erreur de base de données lors de l\'importation : {e}', 'danger')
            conn.rollback()
            conn.close()
            return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
    else:
        # Gérer les erreurs de validation de formulaire
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'Erreur dans le champ "{getattr(form, field).label.text}": {error}', 'danger')
        return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))


@main.route('/cours/<int:cours_id>/plan_cadre/<int:plan_id>/export_json', methods=['GET'])
@login_required
def export_plan_cadre_json(cours_id, plan_id):
    conn = get_db_connection()
    
    # Vérifier que le plan-cadre appartient au cours spécifié
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ? AND cours_id = ?', (plan_id, cours_id)).fetchone()
    if not plan:
        flash('Plan Cadre non trouvé pour ce cours.', 'danger')
        conn.close()
        return redirect(url_for('main.view_cours', cours_id=cours_id))
    
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


@main.route('/')
@login_required
def index():
    conn = get_db_connection()
    programmes = conn.execute('SELECT * FROM Programme').fetchall()
    conn.close()
    return render_template('index.html', programmes=programmes)

# --------------------- Programme Routes ---------------------

# Route pour ajouter un Plan Cadre à un cours
@main.route('/cours/<int:cours_id>/plan_cadre/add', methods=['GET', 'POST'])
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
        return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_cadre_id))
    except sqlite3.IntegrityError:
        flash('Un Plan Cadre existe déjà pour ce cours.', 'danger')
        return redirect(url_for('main.view_cours', cours_id=cours_id))
    except sqlite3.Error as e:
        flash(f'Erreur lors de l\'ajout du Plan Cadre : {e}', 'danger')
    finally:
        conn.close()



    
@main.route('/cours/<int:cours_id>/plan_cadre/<int:plan_id>', methods=['GET', 'POST'])
@login_required
def view_plan_cadre(cours_id, plan_id):

    conn = get_db_connection()
    # On récupère d'abord le Plan Cadre en s'assurant qu'il correspond au cours_id
    plan = conn.execute('SELECT * FROM PlanCadre WHERE id = ? AND cours_id = ?', (plan_id, cours_id)).fetchone()
    cours = conn.execute('SELECT * FROM Cours WHERE id = ?', (cours_id,)).fetchone()
    
    if not plan:
        flash('Plan Cadre non trouvé pour ce cours.', 'danger')
        conn.close()
        return redirect(url_for('main.view_cours', cours_id=cours_id))
    
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

@main.route('/add_programme', methods=('GET', 'POST'))
@login_required
def add_programme():
    form = ProgrammeForm()
    if form.validate_on_submit():
        nom = form.nom.data
        conn = get_db_connection()
        conn.execute('INSERT INTO Programme (nom) VALUES (?)', (nom,))
        conn.commit()
        conn.close()
        flash('Programme ajouté avec succès!')
        return redirect(url_for('main.index'))
    return render_template('add_programme.html', form=form)

@main.route('/cours/<int:cours_id>/plan_cadre', methods=['GET'])
@login_required
def view_or_add_plan_cadre(cours_id):
    conn = get_db_connection()
    try:
        # Vérifier si un plan-cadre existe
        plan_cadre = conn.execute("SELECT id FROM PlanCadre WHERE cours_id = ?", (cours_id,)).fetchone()
        if plan_cadre:
            # Rediriger vers la page du plan-cadre existant
            return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_cadre['id']))
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
            return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=new_plan_cadre_id))
    except sqlite3.Error as e:
        flash(f'Erreur : {e}', 'danger')
        return redirect(url_for('main.view_cours', cours_id=cours_id))
    finally:
        conn.close()


@main.route('/programme/<int:programme_id>')
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
    
    conn.close()
    
    return render_template('view_programme.html', 
                           programme=programme, 
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



# --------------------- Competence Routes ---------------------
@main.route('/add_competence', methods=['GET', 'POST'])
@login_required
def add_competence():
    form = CompetenceForm()
    conn = get_db_connection()
    programmes = conn.execute('SELECT id, nom FROM Programme').fetchall()
    conn.close()
    form.programme.choices = [(p['id'], p['nom']) for p in programmes]

    if form.validate_on_submit():
        programme_id = form.programme.data
        code = form.code.data
        nom = form.nom.data
        criteria_de_performance = form.criteria_de_performance.data or ""
        contexte_de_realisation = form.contexte_de_realisation.data or ""

        # Nettoyer le contenu avant de l'enregistrer
        allowed_tags = [
            'ul', 'ol', 'li', 'strong', 'em', 'p', 'br', 'a', 
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
        ]
        allowed_attributes = {'a': ['href', 'title', 'target']}

        criteria_clean = bleach.clean(
            criteria_de_performance,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True
        )
        context_clean = bleach.clean(
            contexte_de_realisation,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True
        )

        try:
            conn = get_db_connection()
            conn.execute('''
                INSERT INTO Competence (programme_id, code, nom, criteria_de_performance, contexte_de_realisation)
                VALUES (?, ?, ?, ?, ?)
            ''', (programme_id, code, nom, criteria_clean, context_clean))
            conn.commit()
            conn.close()
            flash('Compétence ajoutée avec succès!', 'success')
            return redirect(url_for('main.view_programme', programme_id=programme_id))
        except sqlite3.Error as e:
            flash(f'Erreur lors de l\'ajout de la compétence : {e}', 'danger')
            return redirect(url_for('main.add_competence'))

    return render_template('add_competence.html', form=form)
@main.route('/competence/<int:competence_id>/edit', methods=['GET', 'POST'])
@login_required
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
            return redirect(url_for('main.view_programme', programme_id=programme_id))
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

@main.route('/competence/<int:competence_id>/delete', methods=['POST'])
@login_required
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
        return redirect(url_for('main.view_programme', programme_id=programme_id))
    else:
        flash('Formulaire de suppression invalide.', 'danger')
        return redirect(url_for('main.index'))



# --------------------- ElementCompetence Routes ---------------------

@main.route('/add_element_competence', methods=('GET', 'POST'))
@login_required
def add_element_competence():
    form = ElementCompetenceForm()
    conn = get_db_connection()
    competences = conn.execute('SELECT id, nom FROM Competence').fetchall()
    conn.close()
    form.competence.choices = [(c['id'], c['nom']) for c in competences]

    if form.validate_on_submit():
        competence_id = form.competence.data
        nom = form.nom.data
        criteres = form.criteres_de_performance.data  # Liste des critères

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            # Insérer l'Élément de Compétence
            cursor.execute('INSERT INTO ElementCompetence (competence_id, nom) VALUES (?, ?)', (competence_id, nom))
            element_competence_id = cursor.lastrowid

            # Insérer chaque critère de performance
            for crit in criteres:
                cursor.execute('INSERT INTO ElementCompetenceCriteria (element_competence_id, criteria) VALUES (?, ?)', (element_competence_id, crit))

            conn.commit()
            flash('Élément de compétence et critères de performance ajoutés avec succès!', 'success')
            return redirect(url_for('main.view_programme', programme_id=get_programme_id(conn, competence_id)))
        except sqlite3.Error as e:
            conn.rollback()
            flash(f'Erreur lors de l\'ajout de l\'élément de compétence : {e}', 'danger')
        finally:
            conn.close()
    return render_template('add_element_competence.html', form=form)


@main.route('/add_fil_conducteur', methods=('GET', 'POST'))
@login_required
def add_fil_conducteur():
    form = FilConducteurForm()
    conn = get_db_connection()
    programmes = conn.execute('SELECT id, nom FROM Programme').fetchall()
    conn.close()
    form.programme.choices = [(p['id'], p['nom']) for p in programmes]

    if form.validate_on_submit():
        programme_id = form.programme.data
        description = form.description.data
        couleur = form.couleur.data or '#FFFFFF'  # Utiliser blanc par défaut si aucune couleur spécifiée

        conn = get_db_connection()
        conn.execute('INSERT INTO FilConducteur (programme_id, description, couleur) VALUES (?, ?, ?)', (programme_id, description, couleur))
        conn.commit()
        conn.close()
        flash('Fil conducteur ajouté avec succès!')
        return redirect(url_for('main.view_programme', programme_id=programme_id))

    return render_template('add_fil_conducteur.html', form=form)



@main.route('/add_cours', methods=('GET', 'POST'))
@login_required
def add_cours():
    form = CoursForm()
    conn = get_db_connection()
    
    # Récupérer les programmes et éléments de compétence pour les choix des champs
    programmes = conn.execute('SELECT id, nom FROM Programme').fetchall()
    elements_competence_rows = conn.execute('SELECT id, nom FROM ElementCompetence').fetchall()
    elements_competence = [dict(row) for row in elements_competence_rows]
    conn.close()
    
    form.programme.choices = [(p['id'], p['nom']) for p in programmes]
    
    # Récupérer les éléments de compétence et les passer au formulaire
    for subform in form.elements_competence:
        subform.element_competence.choices = [(e['id'], e['nom']) for e in elements_competence]
    
    if form.validate_on_submit():
        programme_id = form.programme.data
        code = form.code.data
        nom = form.nom.data
        session = form.session.data
        heures_theorie = form.heures_theorie.data
        heures_laboratoire = form.heures_laboratoire.data
        heures_travail_maison = form.heures_travail_maison.data
        nombre_unites = (heures_theorie + heures_laboratoire + heures_travail_maison)/3
        
        elements_competence_data = form.elements_competence.data or []
    
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Insérer le cours dans la table Cours
            cursor.execute('''
                INSERT INTO Cours 
                (programme_id, code, nom, nombre_unites, session, heures_theorie, heures_laboratoire, heures_travail_maison)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (programme_id, code, nom, nombre_unites, session, heures_theorie, heures_laboratoire, heures_travail_maison))
            conn.commit()
            cours_id = cursor.lastrowid  # Récupérer l'ID du cours nouvellement créé
    
            # Insérer les relations ElementCompetenceParCours avec statut
            for ec in elements_competence_data:
                element_id = ec.get('element_competence')
                status = ec.get('status')
                if element_id and status:
                    cursor.execute('''
                        INSERT INTO ElementCompetenceParCours (cours_id, element_competence_id, status)
                        VALUES (?, ?, ?)
                    ''', (cours_id, element_id, status))
                else:
                    flash('Chaque élément de compétence doit avoir un élément sélectionné et un statut.', 'warning')
            
            conn.commit()
            conn.close()
            flash('Cours ajouté avec succès!', 'success')
            return redirect(url_for('main.view_programme', programme_id=programme_id))
        except sqlite3.IntegrityError as e:
            flash(f'Erreur d\'intégrité de la base de données : {e}', 'danger')
            return redirect(url_for('main.add_cours'))
        except sqlite3.Error as e:
            flash(f'Erreur lors de l\'ajout du cours : {e}', 'danger')
            return redirect(url_for('main.add_cours'))
    
    # Afficher les erreurs du formulaire si validation échoue
    elif request.method == 'POST':
        if form.errors:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'Erreur dans le champ "{getattr(form, field).label.text}": {error}', 'danger')
    
    return render_template('add_cours.html', form=form, elements_competence=elements_competence)

@main.route('/cours/<int:cours_id>')
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


# --------------------- CoursPrealable Routes ---------------------

@main.route('/add_cours_prealable', methods=('GET', 'POST'))
@login_required
def add_cours_prealable():
    form = CoursPrealableForm()
    conn = get_db_connection()
    cours = conn.execute('SELECT id, nom FROM Cours').fetchall()
    conn.close()
    form.cours.choices = [(c['id'], c['nom']) for c in cours]
    form.cours_prealable.choices = [(c['id'], c['nom']) for c in cours]

    if form.validate_on_submit():
        cours_id = form.cours.data
        cours_prealable_id = form.cours_prealable.data
        note_necessaire = form.note_necessaire.data
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO CoursPrealable (cours_id, cours_prealable_id, note_necessaire)
            VALUES (?, ?, ?)
        ''', (cours_id, cours_prealable_id, note_necessaire))
        conn.commit()
        conn.close()
        flash('Cours préalable ajouté avec succès!')
        return redirect(url_for('main.view_cours', cours_id=cours_id))
    return render_template('add_cours_prealable.html', form=form)

# --------------------- CoursCorequis Routes ---------------------

@main.route('/add_cours_corequis', methods=('GET', 'POST'))
@login_required
def add_cours_corequis():
    form = CoursCorequisForm()
    conn = get_db_connection()
    cours = conn.execute('SELECT id, nom FROM Cours').fetchall()
    conn.close()
    form.cours.choices = [(c['id'], c['nom']) for c in cours]
    form.cours_corequis.choices = [(c['id'], c['nom']) for c in cours]

    if form.validate_on_submit():
        cours_id = form.cours.data
        cours_corequis_id = form.cours_corequis.data
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO CoursCorequis (cours_id, cours_corequis_id)
            VALUES (?, ?)
        ''', (cours_id, cours_corequis_id))
        conn.commit()
        conn.close()
        flash('Cours corequis ajouté avec succès!')
        return redirect(url_for('main.view_cours', cours_id=cours_id))
    return render_template('add_cours_corequis.html', form=form)

# --------------------- CompetenceParCours Routes ---------------------

@main.route('/add_competence_par_cours', methods=('GET', 'POST'))
@login_required
def add_competence_par_cours():
    form = CompetenceParCoursForm()
    conn = get_db_connection()
    cours = conn.execute('SELECT id, nom FROM Cours').fetchall()
    competences = conn.execute('SELECT id, nom FROM Competence').fetchall()
    conn.close()
    form.cours.choices = [(c['id'], c['nom']) for c in cours]
    form.competence_developpee.choices = [(c['id'], c['nom']) for c in competences]
    form.competence_atteinte.choices = [(c['id'], c['nom']) for c in competences]

    if form.validate_on_submit():
        cours_id = form.cours.data
        competence_developpee_id = form.competence_developpee.data
        competence_atteinte_id = form.competence_atteinte.data
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO CompetenceParCours (cours_id, competence_developpee_id, competence_atteinte_id)
            VALUES (?, ?, ?)
        ''', (cours_id, competence_developpee_id, competence_atteinte_id))
        conn.commit()
        conn.close()
        flash('Relation Compétence par Cours ajoutée avec succès!')
        return redirect(url_for('main.view_cours', cours_id=cours_id))
    return render_template('add_competence_par_cours.html', form=form)

# --------------------- ElementCompetenceParCours Routes ---------------------

@main.route('/add_element_competence_par_cours', methods=('GET', 'POST'))
@login_required
def add_element_competence_par_cours():
    form = ElementCompetenceParCoursForm()
    conn = get_db_connection()
    cours = conn.execute('SELECT id, nom FROM Cours').fetchall()
    elements = conn.execute('SELECT id, nom FROM ElementCompetence').fetchall()
    conn.close()
    form.cours.choices = [(c['id'], c['nom']) for c in cours]
    form.element_developpe.choices = [(e['id'], e['nom']) for e in elements]
    form.element_reinvesti.choices = [(e['id'], e['nom']) for e in elements]
    form.element_atteint.choices = [(e['id'], e['nom']) for e in elements]

    if form.validate_on_submit():
        cours_id = form.cours.data
        element_developpe_id = form.element_developpe.data
        element_reinvesti_id = form.element_reinvesti.data
        element_atteint_id = form.element_atteint.data
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO ElementCompetenceParCours 
            (cours_id, element_developpe_id, element_reinvesti_id, element_atteint_id)
            VALUES (?, ?, ?, ?)
        ''', (cours_id, element_developpe_id, element_reinvesti_id, element_atteint_id))
        conn.commit()
        conn.close()
        flash('Relation Élément de Compétence par Cours ajoutée avec succès!')
        return redirect(url_for('main.view_cours', cours_id=cours_id))
    return render_template('add_element_competence_par_cours.html', form=form)

@main.route('/edit_cours/<int:cours_id>', methods=('GET', 'POST'))
@login_required
def edit_cours(cours_id):
    conn = get_db_connection()
    cours = conn.execute('SELECT * FROM Cours WHERE id = ?', (cours_id,)).fetchone()
    if cours is None:
        conn.close()
        flash('Cours non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    # Récupérer tous les cours pour préalables et corequis
    all_cours = conn.execute('SELECT id, nom FROM Cours WHERE id != ?', (cours_id,)).fetchall()
    cours_choices = [(c['id'], c['nom']) for c in all_cours]

    # Récupérer les préalables existants
    prealables_rows = conn.execute('SELECT cours_prealable_id, note_necessaire FROM CoursPrealable WHERE cours_id = ?', (cours_id,)).fetchall()
    prealables_existants = [{'id': p['cours_prealable_id'], 'note': p['note_necessaire']} for p in prealables_rows]

    # Récupérer les corequis existants
    corequis_rows = conn.execute('SELECT cours_corequis_id FROM CoursCorequis WHERE cours_id = ?', (cours_id,)).fetchall()
    corequis_existants = [c['cours_corequis_id'] for c in corequis_rows]

    # Récupérer les éléments de compétence
    elements_competence_rows = conn.execute('SELECT id, nom FROM ElementCompetence').fetchall()
    elements_competence = [dict(row) for row in elements_competence_rows]

    ec_assoc_rows = conn.execute('SELECT element_competence_id, status FROM ElementCompetenceParCours WHERE cours_id = ?', (cours_id,)).fetchall()
    ec_assoc = [dict(row) for row in ec_assoc_rows]

    programmes_rows = conn.execute('SELECT id, nom FROM Programme').fetchall()
    programmes = [dict(row) for row in programmes_rows]

    # Récupérer les fils conducteurs
    fils_conducteurs_rows = conn.execute('SELECT id, description FROM FilConducteur').fetchall()
    fils_conducteurs = [(fc['id'], fc['description']) for fc in fils_conducteurs_rows]

    conn.close()

    form = CoursForm()
    form.programme.choices = [(p['id'], p['nom']) for p in programmes]
    ec_choices = [(e['id'], e['nom']) for e in elements_competence]

    # Définir les choix pour corequis et fils conducteurs
    form.corequis.choices = cours_choices
    form.fil_conducteur.choices = fils_conducteurs  # Ajouter les fils conducteurs ici

    if request.method == 'GET':
        # Pré-remplir le formulaire
        form.programme.data = cours['programme_id']
        form.code.data = cours['code']
        form.nom.data = cours['nom']
        form.session.data = cours['session']
        form.heures_theorie.data = cours['heures_theorie']
        form.heures_laboratoire.data = cours['heures_laboratoire']
        form.heures_travail_maison.data = cours['heures_travail_maison']
        form.corequis.data = corequis_existants

        # Pré-remplir le fil conducteur (s'il est associé au cours)
        if 'fil_conducteur_id' in cours:
            form.fil_conducteur.data = cours['fil_conducteur_id']
        else:
            form.fil_conducteur.data = None  # Ou une autre valeur par défaut
        # Vider les entrées existantes d'éléments de compétence
        form.elements_competence.entries = []
        for ec in ec_assoc:
            subform = form.elements_competence.append_entry()
            subform.element_competence.choices = ec_choices
            subform.element_competence.data = ec['element_competence_id']
            subform.status.data = ec['status']

        if not ec_assoc:
            subform = form.elements_competence.append_entry()
            subform.element_competence.choices = ec_choices
            subform.element_competence.data = None
            subform.status.data = None

        # Pré-remplir les préalables avec note
        form.prealables.entries = []  # Au cas où
        for p in prealables_existants:
            p_subform = form.prealables.append_entry()
            p_subform.cours_prealable_id.choices = cours_choices
            p_subform.cours_prealable_id.data = p['id']
            p_subform.note_necessaire.data = p['note']

    else:
        # Pour les POST, redéfinir les choices
        for subform in form.elements_competence:
            subform.element_competence.choices = ec_choices
        
        for p_subform in form.prealables:
            p_subform.cours_prealable_id.choices = cours_choices

    if form.validate_on_submit():
        # Récupérer les données
        programme_id = form.programme.data
        code = form.code.data
        nom = form.nom.data
        session_num = form.session.data
        heures_theorie = form.heures_theorie.data
        heures_laboratoire = form.heures_laboratoire.data
        heures_travail_maison = form.heures_travail_maison.data
        fil_conducteur_id = form.fil_conducteur.data  # Récupérer le fil conducteur sélectionné

        elements_competence_data = form.elements_competence.data or []

        # Nouvelles données de préalables
        nouveaux_prealables_data = form.prealables.data or []
        # Nouvelles données de corequis
        nouveaux_corequis = form.corequis.data

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Mise à jour du cours
            cursor.execute('''
                UPDATE Cours
                SET programme_id = ?, code = ?, nom = ?, session = ?, heures_theorie = ?, heures_laboratoire = ?, heures_travail_maison = ?, fil_conducteur_id = ?
                WHERE id = ?
            ''', (programme_id, code, nom, session_num, heures_theorie, heures_laboratoire, heures_travail_maison, fil_conducteur_id, cours_id))

            # Mise à jour des éléments de compétence
            cursor.execute('DELETE FROM ElementCompetenceParCours WHERE cours_id = ?', (cours_id,))
            for ec in elements_competence_data:
                element_id = ec['element_competence']
                status = ec['status']
                if element_id and status:
                    cursor.execute('''
                        INSERT INTO ElementCompetenceParCours (cours_id, element_competence_id, status)
                        VALUES (?, ?, ?)
                    ''', (cours_id, element_id, status))

            # Mise à jour des préalables (avec la note)
            cursor.execute('DELETE FROM CoursPrealable WHERE cours_id = ?', (cours_id,))
            for p_data in nouveaux_prealables_data:
                p_id = p_data['cours_prealable_id']
                note = p_data['note_necessaire']
                if p_id and note is not None:
                    cursor.execute('''
                        INSERT INTO CoursPrealable (cours_id, cours_prealable_id, note_necessaire)
                        VALUES (?, ?, ?)
                    ''', (cours_id, p_id, note))

            # Mise à jour des corequis
            cursor.execute('DELETE FROM CoursCorequis WHERE cours_id = ?', (cours_id,))
            for c_id in nouveaux_corequis:
                cursor.execute('''
                    INSERT INTO CoursCorequis (cours_id, cours_corequis_id)
                    VALUES (?, ?)
                ''', (cours_id, c_id))

            conn.commit()
            conn.close()
            flash('Cours mis à jour avec succès!', 'success')
            return redirect(url_for('main.view_programme', programme_id=programme_id))
        except sqlite3.Error as e:
            flash(f'Erreur lors de la mise à jour du cours : {e}', 'danger')
            return redirect(url_for('main.edit_cours', cours_id=cours_id))

    return render_template('edit_cours.html', form=form, elements_competence=elements_competence, cours_choices=cours_choices)



@main.route('/element_competence/<int:element_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_element_competence(element_id):
    conn = get_db_connection()
    element = conn.execute('SELECT * FROM ElementCompetence WHERE id = ?', (element_id,)).fetchone()
    if element is None:
        flash('Élément de compétence non trouvé.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))

    # Récupérer les compétences pour le choix du champ competence
    competences = conn.execute('SELECT id, nom FROM Competence').fetchall()
    conn.close()

    form = ElementCompetenceForm()
    form.competence.choices = [(c['id'], c['nom']) for c in competences]

    # Pré-remplir le formulaire s'il s'agit d'une requête GET
    if request.method == 'GET':
        form.competence.data = element['competence_id']
        form.nom.data = element['nom']

        # Récupérer les critères pour cet élément
        conn = get_db_connection()
        criteres_rows = conn.execute('SELECT criteria FROM ElementCompetenceCriteria WHERE element_competence_id = ?', (element_id,)).fetchall()
        conn.close()

        form.criteres_de_performance.entries = []
        for critere in criteres_rows:
            form.criteres_de_performance.append_entry(critere['criteria'])

    if form.validate_on_submit():
        competence_id = form.competence.data
        nom = form.nom.data
        criteres_data = form.criteres_de_performance.data

        # Mettre à jour l'élément de compétence
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE ElementCompetence SET competence_id = ?, nom = ? WHERE id = ?', (competence_id, nom, element_id))

        # Supprimer les anciens critères
        cursor.execute('DELETE FROM ElementCompetenceCriteria WHERE element_competence_id = ?', (element_id,))

        # Insérer les nouveaux critères
        for crit in criteres_data:
            if crit.strip():
                cursor.execute('INSERT INTO ElementCompetenceCriteria (element_competence_id, criteria) VALUES (?, ?)', (element_id, crit.strip()))

        conn.commit()
        conn.close()

        flash('Élément de compétence mis à jour avec succès!', 'success')
        return redirect(url_for('main.view_competence', competence_id=competence_id))

    return render_template('edit_element_competence.html', form=form)




@main.route('/cours/<int:cours_id>/plan_cadre/<int:plan_id>/capacite/<int:capacite_id>/edit', methods=['GET', 'POST'])
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
            return redirect(url_for('main.edit_capacite', cours_id=cours_id, plan_id=plan_id, capacite_id=capacite_id))

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
            return redirect(url_for('main.view_plan_cadre', cours_id=cours_id, plan_id=plan_id))
        except sqlite3.Error as e:
            conn.rollback()
            flash(f'Erreur lors de la mise à jour de la capacité : {e}', 'danger')
            conn.close()
            return redirect(url_for('main.edit_capacite', cours_id=cours_id, plan_id=plan_id, capacite_id=capacite_id))

    return render_template('edit_capacite.html', form=form, plan_id=plan_id, capacite_id=capacite_id, cours_id=cours_id)



# Nouvelle Route pour Supprimer un Cours
@main.route('/cours/<int:cours_id>/delete', methods=['POST'])
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

@main.route('/competence/code/<string:competence_code>')
@login_required
def view_competence_by_code(competence_code):
    conn = get_db_connection()
    competence = conn.execute('SELECT id FROM Competence WHERE code = ?', (competence_code,)).fetchone()
    conn.close()

    if not competence:
        flash('Compétence non trouvée.', 'danger')
        return redirect(url_for('main.index'))

    # Rediriger vers la route existante avec competence_id
    return redirect(url_for('main.view_competence', competence_id=competence['id']))


@main.route('/competence/<int:competence_id>')
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


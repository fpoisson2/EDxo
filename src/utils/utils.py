import os
from datetime import datetime
from io import BytesIO

from jinja2 import Template
from bs4 import BeautifulSoup
from docxtpl import DocxTemplate
from dotenv import load_dotenv
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TimeField, BooleanField
from wtforms.validators import DataRequired, Email
from apscheduler.schedulers.background import BackgroundScheduler
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from utils.scheduler_instance import scheduler, start_scheduler

from app.models import User, Cours, Programme

from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

from app.models import db, BackupConfig, User, Competence, ElementCompetence, ElementCompetenceCriteria, \
                   ElementCompetenceParCours, FilConducteur, CoursPrealable, CoursCorequis, CompetenceParCours, \
                   PlanCadre, PlanCadreCoursCorequis, PlanCadreCapacites, PlanCadreCapaciteSavoirsNecessaires, \
                   PlanCadreCapaciteSavoirsFaire, PlanCadreCapaciteMoyensEvaluation, PlanCadreSavoirEtre, \
                   PlanCadreObjetsCibles, PlanCadreCoursRelies, PlanCadreCoursPrealables, \
                   PlanCadreCompetencesCertifiees, PlanCadreCompetencesDeveloppees, PlanDeCours, PlanDeCoursCalendrier, \
                   PlanDeCoursMediagraphie, PlanDeCoursDisponibiliteEnseignant, PlanDeCoursEvaluations, \
                   PlanDeCoursEvaluationsCapacites, Department, DepartmentRegles, DepartmentPIEA, \
                   ListeProgrammeMinisteriel, Programme, Cours, ListeCegep, GlobalGenerationSettings, user_programme

import base64

import pytz
import logging

# Configuration de base du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE = 'programme.db'

def is_teacher_in_programme(user_id, programme_id):
    """
    Vérifie si un enseignant est associé à un programme donné.
    
    Args:
        user_id (int): ID de l'utilisateur
        programme_id (int): ID du programme
        
    Returns:
        bool: True si l'enseignant est associé au programme
    """

    user = db.session.get(User, user_id)
    if not user:
        logging.debug(f"is_teacher_in_programme: Aucun utilisateur trouvé avec l'ID {user_id}")
        return False
    if user.role != 'professeur':
        logging.debug(f"is_teacher_in_programme: L'utilisateur {user_id} a le rôle '{user.role}', et non 'enseignant'")
        return False
    
    # Vérifie si le programme est associé à l'utilisateur via la table user_programme
    associated = db.session.query(user_programme).filter_by(user_id=user_id, programme_id=programme_id).first() is not None
    
    logging.debug(f"is_teacher_in_programme: L'utilisateur {user_id} est associé au programme {programme_id}: {associated}")

    return associated

def get_programme_id_for_cours(cours_id):
    """Get the programme ID associated with a course."""
    cours = db.session.get(Cours, cours_id)
    return cours.programme_id if cours else None

def is_coordo_for_programme(user_id, programme_id):
    """Check if user is coordinator for given programme."""
    user = db.session.get(User, user_id)
    return programme_id in [p.id for p in user.programmes]

def send_backup_email(app, recipient_email, db_path):
    """
    Envoie un email (via l'API Gmail) contenant la base de données en pièce jointe.
    """
    import os
    import base64
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email.mime.text import MIMEText
    from email import encoders

    logger.info(f"Starting scheduled backup to {recipient_email}")

    SCOPES = ['https://www.googleapis.com/auth/gmail.send']
    creds = None

    # Vérification du token
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            # ✅ Utilisation de run_local_server avec open_browser=False
            creds = flow.run_local_server(port=0, open_browser=False)

        # Sauvegarde du token
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)

    # Créer le message
    message = MIMEMultipart()
    message['to'] = recipient_email
    message['from'] = recipient_email
    message['subject'] = "BD EDxo"

    # Corps du message (texte)
    text_part = MIMEText('Bonjour, voici la dernière version de la BD de EDxo', 'plain')
    message.attach(text_part)

    # Lecture du fichier .db et ajout en pièce jointe
    with open(db_path, 'rb') as f:
        file_data = f.read()

    attachment = MIMEBase('application', 'octet-stream')
    attachment.set_payload(file_data)
    encoders.encode_base64(attachment)
    attachment.add_header('Content-Disposition', 'attachment', filename='backup.db')
    message.attach(attachment)

    # Encoder le message en base64
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

    # Envoi via l'API Gmail
    try:
        sent_message = service.users().messages().send(
            userId='me',
            body={'raw': raw}
        ).execute()
        print("Message envoyé. ID:", sent_message['id'])
    except Exception as e:
        print("Erreur:", e)


def get_initials(nom_complet):
    """
    Extrait les initiales d'un nom complet.
    
    Args:
        nom_complet (str): Le nom complet de l'enseignant
        
    Returns:
        str: Les initiales en majuscules
    """
    mots = nom_complet.strip().split()
    initiales = ''.join(mot[0].upper() for mot in mots if mot)
    return initiales


def get_all_cegeps():
    """
    Retourne la liste de tous les cégeps (id, nom) via SQLAlchemy.
    """
    cegeps = db.session.query(ListeCegep).all()
    result = []
    for c in cegeps:
        result.append({'id': c.id, 'nom': c.nom})
    return result


def get_cegep_details_data(cegep_id):
    """
    Récupère les départements et programmes pour un cégep spécifique, via SQLAlchemy.
    """
    departments = db.session.query(Department).filter(Department.cegep_id == cegep_id).all()
    programmes = db.session.query(Programme).filter(Programme.cegep_id == cegep_id).all()

    return {
        'departments': [{'id': d.id, 'nom': d.nom} for d in departments],
        'programmes': [{'id': p.id, 'nom': p.nom} for p in programmes]
    }


def get_all_departments():
    """
    Retourne la liste de tous les départements (id, nom) via SQLAlchemy.
    """
    departments = db.session.query(Department).all()
    return [{'id': d.id, 'nom': d.nom} for d in departments]


def get_all_programmes():
    """
    Retourne la liste de tous les programmes (id, nom) via SQLAlchemy.
    """
    programmes = db.session.query(Programme).all()
    return [{'id': p.id, 'nom': p.nom} for p in programmes]


def get_programmes_by_user(user_id):
    """
    Récupère la liste des programme_id associés à un utilisateur donné (via la table d'association user_programme).
    """
    rows = db.session.query(user_programme.c.programme_id).filter(user_programme.c.user_id == user_id).all()
    return [{'programme_id': r[0]} for r in rows]


def parse_html_to_list(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    return [li.get_text(strip=True) for li in soup.find_all('li')]


def parse_html_to_nested_list(html_content):
    """
    Parses HTML content with nested <ul> and <ol> elements and returns a
    nested list structure with sub-items included recursively.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    def process_list(items):
        result = []
        for li in items:
            item_text = li.contents[0].strip() if li.contents else ""
            sub_items = []

            nested_list = li.find('ul') or li.find('ol')
            if nested_list:
                sub_items = process_list(nested_list.find_all('li', recursive=False))

            if sub_items:
                result.append({
                    'text': item_text,
                    'sub_items': sub_items
                })
            else:
                result.append({
                    'text': item_text
                })
        return result

    top_list = soup.find('ul') or soup.find('ol')
    if top_list:
        return process_list(top_list.find_all('li', recursive=False))
    else:
        return []


def get_plan_cadre_data(cours_id, db_path='programme.db'):
    """
    Récupère et retourne les informations d'un plan cadre pour un cours donné sous forme de dictionnaire
    (remplaçant les anciennes connexions directes par SQLAlchemy).
    """
    plan_cadre = {}

    try:
        # 1. Nom du cours, Code du cours et session
        cours = db.session.query(Cours).filter_by(id=cours_id).first()
        if not cours:
            print(f"Aucun cours trouvé avec l'ID {cours_id}.")
            return None

        plan_cadre['cours'] = {
            'nom': cours.nom,
            'code': cours.code,
            'session': cours.session,
            'heures_theorie': cours.heures_theorie,
            'heures_laboratoire': cours.heures_laboratoire,
            'heures_maison': cours.heures_travail_maison
        }

        # 2. Nom du programme
        programme_nom = "Non défini"
        if cours.programme_id:
            programme = db.session.query(Programme).filter_by(id=cours.programme_id).first()
            if programme:
                programme_nom = programme.nom
        plan_cadre['programme'] = programme_nom

        # 2. Fil conducteur
        fil_conducteur_desc = "Non défini"
        if cours.fil_conducteur_id:
            fil_conducteur = db.session.query(FilConducteur).filter_by(id=cours.fil_conducteur_id).first()
            if fil_conducteur:
                fil_conducteur_desc = fil_conducteur.description
        plan_cadre['fil_conducteur'] = fil_conducteur_desc

        # 3. Éléments de compétence développée ou atteinte
        #   Requiert un LEFT JOIN avec ElementCompetenceCriteria
        #   Pas de relation directe, on fait le join manuellement
        elems = db.session.query(
            ElementCompetence.id.label('element_competence_id'),
            ElementCompetence.nom.label('element_nom'),
            ElementCompetenceParCours.status.label('status'),
            ElementCompetence.competence_id.label('competence_id'),
            ElementCompetenceCriteria.criteria.label('critere_performance')
        ) \
        .join(ElementCompetenceParCours, ElementCompetence.id == ElementCompetenceParCours.element_competence_id) \
        .outerjoin(ElementCompetenceCriteria, ElementCompetence.id == ElementCompetenceCriteria.element_competence_id) \
        .filter(ElementCompetenceParCours.cours_id == cours_id).all()

        plan_cadre['elements_competences_developpees'] = []
        for row in elems:
            plan_cadre['elements_competences_developpees'].append({
                'element_nom': row.element_nom,
                'element_competence_id': row.element_competence_id,
                'status': row.status,
                'competence_id': row.competence_id,
                'critere_performance': row.critere_performance
            })

        # 4. Compétences développées
        comps_developpees = db.session.query(
            ElementCompetence.competence_id,
            Competence.nom.label('competence_nom'),
            Competence.criteria_de_performance.label('critere_performance'),
            Competence.contexte_de_realisation.label('contexte_realisation')
        ) \
        .join(ElementCompetenceParCours, ElementCompetence.id == ElementCompetenceParCours.element_competence_id) \
        .join(Competence, ElementCompetence.competence_id == Competence.id) \
        .filter(ElementCompetenceParCours.cours_id == cours_id, ElementCompetenceParCours.status == 'Développé significativement') \
        .distinct().all()

        plan_cadre['competences_developpees'] = []
        for row in comps_developpees:
            plan_cadre['competences_developpees'].append({
                'competence_nom': row.competence_nom,
                'competence_id': row.competence_id,
                'critere_performance': row.critere_performance,
                'contexte_realisation': row.contexte_realisation
            })

        # 5. Compétences atteintes
        comps_atteintes = db.session.query(
            ElementCompetence.competence_id,
            Competence.nom.label('competence_nom'),
            Competence.criteria_de_performance.label('critere_performance'),
            Competence.contexte_de_realisation.label('contexte_realisation')
        ) \
        .join(ElementCompetenceParCours, ElementCompetence.id == ElementCompetenceParCours.element_competence_id) \
        .join(Competence, ElementCompetence.competence_id == Competence.id) \
        .filter(ElementCompetenceParCours.cours_id == cours_id, ElementCompetenceParCours.status == 'Atteint') \
        .distinct().all()

        plan_cadre['competences_atteintes'] = []
        for row in comps_atteintes:
            plan_cadre['competences_atteintes'].append({
                'competence_nom': row.competence_nom,
                'competence_id': row.competence_id,
                'critere_performance': row.critere_performance,
                'contexte_realisation': row.contexte_realisation
            })

        # 6. Cours préalables
        prealables = db.session.query(
            CoursPrealable.cours_prealable_id,
            Cours.nom.label('cours_prealable_nom'),
            Cours.code.label('cours_prealable_code')
        ) \
        .join(Cours, CoursPrealable.cours_prealable_id == Cours.id) \
        .filter(CoursPrealable.cours_id == cours_id).all()

        plan_cadre['cours_prealables'] = []
        for row in prealables:
            plan_cadre['cours_prealables'].append({
                'cours_prealable_code': row.cours_prealable_code,
                'cours_prealable_nom': row.cours_prealable_nom,
                'cours_prealable_id': row.cours_prealable_id
            })

        # 7. Préalable à quel(s) cours
        prealables_of = db.session.query(
            CoursPrealable.cours_id.label('cours_prealable_a_id'),
            Cours.nom.label('cours_prealable_a_nom'),
            Cours.code.label('cours_prealable_a_code')
        ) \
        .join(Cours, CoursPrealable.cours_id == Cours.id) \
        .filter(CoursPrealable.cours_prealable_id == cours_id).all()

        plan_cadre['prealables_of'] = []
        for row in prealables_of:
            plan_cadre['prealables_of'].append({
                'cours_prealable_a_code': row.cours_prealable_a_code,
                'cours_prealable_a_nom': row.cours_prealable_a_nom,
                'cours_prealable_a_id': row.cours_prealable_a_id
            })

        # 8. Cours corequis
        corequis = db.session.query(
            CoursCorequis.cours_corequis_id,
            Cours.nom
        ) \
        .join(Cours, CoursCorequis.cours_corequis_id == Cours.id) \
        .filter(CoursCorequis.cours_id == cours_id).all()

        plan_cadre['cours_corequis'] = []
        for row in corequis:
            plan_cadre['cours_corequis'].append({
                'cours_corequis_id': row.cours_corequis_id,
                'cours_corequis_nom': row.nom
            })

        # 9. Cours développant une même compétence avant, pendant et après
        #    Reprise de la logique "SELECT ... FROM Cours AS C JOIN ElementCompetenceParCours"
        #    Filtre sur les mêmes éléments de compétence que cours_id
        subquery = db.session.query(ElementCompetenceParCours.element_competence_id).filter_by(cours_id=cours_id).subquery()
        cours_developpant = db.session.query(
            Cours.id.label('cours_id'),
            Cours.nom.label('cours_nom'),
            Cours.code.label('code'),
            Cours.session.label('session')
        ) \
        .join(ElementCompetenceParCours, Cours.id == ElementCompetenceParCours.cours_id) \
        .filter(ElementCompetenceParCours.element_competence_id.in_(subquery)) \
        .filter(Cours.id != cours_id) \
        .distinct().all()

        plan_cadre['cours_developpant_une_meme_competence'] = []
        # Ici, l'ancienne requête concaténait l'ID de compétence. On n'a pas besoin d'exactement ça si on veut juste la liste.
        # On peut ignorer la concaténation et se contenter de lister les cours.
        for row in cours_developpant:
            plan_cadre['cours_developpant_une_meme_competence'].append({
                'cours_nom': row.cours_nom,
                'cours_id': row.cours_id,
                'code': row.code,
                'session': row.session,
                'competence_ids': ''  # On n'a pas la concat directe, on peut mettre vide ou ajouter une requête supplémentaire si besoin
            })

    except Exception as e:
        print(f"Erreur SQLite/Ailleurs (via SQLAlchemy): {e}")
        return None

    return plan_cadre


def replace_tags_jinja2(text, plan_cadre, extra_context=None):
    """
    Utilise Jinja2 pour remplacer les tags dans le texte avec les données de plan_cadre et un contexte supplémentaire.
    """
    try:
        template = Template(text)
        
        context = {
            'code_cours': plan_cadre['cours']['code'],
            'nom_cours': plan_cadre['cours']['nom'],
            'fil_conducteur': plan_cadre['fil_conducteur'],
            'programme': plan_cadre['programme'],
            'session': plan_cadre['cours'].get('session', 'Non défini'),
            'competences_developpees': plan_cadre.get('competences_developpees', []),
            'competences_atteintes': plan_cadre.get('competences_atteintes', []),
            'cours_prealables': plan_cadre.get('cours_prealables', []),
            'cours_corequis': plan_cadre.get('cours_corequis', []),
            'cours_developpant_une_meme_competence': plan_cadre.get('cours_developpant_une_meme_competence', []),
            'heures_theorie': plan_cadre['cours']['heures_theorie'],
            'heures_lab': plan_cadre['cours']['heures_laboratoire'],
            'heures_maison': plan_cadre['cours']['heures_maison']
        }
        
        if extra_context:
            context.update(extra_context)

        replaced_text = template.render(**context)
        return replaced_text
    except KeyError as e:
        print("Clé manquante dans le contexte lors du rendu du template")
        raise
    except Exception as e:
        print("Erreur lors du rendu du template Jinja2")
        raise


def process_ai_prompt(prompt, role):
    """
    Sends the prompt to the AI service and returns the generated content.
    (Fonction indicative, non-implémentée dans ce code.)
    """
    try:
        # Simulation
        return "AI-generated content here."
    except Exception as e:
        print("Error generating AI content")
        return None


def generate_docx_with_template(plan_id):
    """
    Génère un fichier DOCX à partir d'un modèle et des informations d'un PlanCadre, via SQLAlchemy.
    """
    template_path = os.path.join('static', 'docs', 'plan_cadre_template.docx')

    if not os.path.exists(template_path):
        print("Erreur : Le modèle DOCX n'a pas été trouvé !")
        return None

    # Récupérer le plan-cadre
    plan = db.session.query(PlanCadre).filter_by(id=plan_id).first()
    if not plan:
        return None

    # Récupérer le cours associé
    cours = db.session.query(Cours).filter_by(id=plan.cours_id).first()
    if not cours:
        return None

    # Récupérer le programme associé
    programme = None
    if cours.programme_id:
        programme = db.session.query(Programme).filter_by(id=cours.programme_id).first()

    # Récupérer les compétences développées (texte, description)
    competences_developpees = db.session.query(PlanCadreCompetencesDeveloppees).filter_by(plan_cadre_id=plan_id).all()

    # Récupérer la table ElementCompetenceParCours pour ce cours
    ecpc = db.session.query(ElementCompetenceParCours).filter_by(cours_id=cours.id).all()
    # Filtrer seulement ceux avec status='Développé significativement' pour comptabiliser la liste
    developpee_ids = {e.element_competence_id for e in ecpc if e.status == 'Développé significativement'}

    # Récupérer la liste unique des competences ID pour ces éléments
    competence_ids = set()
    for elemcompid in developpee_ids:
        elem = db.session.query(ElementCompetence).filter_by(id=elemcompid).all()
        for e in elem:
            competence_ids.add(e.competence_id)

    competence_info_developes = {}
    for cid in competence_ids:
        c_results = db.session.query(Competence).filter_by(id=cid).all()
        for c in c_results:
            contexte_html = c.contexte_de_realisation
            contexte_parsed = parse_html_to_nested_list(contexte_html) if contexte_html else []

            criteria_html = c.criteria_de_performance
            criteria_parsed = parse_html_to_list(criteria_html) if criteria_html else []

            if c.id not in competence_info_developes:
                competence_info_developes[c.id] = {
                    "id": c.id,
                    "code": c.code,
                    "nom": c.nom,
                    "criteria_de_performance": criteria_parsed,
                    "contexte_de_realisation": contexte_parsed,
                    "elements": []
                }

            # Récupérer les éléments de compétence
            ec_data = db.session.query(ElementCompetence).filter_by(competence_id=c.id).all()
            for ec_item in ec_data:
                # Récupérer les critères individuellement
                criteria_data = db.session.query(ElementCompetenceCriteria).filter_by(element_competence_id=ec_item.id).all()
                crit_list = [cd.criteria for cd in criteria_data]

                element_competence = {
                    "element_competence_id": ec_item.id,
                    "nom": ec_item.nom,
                    "competence_id": ec_item.competence_id,
                    "criteria": crit_list,
                    "cours_associes": []
                }

                # Récupérer les cours associés
                assoc_cours = db.session.query(Cours, ElementCompetenceParCours).join(
                    ElementCompetenceParCours, Cours.id == ElementCompetenceParCours.cours_id
                ).filter(ElementCompetenceParCours.element_competence_id == ec_item.id).order_by(Cours.session).all()

                for (cours_assoc, ecpc_assoc) in assoc_cours:
                    element_competence["cours_associes"].append({
                        "cours_id": cours_assoc.id,
                        "cours_code": cours_assoc.code,
                        "cours_nom": cours_assoc.nom,
                        "cours_session": cours_assoc.session,
                        "status": ecpc_assoc.status
                    })

                competence_info_developes[c.id]["elements"].append(element_competence)

    # Répéter le même processus pour les compétences atteintes
    atteint_ids = {e.element_competence_id for e in ecpc if e.status == 'Atteint'}

    comp_atteint_ids = set()
    for elemcompid in atteint_ids:
        elem = db.session.query(ElementCompetence).filter_by(id=elemcompid).all()
        for e in elem:
            comp_atteint_ids.add(e.competence_id)

    competence_info_atteint = {}
    for cid in comp_atteint_ids:
        c_results = db.session.query(Competence).filter_by(id=cid).all()
        for c in c_results:
            contexte_html = c.contexte_de_realisation
            contexte_parsed = parse_html_to_nested_list(contexte_html) if contexte_html else []

            criteria_html = c.criteria_de_performance
            criteria_parsed = parse_html_to_list(criteria_html) if criteria_html else []

            if c.id not in competence_info_atteint:
                competence_info_atteint[c.id] = {
                    "id": c.id,
                    "code": c.code,
                    "nom": c.nom,
                    "criteria_de_performance": criteria_parsed,
                    "contexte_de_realisation": contexte_parsed,
                    "elements": []
                }

            # Récupérer les éléments de compétence
            ec_data = db.session.query(ElementCompetence).filter_by(competence_id=c.id).all()
            for ec_item in ec_data:
                # Récupérer les critères individuellement
                criteria_data = db.session.query(ElementCompetenceCriteria).filter_by(element_competence_id=ec_item.id).all()
                crit_list = [cd.criteria for cd in criteria_data]

                element_competence = {
                    "element_competence_id": ec_item.id,
                    "nom": ec_item.nom,
                    "competence_id": ec_item.competence_id,
                    "criteria": crit_list,
                    "cours_associes": []
                }

                # Récupérer les cours associés
                assoc_cours = db.session.query(Cours, ElementCompetenceParCours).join(
                    ElementCompetenceParCours, Cours.id == ElementCompetenceParCours.cours_id
                ).filter(ElementCompetenceParCours.element_competence_id == ec_item.id).order_by(Cours.session).all()

                for (cours_assoc, ecpc_assoc) in assoc_cours:
                    element_competence["cours_associes"].append({
                        "cours_id": cours_assoc.id,
                        "cours_code": cours_assoc.code,
                        "cours_nom": cours_assoc.nom,
                        "cours_session": cours_assoc.session,
                        "status": ecpc_assoc.status
                    })

                competence_info_atteint[c.id]["elements"].append(element_competence)

    objets_cibles = db.session.query(PlanCadreObjetsCibles).filter_by(plan_cadre_id=plan_id).all()
    cours_relies = db.session.query(PlanCadreCoursRelies).filter_by(plan_cadre_id=plan_id).all()

    # Récupérer et structurer les capacités
    capacites_db = db.session.query(PlanCadreCapacites).filter_by(plan_cadre_id=plan_id).all()
    capacites_detail = []
    for cap in capacites_db:
        sav_necessaires = db.session.query(PlanCadreCapaciteSavoirsNecessaires).filter_by(capacite_id=cap.id).all()
        sav_faire = db.session.query(PlanCadreCapaciteSavoirsFaire).filter_by(capacite_id=cap.id).all()
        moyens_eval = db.session.query(PlanCadreCapaciteMoyensEvaluation).filter_by(capacite_id=cap.id).all()

        capacites_detail.append({
            'capacite': cap.capacite,
            'description_capacite': cap.description_capacite,
            'ponderation_min': cap.ponderation_min,
            'ponderation_max': cap.ponderation_max,
            'savoirs_necessaires': [s.texte for s in sav_necessaires],
            'savoirs_faire': [
                {
                    'texte': sf.texte,
                    'cible': sf.cible,
                    'seuil_reussite': sf.seuil_reussite
                } for sf in sav_faire
            ],
            'moyens_evaluation': [me.texte for me in moyens_eval]
        })

    savoir_etre_db = db.session.query(PlanCadreSavoirEtre).filter_by(plan_cadre_id=plan_id).all()
    cours_corequis_db = db.session.query(PlanCadreCoursCorequis).filter_by(plan_cadre_id=plan_id).all()
    competences_certifiees_db = db.session.query(PlanCadreCompetencesCertifiees).filter_by(plan_cadre_id=plan_id).all()

    # 9. Cours développant une même compétence avant, pendant et après
    #    On refait une requête similaire pour lister tous les cours liés
    subq = db.session.query(ElementCompetenceParCours.element_competence_id).filter_by(cours_id=plan.cours_id).subquery()
    cours_meme_competence = db.session.query(
        Cours.id.label('cours_id'),
        Cours.nom.label('cours_nom'),
        Cours.code.label('code'),
        Cours.session.label('session')
    ) \
    .join(ElementCompetenceParCours, Cours.id == ElementCompetenceParCours.cours_id) \
    .filter(ElementCompetenceParCours.element_competence_id.in_(subq)) \
    .distinct().all()

    # Récupérer les cours corequis
    cc = db.session.query(CoursCorequis, Cours).join(
        Cours, CoursCorequis.cours_corequis_id == Cours.id
    ).filter(CoursCorequis.cours_id == plan.cours_id).distinct().all()

    # Récupérer les cours préalables
    cp = db.session.query(CoursPrealable, Cours).join(
        Cours, CoursPrealable.cours_prealable_id == Cours.id
    ).filter(CoursPrealable.cours_id == plan.cours_id).distinct().all()

    context = {
        'programme': {
            'nom': programme.nom if programme else 'Non défini',
            'departement': programme.department.nom if (programme and programme.department) else 'Non défini'
        },
        'cours': {
            'code': cours.code,
            'nom': cours.nom,
            'session': cours.session,
            'heures_theorie': cours.heures_theorie,
            'heures_laboratoire': cours.heures_laboratoire,
            'heures_travail_maison': cours.heures_travail_maison,
            'nombre_unites': cours.nombre_unites
        },
        'plan_cadre': {
            'place_intro': plan.place_intro,
            'objectif_terminal': plan.objectif_terminal,
            'structure_intro': plan.structure_intro,
            'structure_activites_theoriques': plan.structure_activites_theoriques,
            'structure_activites_pratiques': plan.structure_activites_pratiques,
            'structure_activites_prevues': plan.structure_activites_prevues,
            'eval_evaluation_sommative': plan.eval_evaluation_sommative,
            'eval_nature_evaluations_sommatives': plan.eval_nature_evaluations_sommatives,
            'eval_evaluation_de_la_langue': plan.eval_evaluation_de_la_langue,
            'eval_evaluation_sommatives_apprentissages': plan.eval_evaluation_sommatives_apprentissages
        },
        'competences_developpees': [
            {'texte': cd.texte, 'description': cd.description} for cd in competences_developpees
        ],
        'objets_cibles': [{'texte': o.texte, 'description': o.description} for o in objets_cibles],
        'cours_relies': [{'texte': cr.texte, 'description': cr.description} for cr in cours_relies],
        'capacites': capacites_detail,
        'savoir_etre': [{'texte': se.texte} for se in savoir_etre_db],
        'competences_info_developes': list(competence_info_developes.values()),
        'competences_info_atteint': list(competence_info_atteint.values()),
        'cours_corequis': [{'texte': cco.texte, 'description': cco.description} for cco in cours_corequis_db],
        'competences_certifiees': [{'texte': ccx.texte, 'description': ccx.description} for ccx in competences_certifiees_db],
        'cours_developpant_une_meme_competence': [
            {
                'cours_id': cdmc.cours_id,
                'cours_nom': cdmc.cours_nom,
                'code': cdmc.code,
                'session': cdmc.session
            }
            for cdmc in cours_meme_competence
        ],
        'cc': [
            {
                'nom': co[1].nom,
                'code': co[1].code
            } for co in cc
        ],
        'cp': [
            {
                'nom': co[1].nom,
                'code': co[1].code,
                'note_necessaire': co[0].note_necessaire
            } for co in cp
        ]
    }

    tpl = DocxTemplate(template_path)
    tpl.render(context)

    file_stream = BytesIO()
    tpl.save(file_stream)
    file_stream.seek(0)

    return file_stream


def get_programme_id(conn, competence_id):
    """
    Fonction utilitaire pour récupérer le programme_id à partir d'une competence_id.
    (Ce n'est plus utilisé car on utilise SQLAlchemy partout, mais laissé tel quel.)
    """
    programme = db.session.query(Competence.programme_id).filter_by(id=competence_id).first()
    return programme[0] if programme else None

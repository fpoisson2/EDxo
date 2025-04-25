# programme.py
import logging
from collections import defaultdict

import bleach
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app

import os

import html

import json
from flask_login import login_required, current_user

from app.forms import (
    CompetenceForm,
    DeleteForm,
    ReviewImportConfirmForm
)
# Import SQLAlchemy models
from app.models import (
    db,
    User,
    Programme,
    Competence,
    FilConducteur,
    Cours,
    CoursPrealable,
    CoursCorequis,
    ElementCompetence,
    ElementCompetenceCriteria,
    ElementCompetenceParCours,
    PlanDeCours
)
from utils.decorator import role_required, ensure_profile_completed, roles_required

# Utilities
# Example of another blueprint import (unused here, just as in your snippet)
logger = logging.getLogger(__name__)

programme_bp = Blueprint('programme', __name__, url_prefix='/programme')

@programme_bp.route('/<int:programme_id>/competences')
@login_required
@ensure_profile_completed
def view_competences_programme(programme_id):
    """
    Affiche la liste de toutes les compétences associées à un programme spécifique.
    """
    logger.debug(f"Accessing competencies list for programme ID: {programme_id}")
    programme = Programme.query.get_or_404(programme_id)

    # Vérifier l’accès
    if programme not in current_user.programmes and current_user.role != 'admin':
        flash("Vous n'avez pas accès à ce programme.", 'danger')
        return redirect(url_for('main.index'))

    # Récupérer toutes les compétences via la relation many-to-many,
    # triées par code
    competences = (
        programme
        .competences          # backref dynamique défini sur Competence.programmes
        .order_by(Competence.code)
        .all()
    )

    return render_template(
        'programme/view_competences_programme.html',
        programme=programme,
        competences=competences
    )


@programme_bp.route('/review_import', methods=['POST'])
@login_required
def review_competencies_import():
    """
    Prépare un comparatif côte-à-côte pour chaque compétence identifiée par son code,
    entre la version en base de données et celle extraite du fichier JSON, en
    particulier pour le champ "Contexte" qui sera transformé pour ressembler à la version BD.
    """
    # Récupération des paramètres
    programme_id = request.form.get('programme_id')
    base_filename = request.form.get('base_filename')
    if not programme_id or not base_filename:
        flash("Informations manquantes (programme ou devis) pour démarrer la révision.", "danger")
        return redirect(url_for('ocr.show_trigger_page'))
    
    try:
        programme_id = int(programme_id)
    except ValueError:
        flash("ID de programme invalide.", "danger")
        return redirect(url_for('ocr.show_trigger_page'))
    
    programme = db.session.get(Programme, programme_id)
    if not programme:
        flash(f"Programme avec l'ID {programme_id} non trouvé.", "danger")
        abort(404)
    
    # Chemins vers les fichiers
    txt_output_dir = current_app.config.get('TXT_OUTPUT_DIR')
    ocr_file_path = os.path.join(txt_output_dir, f"{base_filename}_ocr.md")
    competencies_file_path = os.path.join(txt_output_dir, f"{base_filename}_competences.json")
    
    # Lecture du fichier OCR (bien que non utilisé dans le comparatif)
    ocr_text = ""
    try:
        with open(ocr_file_path, 'r', encoding='utf-8') as f:
            ocr_text = f.read()
    except Exception as e:
        logger.error(f"Erreur lors de la lecture OCR {ocr_file_path}: {e}", exc_info=True)
    
    # Lecture du fichier JSON de compétences
    competencies_data = None
    has_competencies_file = False
    try:
        with open(competencies_file_path, 'r', encoding='utf-8') as f:
            competencies_data = json.load(f)
        if not isinstance(competencies_data, dict) or 'competences' not in competencies_data:
            raise ValueError("Structure JSON invalide: clé 'competences' manquante.")
        has_competencies_file = True
    except Exception as e:
        logger.error(f"Erreur lors du parsing JSON {competencies_file_path}: {e}", exc_info=True)
        flash(f"Erreur lors de la lecture ou du parsing du fichier JSON des compétences: {e}", "warning")
    
    # Construction du comparatif pour chaque compétence
    comparisons = []
    if has_competencies_file and competencies_data and "competences" in competencies_data:
        for comp in competencies_data["competences"]:
            # Récupérer le code (dans "code" ou "Code")
            code = comp.get("code") or comp.get("Code")
            if not code:
                continue
            # Recherche en BD par code et programme
            db_comp = Competence.query.filter_by(code=code, programme_id=programme.id).first()
            db_version = None
            if db_comp:
                db_elements = []
                for elem in db_comp.elements:
                    criteria_list = [crit.criteria for crit in elem.criteria] if elem.criteria else []
                    db_elements.append({
                        "nom": elem.nom,
                        "criteres": criteria_list
                    })
                # Conversion du champ texte en une liste de critères à partir des lignes du texte
                db_criteres = db_comp.criteria_de_performance

                db_version = {
                    "code": db_comp.code,
                    "nom": db_comp.nom,
                    "contexte": db_comp.contexte_de_realisation,
                    "criteres": db_criteres,
                    "elements": db_elements
                }
            # Traitement de la version JSON
            json_elements = []
            if comp.get("Éléments"):
                for elem in comp["Éléments"]:
                    if isinstance(elem, str):
                        json_elements.append({
                            "nom": elem,
                            "criteres": None
                        })
                    elif isinstance(elem, dict):
                        json_elements.append({
                            "nom": elem.get("element") or elem.get("nom"),
                            "criteres": elem.get("criteres")
                        })
            json_version = {
                "code": comp.get("Code") or comp.get("code"),
                "nom": comp.get("Nom de la compétence") or comp.get("nom"),
                "contexte": comp.get("Contexte de réalisation"),
                "criteres": comp.get("Critères de performance pour l’ensemble de la compétence"),
                "elements": json_elements
            }
            comparisons.append({
                "code": code,
                "db": db_version,
                "json": json_version
            })
    
    form = ReviewImportConfirmForm()
    form.programme_id.data = programme_id
    form.base_filename.data = base_filename
    form.import_structured.data = 'true' if has_competencies_file and competencies_data else 'false'
    
    return render_template('programme/review_import.html',
                           programme=programme,
                           comparisons=comparisons,
                           base_filename=base_filename,
                           form=form)


def json_to_html_list(data):
    """
    Convertit une structure JSON (liste ou dict avec 'texte'/'sous_points')
    en une chaîne HTML formatée en liste imbriquée, en échappant le contenu texte.
    """
    if isinstance(data, list):
        # If data is a list, process each item and wrap in <ul>
        if not data: # Handle empty list
            return ""
        html_items = ""
        for item in data:
            html_items += json_to_html_list(item) # Recursive call for each item
        return f"<ul>{html_items}</ul>"

    elif isinstance(data, dict):
        # If data is a dict, extract 'texte', escape it, start <li>,
        # recursively process 'sous_points' if they exist, then close </li>
        texte = data.get("texte") or data.get("Text") or ""
        escaped_texte = html.escape(texte) # <-- Escape the text content
        html_content = f"<li>{escaped_texte}" # Start list item with escaped text

        sous_points = data.get("sous_points")
        if isinstance(sous_points, list) and sous_points: # Check if sous_points is a non-empty list
            # Recursive call for sub-points - this will return a nested <ul>...</ul>
            html_content += json_to_html_list(sous_points)

        html_content += "</li>" # Close the list item
        return html_content

    elif isinstance(data, str):
        # If data is just a string, escape it and wrap it in <li>
        if not data.strip(): # Handle empty string
             return ""
        escaped_data = html.escape(data) # <-- Escape the string content
        return f"<li>{escaped_data}</li>"

    else:
        # Ignore other data types or return their string representation (escaped)
        return html.escape(str(data)) if data is not None else ""

def format_context(context):
    """
    Formats the contexte de réalisation for database storage, aiming for safe HTML.

    - If 'context' is a list (typically from JSON like [{'texte': ..., 'sous_points': ...}]),
      it delegates to json_to_html_list to create potentially nested HTML <ul>/<li> lists.
    - If 'context' is a dictionary, it attempts to extract the 'texte' key or provides
      a safe string representation.
    - If 'context' is a string containing newline characters, it formats it as an
      HTML <ul> list with each line as an <li> item.
    - If 'context' is a simple string, it returns the HTML-escaped string.
    - Handles other types by converting them to string and escaping.

    Args:
        context: The data to format (list, dict, str, etc.).

    Returns:
        A string containing safe HTML representation of the context.
    """
    if isinstance(context, list):
        # Delegate list processing to the recursive function that handles nesting
        # Assumes json_to_html_list exists and handles escaping internally
        try:
            # Add try-except block for robustness if json_to_html_list might fail
             return json_to_html_list(context)
        except Exception as e:
             # Log the error appropriately in a real application
             print(f"Error processing list context with json_to_html_list: {e}")
             # Fallback to a safe representation
             return html.escape(str(context))


    elif isinstance(context, dict):
        # For a dictionary, try to get 'texte' key, otherwise use string representation. Escape result.
        # This is a fallback; ideally, dicts should be part of lists handled above.
        text_content = context.get('texte', str(context))
        return html.escape(text_content)

    elif isinstance(context, str):
        # If the string contains newline characters, treat each line as a list item
        if "\n" in context:
            lignes = [ligne.strip() for ligne in context.splitlines() if ligne.strip()]
            # Escape each line before wrapping in <li>
            escaped_lignes = [f"<li>{html.escape(ligne)}</li>" for ligne in lignes]
            # Return as a <ul> list if there are any lines
            return f"<ul>{''.join(escaped_lignes)}</ul>" if escaped_lignes else ""
        else:
            # For a simple string (no newlines), just strip whitespace and escape it
            return html.escape(context.strip())

    # Handle other potential types (int, float, None, etc.) safely
    elif context is None:
        return "" # Return empty string for None
    else:
        # Convert any other type to string and escape it
        return html.escape(str(context))

def format_global_criteria(text: str) -> str:
    """
    Convertit une chaîne de critères (une ligne par critère) en une liste HTML.
    Par exemple:
        "Critère 1.\nCritère 2."
    devient:
        <ul>
            <li>Critère 1.</li>
            <li>Critère 2.</li>
        </ul>
    """
    # Supprimer les espaces et ignorer les lignes vides
    criteria_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not criteria_lines:
        return ""
    # Construit la liste HTML
    html_list = "<ul>\n" + "\n".join(f"\t<li>{line}</li>" for line in criteria_lines) + "\n</ul>"
    return html_list

@programme_bp.route('/confirm_import', methods=['POST'])
@login_required
def confirm_competencies_import():
    """
    Traite la confirmation depuis la page de révision et importe les compétences en base de données.
    Conversion du champ "contexte" du JSON en HTML dans le format souhaité.
    """
    form = ReviewImportConfirmForm()
    if form.validate_on_submit():
        programme_id = form.programme_id.data
        base_filename = form.base_filename.data
        import_structured = form.import_structured.data == 'true'

        # Récupération du programme cible
        try:
            programme = db.session.get(Programme, int(programme_id))
        except ValueError:
            flash("ID de programme invalide.", "danger")
            return redirect(url_for('main.index'))

        if not programme:
            flash("Programme cible non trouvé lors de la confirmation.", "danger")
            return redirect(url_for('main.index'))

        # Cas 1: Seule confirmation du texte OCR
        if not import_structured:
            flash(
                f"Texte OCR pour '{base_filename}' confirmé et associé au programme '{programme.nom}'. Aucune compétence importée.",
                "info"
            )
            return redirect(url_for('programme.view_programme', programme_id=programme.id))

        # Cas 2: Importation des compétences à partir du fichier JSON
        txt_output_dir = current_app.config.get('TXT_OUTPUT_DIR')
        competencies_file_path = os.path.join(txt_output_dir, f"{base_filename}_competences.json")
        competences_added_count = 0
        elements_added_count = 0
        competences_updated_count = 0

        try:
            logger.info(f"Début de l'importation depuis {competencies_file_path} pour le Programme ID {programme.id}")
            with open(competencies_file_path, 'r', encoding='utf-8') as f:
                competencies_data = json.load(f)

            competences_list = competencies_data.get('competences', [])
            if not isinstance(competences_list, list):
                raise ValueError("La clé 'competences' dans le JSON n'est pas une liste.")

            for comp_data in competences_list:
                if not isinstance(comp_data, dict):
                    logger.warning(f"Entrée compétence invalide (pas un dict): {comp_data}")
                    continue

                # Extraction des données en essayant plusieurs clés selon le JSON
                code = comp_data.get('code') or comp_data.get('Code')
                nom = comp_data.get('enonce') or comp_data.get('nom') or comp_data.get('Nom de la compétence')

                # Extraction et formatage du contexte
                raw_contexte = (comp_data.get('contexte_de_realisation') or 
                                comp_data.get('Contexte') or 
                                comp_data.get('Contexte de réalisation'))
                contexte = ""
                if raw_contexte is not None:
                    contexte = format_context(raw_contexte)

                # Extraction des critères de performance globaux
                critere_perf = (comp_data.get('criteria_de_performance') or 
                                comp_data.get('Critères de performance pour l’ensemble de la compétence') or 
                                comp_data.get('Critères de performance'))
                if critere_perf is not None:
                    # S'il s'agit d'une liste, on la convertit en chaîne avec un retour à la ligne
                    if isinstance(critere_perf, list):
                        critere_perf = "\n".join(critere_perf)
                    elif isinstance(critere_perf, str):
                        critere_perf = critere_perf.strip()
                    # On transforme la chaîne en liste HTML
                    critere_perf = format_global_criteria(critere_perf)

                if not code or not nom:
                    logger.warning(f"Compétence ignorée (code ou nom manquant): {comp_data}")
                    continue

                # Recherche d'une compétence existante dans la base
                existing_comp = Competence.query.filter_by(code=code, programme_id=programme.id).first()
                if existing_comp:
                    existing_comp.nom = nom
                    existing_comp.contexte_de_realisation = contexte
                    existing_comp.criteria_de_performance = critere_perf
                    db.session.add(existing_comp)
                    competences_updated_count += 1
                    logger.info(f"Compétence {code} mise à jour.")
                    comp_to_process = existing_comp
                else:
                    new_comp = Competence(
                        code=code,
                        nom=nom,
                        contexte_de_realisation=contexte,
                        criteria_de_performance=critere_perf,
                        programme_id=programme.id
                    )
                    db.session.add(new_comp)
                    db.session.flush()  # Pour obtenir l'ID si nécessaire pour les éléments
                    comp_to_process = new_comp
                    competences_added_count += 1
                    logger.info(f"Création de la compétence {code}.")

                # Traitement complet des éléments de compétence :
                # Récupération de la liste d'éléments depuis le JSON
                elements_list = comp_data.get('elements') or comp_data.get('Éléments') or []
                # Construction d'un dictionnaire associant chaque nom d'élément à ses données JSON (incluant les critères)
                json_elements = {}
                for elem_data in elements_list:
                    if isinstance(elem_data, str):
                        nom_elem = elem_data.strip()
                        json_elements[nom_elem] = {"criteres": None}
                    elif isinstance(elem_data, dict):
                        nom_elem = elem_data.get('element') or elem_data.get('nom')
                        if not nom_elem:
                            continue
                        json_elements[nom_elem] = {
                            "criteres": elem_data.get('criteres')
                        }
                
                # Synchronisation des éléments en base
                current_elements = comp_to_process.elements if hasattr(comp_to_process, 'elements') else []
                # Suppression des éléments en base qui ne sont plus présents dans le JSON
                for elem in list(current_elements):
                    if elem.nom not in json_elements:
                        db.session.delete(elem)
                        logger.debug(f"Suppression de l'élément '{elem.nom}' pour la compétence {code}.")

                # Mise à jour ou création des éléments et de leurs critères
                current_elements_names = {elem.nom for elem in comp_to_process.elements} if comp_to_process.elements else set()
                for nom_elem, elem_info in json_elements.items():
                    json_criteres = elem_info.get("criteres")
                    if nom_elem in current_elements_names:
                        # Mise à jour des critères de l'élément existant
                        elem = next(e for e in comp_to_process.elements if e.nom == nom_elem)
                        elem.criteria.clear()  # Suppression des critères existants
                        if json_criteres:
                            if isinstance(json_criteres, list):
                                for crit in json_criteres:
                                    if isinstance(crit, (dict, list)):
                                        crit_text = json_to_html_list(crit)
                                    else:
                                        crit_text = str(crit).strip()
                                    new_crit = ElementCompetenceCriteria(criteria=crit_text)
                                    elem.criteria.append(new_crit)
                            else:
                                if isinstance(json_criteres, (dict, list)):
                                    crit_text = json_to_html_list(json_criteres)
                                else:
                                    crit_text = str(json_criteres).strip()
                                new_crit = ElementCompetenceCriteria(criteria=crit_text)
                                elem.criteria.append(new_crit)
                        logger.debug(f"Mise à jour des critères de l'élément '{nom_elem}' pour la compétence {code}.")
                    else:
                        # Création d'un nouvel élément avec ses critères
                        new_elem = ElementCompetence(nom=nom_elem, competence_id=comp_to_process.id)
                        if json_criteres:
                            if isinstance(json_criteres, list):
                                for crit in json_criteres:
                                    if isinstance(crit, (dict, list)):
                                        crit_text = json_to_html_list(crit)
                                    else:
                                        crit_text = str(crit).strip()
                                    new_crit = ElementCompetenceCriteria(criteria=crit_text)
                                    new_elem.criteria.append(new_crit)
                            else:
                                if isinstance(json_criteres, (dict, list)):
                                    crit_text = json_to_html_list(json_criteres)
                                else:
                                    crit_text = str(json_criteres).strip()
                                new_crit = ElementCompetenceCriteria(criteria=crit_text)
                                new_elem.criteria.append(new_crit)
                        db.session.add(new_elem)
                        elements_added_count += 1
                        logger.debug(f"Création de l'élément '{nom_elem}' avec ses critères pour la compétence {code}.")

            db.session.commit()
            flash_msg = f"Import terminé pour le programme '{programme.nom}'."
            if competences_added_count:
                flash_msg += f" {competences_added_count} compétence(s) ajoutée(s)."
            if competences_updated_count:
                flash_msg += f" {competences_updated_count} compétence(s) mise(s) à jour."
            if elements_added_count:
                flash_msg += f" {elements_added_count} élément(s) ajouté(s)/supprimé(s)."
            if not (competences_added_count or competences_updated_count or elements_added_count):
                flash_msg += " Aucune donnée nouvelle à importer."
            flash(flash_msg, "success")
        except FileNotFoundError:
            db.session.rollback()
            flash(f"Fichier JSON '{os.path.basename(competencies_file_path)}' non trouvé lors de l'import.", "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'importation en base de données: {e}", "danger")
            logger.error(f"Erreur inattendue lors de l'importation pour le programme {programme.id}: {e}", exc_info=True)

        return redirect(url_for('programme.view_programme', programme_id=programme.id))
    else:
        flash("Erreur lors de la soumission du formulaire de confirmation. Veuillez réessayer.", "danger")
        try:
            prog_id = int(request.form.get('programme_id', 0))
            return redirect(url_for('programme.view_programme', programme_id=prog_id))
        except Exception:
            return redirect(url_for('main.index'))



@programme_bp.route('/<int:programme_id>')
@login_required
@ensure_profile_completed
def view_programme(programme_id):
    # Debug logging
    logger.debug(f"Accessing programme {programme_id}")
    logger.debug(f"User programmes: {[p.id for p in current_user.programmes]}")
    
    # Récupérer le programme
    programme = Programme.query.get(programme_id)
    if not programme:
        flash('Programme non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    # Vérifier si l'utilisateur a accès à ce programme
    if programme not in current_user.programmes and current_user.role != 'admin':
        flash("Vous n'avez pas accès à ce programme.", 'danger')
        return render_template('no_access.html')


    # Récupérer les compétences associées
    competences = Competence.query.filter_by(programme_id=programme_id).all()

    # Récupérer les fils conducteurs associés
    fil_conducteurs = FilConducteur.query.filter_by(programme_id=programme_id).all()

    # Récupérer les cours associés via la table d'association, triés par session
    # (chaque association CoursProgramme contient la session pour ce programme)
    # 'programme' a déjà été récupéré ci-dessus
    cours_assocs = sorted(programme.cours_assocs, key=lambda a: a.session)
    # Liste des objets Cours
    cours_liste = [assoc.cours for assoc in cours_assocs]
    # Mapping cours_id -> session spécifique à ce programme
    session_map = {assoc.cours.id: assoc.session for assoc in cours_assocs}


    # Regrouper les cours par session
    cours_par_session = defaultdict(list)
    
    # Pour chaque cours, récupérer les informations du dernier plan
    for cours in cours_liste:
        # Récupérer le dernier plan de cours
        dernier_plan = PlanDeCours.query\
            .filter_by(cours_id=cours.id)\
            .order_by(PlanDeCours.modified_at.desc())\
            .first()
        
        if dernier_plan:
            # Récupérer le username de l'utilisateur si modified_by_id existe
            modified_username = None
            if dernier_plan.modified_by_id:
                user = User.query.get(dernier_plan.modified_by_id)
                modified_username = user.username if user else None

            cours.dernier_plan = {
                'session': dernier_plan.session,
                'modified_at': dernier_plan.modified_at,
                'modified_by': modified_username
            }
        else:
            cours.dernier_plan = None
            
        # Grouper par session définie dans la relation CoursProgramme
        sess = session_map.get(cours.id)
        cours_par_session[sess].append(cours)

    # Récupérer préalables et co-requis pour chaque cours
    prerequisites = {}
    corequisites = {}
    for cours in cours_liste:  # Utiliser cours_liste au lieu de cours
        # Pré-requis
        preq = (db.session.query(Cours.nom, Cours.code, CoursPrealable.note_necessaire)
                .join(CoursPrealable, Cours.id == CoursPrealable.cours_prealable_id)
                .filter(CoursPrealable.cours_id == cours.id)
                .all())
        prerequisites[cours.id] = [(f"{p.code} - {p.nom}", p.note_necessaire) for p in preq]

        # Co-requis
        coreq = (db.session.query(Cours.nom, Cours.code)
                 .join(CoursCorequis, Cours.id == CoursCorequis.cours_corequis_id)
                 .filter(CoursCorequis.cours_id == cours.id)
                 .all())
        corequisites[cours.id] = [f"{cc.code} - {cc.nom}" for cc in coreq]

    # Récupérer les codes des compétences (développées ou atteintes) par cours
    competencies_codes = {}
    for c in cours_liste    :
        # Un SELECT DISTINCT sur c.code AS competence_code depuis la table Competence 
        # via ElementCompetence -> ElementCompetenceParCours
        comps = (db.session.query(Competence.code.label('competence_code'))
                 .join(ElementCompetence, Competence.id == ElementCompetence.competence_id)
                 .join(ElementCompetenceParCours, ElementCompetence.id == ElementCompetenceParCours.element_competence_id)
                 .filter(ElementCompetenceParCours.cours_id == c.id)
                 .filter(ElementCompetenceParCours.status.in_(['Développé significativement', 'Atteint']))
                 .distinct()
                 .all())
        competencies_codes[c.id] = [comp.competence_code for comp in comps]

    # Calcul des totaux
    total_heures_theorie = sum(c.heures_theorie for c in cours_liste)
    total_heures_laboratoire = sum(c.heures_laboratoire for c in cours_liste)
    total_heures_travail_maison = sum(c.heures_travail_maison for c in cours_liste)
    total_unites = sum(c.nombre_unites for c in cours_liste)

    # Créer des dictionnaires de formulaires de suppression
    delete_forms_competences = {comp.id: DeleteForm(prefix=f"competence-{comp.id}") for comp in competences}
    delete_forms_cours = {c.id: DeleteForm(prefix=f"cours-{c.id}") for c in cours_liste}

    # Récupérer tous les programmes (pour le sélecteur éventuel)
    programmes = current_user.programmes

    cours_plans_mapping = {}
    for cours in cours_liste:
        plans = PlanDeCours.query.filter_by(cours_id=cours.id).all()
        cours_plans_mapping[cours.id] = [p.to_dict() for p in plans]

    return render_template('view_programme.html',
                           programme=programme,
                           programmes=programmes,
                           competences=competences,
                           fil_conducteurs=fil_conducteurs,
                           cours_par_session=cours_par_session,
                           delete_forms_competences=delete_forms_competences,
                           delete_forms_cours=delete_forms_cours,
                           prerequisites=prerequisites,
                           corequisites=corequisites,
                           competencies_codes=competencies_codes,
                           total_heures_theorie=total_heures_theorie,
                           total_heures_laboratoire=total_heures_laboratoire,
                           total_heures_travail_maison=total_heures_travail_maison,
                           total_unites=total_unites,
                           cours_plans_mapping=cours_plans_mapping
                           )

@programme_bp.route('/competence/<int:competence_id>/edit', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def edit_competence(competence_id):
    competence = Competence.query.get_or_404(competence_id)
    programmes = Programme.query.all()
    form = CompetenceForm()
    form.programmes.choices = [(p.id, p.nom) for p in programmes]

    if form.validate_on_submit():
        try:
            # MAJ many-to-many
            competence.programmes = Programme.query.filter(
                Programme.id.in_(form.programmes.data)
            ).all()
            competence.code = form.code.data
            competence.nom  = form.nom.data
            competence.criteria_de_performance   = form.criteria_de_performance.data
            competence.contexte_de_realisation   = form.contexte_de_realisation.data

            db.session.commit()
            flash('Compétence mise à jour avec succès !', 'success')

            # redirige vers le premier programme associé
            first_id = competence.programmes[0].id if competence.programmes else None
            return redirect(url_for('programme.view_programme', programme_id=first_id))

        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour : {e}', 'danger')
            return redirect(url_for('programme.edit_competence', competence_id=competence_id))

    # --- GET ou validaton KO ---
    # pré-remplissage
    form.programmes.data             = [p.id for p in competence.programmes]
    form.code.data                   = competence.code or ''
    form.nom.data                    = competence.nom
    form.criteria_de_performance.data = competence.criteria_de_performance
    form.contexte_de_realisation.data = competence.contexte_de_realisation

    return render_template(
        'edit_competence.html',
        form=form,  # ou form=form
        competence=competence
    )


@programme_bp.route('/competence/<int:competence_id>/delete', methods=['POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def delete_competence(competence_id):
    # Formulaire de suppression
    delete_form = DeleteForm(prefix=f"competence-{competence_id}")

    if delete_form.validate_on_submit():
        competence = Competence.query.get(competence_id)
        if not competence:
            flash('Compétence non trouvée.', 'danger')
            return redirect(url_for('main.index'))

        programme_id = competence.programme_id
        try:
            db.session.delete(competence)
            db.session.commit()
            flash('Compétence supprimée avec succès!', 'success')
        except Exception as e:
            flash(f'Erreur lors de la suppression de la compétence : {e}', 'danger')

        return redirect(url_for('programme.view_programme', programme_id=programme_id))
    else:
        flash('Formulaire de suppression invalide.', 'danger')
        return redirect(url_for('main.index'))


@programme_bp.route('/competence/code/<string:competence_code>')
@role_required('admin')
@ensure_profile_completed
def view_competence_by_code(competence_code):
    # Récupérer la compétence par son code
    competence = Competence.query.filter_by(code=competence_code).first()

    if not competence:
        flash('Compétence non trouvée.', 'danger')
        return redirect(url_for('main.index'))

    # Rediriger vers la route existante avec competence_id
    return redirect(url_for('programme.view_competence', competence_id=competence.id))


@programme_bp.route('/competence/<int:competence_id>')
@login_required
@ensure_profile_completed
def view_competence(competence_id):
    # Récupération de la compétence + programme lié
    competence = Competence.query.get(competence_id)
    if not competence:
        flash('Compétence non trouvée.', 'danger')
        return redirect(url_for('main.index'))

    # Nettoyage HTML
    allowed_tags = [
        'ul', 'ol', 'li', 'strong', 'em', 'p', 'br', 'a',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
    ]
    allowed_attributes = {
        'a': ['href', 'title', 'target']
    }

    criteria_content = competence.criteria_de_performance or ""
    context_content = competence.contexte_de_realisation or ""

    # Assurer que ce sont des chaînes
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

    # Récupérer les éléments de compétence et leurs critères
    # Dans le modèle SQLAlchemy, un Competence possède un relationship 'elements'
    # et chaque ElementCompetence possède un relationship 'criteria'
    elements_comp = competence.elements  # liste de ElementCompetence

    # Organiser les critères par élément de compétence
    elements_dict = {}
    for element in elements_comp:
        elements_dict[element.id] = {
            'nom': element.nom,
            'criteres': [c.criteria for c in element.criteria]
        }

    # Instancier le formulaire de suppression
    delete_form = DeleteForm(prefix=f"competence-{competence.id}")

    return render_template(
        'view_competence.html',
        competence=competence,
        criteria_html=criteria_html,
        context_html=context_html,
        elements_competence=elements_dict,
        delete_form=delete_form
    )

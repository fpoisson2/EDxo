# programme.py
import logging
from collections import defaultdict

import bleach
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app

import os

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
    ElementCompetenceParCours,
    PlanDeCours
)
from utils.decorator import role_required, ensure_profile_completed

# Utilities
# Example of another blueprint import (unused here, just as in your snippet)
logger = logging.getLogger(__name__)

programme_bp = Blueprint('programme', __name__, url_prefix='/programme')


# === ROUTE DE RÉVISION (DÉCLENCHÉE PAR POST DEPUIS L'ASSOCIATION) ===
@programme_bp.route('/review_import', methods=['POST']) # Accepte seulement POST
@login_required
def review_competencies_import():
    """
    Reçoit l'association (programme_id, base_filename) et affiche
    la page de révision côte à côte (OCR / Compétences JSON).
    """
    programme_id = request.form.get('programme_id')
    base_filename = request.form.get('base_filename')

    if not programme_id or not base_filename:
        flash("Informations manquantes (programme ou devis) pour démarrer la révision.", "danger")
        return redirect(url_for('ocr.show_trigger_page')) # Rediriger vers une page appropriée

    # Valider et convertir programme_id
    try:
        programme_id = int(programme_id)
    except ValueError:
         flash("ID de programme invalide.", "danger")
         return redirect(url_for('ocr.show_trigger_page'))

    # Récupérer le programme sélectionné
    programme = db.session.get(Programme, programme_id)
    if not programme:
        # Utiliser abort(404) si l'ID est valide mais le programme n'existe pas
        flash(f"Programme avec ID {programme_id} non trouvé.", "danger")
        abort(404) # Ou rediriger avec un flash

    # Construire les chemins des fichiers
    txt_output_dir = current_app.config.get('TXT_OUTPUT_DIR', 'src/txt_outputs')
    ocr_file_path = os.path.join(txt_output_dir, f"{base_filename}_ocr.md")
    competencies_file_path = os.path.join(txt_output_dir, f"{base_filename}_competences.json")

    # Lire les contenus des fichiers
    ocr_text = ""
    competencies_data = None
    has_competencies_file = False
    error_loading_files = False

    try:
        with open(ocr_file_path, 'r', encoding='utf-8') as f:
            ocr_text = f.read()
    except FileNotFoundError:
        logger.warning(f"Fichier Markdown introuvable pour révision: {ocr_file_path}")
        flash(f"Fichier Markdown ({os.path.basename(ocr_file_path)}) introuvable.", "warning")
        error_loading_files = True
    except Exception as e:
        logger.error(f"Erreur lecture Markdown {ocr_file_path}: {e}", exc_info=True)
        flash(f"Erreur lors de la lecture du fichier Markdown: {e}", "danger")
        error_loading_files = True

    try:
        with open(competencies_file_path, 'r', encoding='utf-8') as f:
            competencies_data = json.load(f)
            if not isinstance(competencies_data, dict) or 'competences' not in competencies_data:
                raise ValueError("Structure JSON invalide: clé 'competences' manquante.")
            has_competencies_file = True
            logger.info(f"Fichier JSON chargé pour révision: {competencies_file_path}")
    except FileNotFoundError:
        logger.info(f"Fichier JSON de compétences introuvable pour révision: {competencies_file_path}")
        flash("Fichier JSON des compétences structurées non trouvé. Seul le texte OCR est affiché pour information.", "info")
        has_competencies_file = False
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Erreur lecture/parsing JSON {competencies_file_path}: {e}", exc_info=True)
        flash(f"Erreur lors de la lecture ou du parsing du fichier JSON des compétences: {e}", "warning")
        has_competencies_file = False
        error_loading_files = True

    # Si aucun fichier OCR n'a été trouvé, c'est problématique pour la révision
    if not ocr_text and error_loading_files:
         flash("Impossible de charger le fichier OCR principal pour la révision.", "danger")
         # Rediriger vers la page d'association ou une autre page d'erreur
         return redirect(url_for('ocr.associate_devis', base_filename=base_filename))

    # --- Instancier et pré-remplir le formulaire ---
    form = ReviewImportConfirmForm()
    form.programme_id.data = programme_id
    form.base_filename.data = base_filename
    # Définir la valeur de import_structured basé sur si on a trouvé des données JSON valides
    form.import_structured.data = 'true' if has_competencies_file and competencies_data else 'false'
    # --- Fin Instanciation Formulaire ---

    # Rendre le template de révision
    # Assurez-vous que le chemin du template est correct ('programme/...' ou 'ocr/...')
    return render_template('programme/review_import.html',
                           programme=programme,
                           ocr_text=ocr_text,
                           competencies_data=competencies_data,
                           has_competencies_file=has_competencies_file,
                           base_filename=base_filename,
                           form=form) # Passer base_filename


@programme_bp.route('/confirm_import', methods=['POST'])
@login_required
def confirm_competencies_import():
    """Traite la confirmation depuis la page de révision et importe les compétences en DB."""
    form = ReviewImportConfirmForm() # Instancier pour valider et récupérer les données

    # form.validate_on_submit() gère la validation CSRF et les validateurs définis (DataRequired etc.)
    if form.validate_on_submit():
        programme_id = form.programme_id.data # WTForms retourne généralement str
        base_filename = form.base_filename.data
        # Convertir la valeur du champ caché en booléen
        import_structured = form.import_structured.data == 'true'

        # Récupérer le programme cible
        try:
            programme = db.session.get(Programme, int(programme_id))
            if not programme:
                 flash("Programme cible non trouvé lors de la confirmation.", "danger")
                 # Rediriger vers une page sûre, ex: liste des programmes ou index
                 return redirect(url_for('main.index'))
        except ValueError:
             flash("ID de programme invalide fourni.", "danger")
             return redirect(url_for('main.index'))

        # Cas 1 : Confirmation simple du texte OCR (pas d'import structuré)
        if not import_structured:
            flash(f"Texte OCR pour '{base_filename}' confirmé et associé au programme '{programme.nom}'. Aucune compétence structurée importée.", "info")
            # Ici, on pourrait ajouter une logique pour marquer ce devis comme 'révisé'
            # par exemple, en stockant base_filename quelque part lié au programme,
            # ou en déplaçant/supprimant les fichiers traités. Pour l'instant, on redirige.
            return redirect(url_for('.view_programme', programme_id=programme.id))

        # Cas 2 : Importation des compétences structurées depuis le fichier JSON
        txt_output_dir = current_app.config.get('TXT_OUTPUT_DIR', 'src/txt_outputs')
        competencies_file_path = os.path.join(txt_output_dir, f"{base_filename}_competences.json")
        competences_added_count = 0
        elements_added_count = 0
        competences_updated_count = 0

        try:
            logger.info(f"Début de l'importation depuis {competencies_file_path} pour Programme ID {programme.id}")
            with open(competencies_file_path, 'r', encoding='utf-8') as f:
                competencies_data = json.load(f)

            competences_list = competencies_data.get('competences', [])
            if not isinstance(competences_list, list):
                 raise ValueError("La clé 'competences' dans le JSON n'est pas une liste.")

            # Itérer sur les compétences du fichier JSON
            for comp_data in competences_list:
                if not isinstance(comp_data, dict):
                    logger.warning(f"Import pour {programme.id}: Entrée compétence invalide (pas dict): {comp_data}")
                    continue

                # Extraire les données de la compétence (Adapter les clés à votre JSON)
                code = comp_data.get('code') or comp_data.get('Code')
                nom_ou_enonce = comp_data.get('enonce') or comp_data.get('nom') or comp_data.get('Nom de la compétence')
                contexte = comp_data.get('contexte_de_realisation') # Peut être str ou dict/liste selon votre schéma
                critere_perf_global = comp_data.get('criteria_de_performance') or comp_data.get('Critères de performance pour l’ensemble de la compétence') # Peut être str ou liste

                if not code or not nom_ou_enonce:
                    logger.warning(f"Import {programme.id}: Compétence ignorée (code/nom manquant): {comp_data}")
                    continue

                # Convertir contexte et critères en texte simple si nécessaire pour le modèle actuel
                # (Cette partie dépend fortement de la structure de votre modèle Competence)
                if isinstance(contexte, (dict, list)): contexte = json.dumps(contexte, ensure_ascii=False) # Exemple: stocker comme JSON string
                if isinstance(critere_perf_global, list): critere_perf_global = "\n".join(critere_perf_global) # Exemple: stocker comme texte multiligne

                # Chercher/Mettre à jour ou Créer la Compétence
                existing_comp = Competence.query.filter_by(code=code, programme_id=programme.id).first()
                comp_to_process = None # Garder une référence à la compétence traitée (existante ou nouvelle)

                if existing_comp:
                    comp_to_process = existing_comp
                    updated = False
                    if existing_comp.nom != nom_ou_enonce: existing_comp.nom = nom_ou_enonce; updated = True
                    if contexte is not None and existing_comp.contexte_de_realisation != contexte: existing_comp.contexte_de_realisation = contexte; updated = True
                    if critere_perf_global is not None and existing_comp.criteria_de_performance != critere_perf_global: existing_comp.criteria_de_performance = critere_perf_global; updated = True
                    if updated:
                        db.session.add(existing_comp)
                        competences_updated_count += 1
                        logger.info(f"Import {programme.id}: Compétence {code} mise à jour.")
                else:
                    logger.info(f"Import {programme.id}: Création compétence {code}.")
                    new_comp = Competence(
                        code=code, nom=nom_ou_enonce, contexte_de_realisation=contexte,
                        criteria_de_performance=critere_perf_global, programme_id=programme.id
                    )
                    db.session.add(new_comp)
                    # Important: Flush pour obtenir l'ID si ElementCompetence en dépend immédiatement
                    db.session.flush()
                    comp_to_process = new_comp
                    competences_added_count += 1

                # Traiter les Éléments de Compétence (Adapter à VOS modèles et structure JSON)
                elements_list = comp_data.get('elements') or comp_data.get('Éléments') or []
                if isinstance(elements_list, list) and comp_to_process and hasattr(comp_to_process, 'elements'): # Vérifier si la relation 'elements' existe sur le modèle Competence
                    for elem_data in elements_list:
                        elem_nom = None
                        # Adapter l'extraction du nom de l'élément selon votre JSON
                        if isinstance(elem_data, str): elem_nom = elem_data.strip()
                        elif isinstance(elem_data, dict): elem_nom = elem_data.get('element') or elem_data.get('nom')

                        if elem_nom:
                            # Vérifier si l'élément existe déjà pour CETTE compétence
                            existing_elem = ElementCompetence.query.filter_by(competence_id=comp_to_process.id, nom=elem_nom).first()
                            if not existing_elem:
                                new_elem = ElementCompetence(nom=elem_nom, competence_id=comp_to_process.id)
                                db.session.add(new_elem)
                                elements_added_count += 1
                                logger.debug(f"Import {programme.id}: Ajout Élément '{elem_nom[:30]}...' pour Comp {code}")
                                # --- Logique pour les critères de l'élément (si applicable) ---
                                # Si vos 'elem_data' contiennent des critères et vous avez un modèle ElementCompetenceCriteria:
                                # criteres_specifiques = elem_data.get('criteres') # Liste de strings?
                                # if criteres_specifiques and isinstance(criteres_specifiques, list):
                                #      db.session.flush() # Obtenir ID de new_elem
                                #      for crit_str in criteres_specifiques:
                                #           existing_crit = ElementCompetenceCriteria.query.filter_by(element_competence_id=new_elem.id, criteria=crit_str).first()
                                #           if not existing_crit:
                                #                new_crit = ElementCompetenceCriteria(criteria=crit_str, element_competence_id=new_elem.id)
                                #                db.session.add(new_crit)
                                # -------------------------------------------------------------

            # Commit final après la boucle si tout s'est bien passé (ou gérer par compétence?)
            db.session.commit()
            # Construire message de succès
            flash_msg = f"Importation terminée pour le programme '{programme.nom}'."
            if competences_added_count > 0: flash_msg += f" {competences_added_count} compétence(s) ajoutée(s)."
            if competences_updated_count > 0: flash_msg += f" {competences_updated_count} compétence(s) mise(s) à jour."
            if elements_added_count > 0: flash_msg += f" {elements_added_count} élément(s) ajouté(s)."
            if competences_added_count == 0 and competences_updated_count == 0 and elements_added_count == 0:
                 flash_msg += " Aucune nouvelle donnée à importer ou mettre à jour."
            flash(flash_msg, "success")

        except FileNotFoundError:
            flash(f"Fichier JSON '{os.path.basename(competencies_file_path)}' non trouvé lors de l'import.", "danger")
            db.session.rollback()
        except (json.JSONDecodeError, ValueError, KeyError, AttributeError) as e: # Ajouter AttributeError
            flash(f"Erreur de lecture, structure JSON/Modèle invalide ({os.path.basename(competencies_file_path)}): {e}", "danger")
            db.session.rollback()
            logger.error(f"Erreur JSON/Structure/Modèle import {programme_id}, fichier {base_filename}: {e}", exc_info=True)
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur inattendue lors de l'importation en base de données: {e}", "danger")
            logger.error(f"Erreur DB/Inattendue import {programme_id}, fichier {base_filename}: {e}", exc_info=True)

        # Rediriger vers la vue programme après la tentative d'import
        return redirect(url_for('.view_programme', programme_id=programme.id))

    else:
        # Cas où form.validate_on_submit() échoue (CSRF invalide, etc.)
        flash("Erreur lors de la soumission du formulaire de confirmation (validation échouée). Veuillez réessayer.", "danger")
        # Essayer de récupérer l'ID programme pour rediriger intelligemment
        programme_id_from_form = request.form.get('programme_id')
        base_filename_from_form = request.form.get('base_filename')
        # On ne peut pas facilement retourner à la page de révision sans re-lire les fichiers
        # Le plus simple est de retourner à la vue programme ou à l'association
        try:
             # Rediriger vers la vue programme si possible
             return redirect(url_for('.view_programme', programme_id=int(programme_id_from_form)))
        except:
             # Ou rediriger vers l'étape d'association si on a le base_filename
             if base_filename_from_form:
                  return redirect(url_for('ocr.associate_devis', base_filename=base_filename_from_form))
             else:
                  # Fallback ultime
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

    # Récupérer les cours associés au programme + infos fil conducteur
    # (Dans ce modèle, FilConducteur n'est pas forcément relié par relationship, 
    # on utilise donc l’id fil_conducteur_id directement)
    cours_liste = (Cours.query
             .filter_by(programme_id=programme_id)
             .order_by(Cours.session.asc())
             .all())

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
            
        cours_par_session[cours.session].append(cours)

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
@role_required('admin')
@ensure_profile_completed
def edit_competence(competence_id):
    form = CompetenceForm()
    # Récupérer la compétence
    competence = Competence.query.get(competence_id)
    # Récupérer la liste des programmes
    programmes = Programme.query.all()

    if competence is None:
        flash('Compétence non trouvée.', 'danger')
        return redirect(url_for('main.index'))

    # Peupler le choix de programme
    form.programme.choices = [(p.id, p.nom) for p in programmes]

    if request.method == 'POST' and form.validate_on_submit():
        try:
            competence.programme_id = form.programme.data
            competence.code = form.code.data
            competence.nom = form.nom.data
            competence.criteria_de_performance = form.criteria_de_performance.data
            competence.contexte_de_realisation = form.contexte_de_realisation.data

            db.session.commit()
            flash('Compétence mise à jour avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=competence.programme_id))
        except Exception as e:
            flash(f'Erreur lors de la mise à jour de la compétence : {e}', 'danger')
            return redirect(url_for('programme.edit_competence', competence_id=competence_id))
    else:
        # Pré-remplir le formulaire
        form.programme.data = competence.programme_id
        form.code.data = competence.code if competence.code else ''
        form.nom.data = competence.nom
        form.criteria_de_performance.data = competence.criteria_de_performance
        form.contexte_de_realisation.data = competence.contexte_de_realisation

    return render_template('edit_competence.html', form=form, competence=competence)


@programme_bp.route('/competence/<int:competence_id>/delete', methods=['POST'])
@role_required('admin')
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

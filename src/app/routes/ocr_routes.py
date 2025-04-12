# EDxo/src/app/routes/ocr_routes.py

import logging
from flask import (
    Blueprint, request, redirect, url_for, jsonify,
    render_template, current_app, flash
)
from flask_login import login_required

# --- Imports Projet ---
from extensions import csrf
from app.forms import OcrProgrammeSelectionForm
try:
    from ocr_processing import web_utils
    from config import constants
    # NOTE: L'import de 'process_ocr_task' est déplacé plus bas
except ImportError as e:
    logging.error(f"Erreur d'importation critique dans ocr_routes.py: {e}. Vérifiez la structure de votre projet et les chemins d'importation.")
    class web_utils: # Placeholder
        @staticmethod
        def get_page_content(url): return None
        @staticmethod
        def extract_secteur_links(html, url): return []
        @staticmethod
        def extract_pdf_links_from_subpage(html, url): return []
    class constants: # Placeholder
        MAIN_PAGE = "URL_PAR_DEFAUT_SI_IMPORT_ECHOUE"
# --- Fin Imports Projet ---

ocr_bp = Blueprint('ocr', __name__, url_prefix='/ocr')
logger = logging.getLogger(__name__)

# === Route pour afficher la page de déclenchement ===
@ocr_bp.route('/trigger')
@login_required
def show_trigger_page():
    """Affiche la page avec les sélecteurs de secteur et programme."""
    form = OcrProgrammeSelectionForm()
    sectors = []
    try:
        # Utiliser l'URL MISE À JOUR depuis constants.py (si l'import a réussi)
        logger.info(f"Récupération des secteurs depuis : {constants.MAIN_PAGE}")
        main_html = web_utils.get_page_content(constants.MAIN_PAGE)
        if main_html:
            sectors = web_utils.extract_secteur_links(main_html, constants.MAIN_PAGE)
            form.secteur_url.choices = [('', '-- Choisir un secteur --')] + [(url, name) for name, url in sectors]
            logger.info(f"{len(sectors)} secteurs trouvés et ajoutés au formulaire.")
        else:
            logger.warning("Impossible de récupérer le contenu de la page principale pour les secteurs.")
            flash("Impossible de récupérer la liste des secteurs depuis le site.", "danger")
            form.secteur_url.choices = [('', '-- Erreur chargement secteurs --')]
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des secteurs: {e}", exc_info=True)
        flash(f"Erreur lors de la récupération des secteurs: {e}", "danger")
        form.secteur_url.choices = [('', '-- Erreur chargement secteurs --')]
    form.programme_url.choices = [('', '-- Choisir un programme --')]
    return render_template('ocr/trigger_page.html', form=form)

# === Nouvelle route API pour obtenir les programmes d'un secteur ===
@ocr_bp.route('/get_programmes', methods=['GET'])
@login_required
def get_programmes_for_secteur():
    """Endpoint API pour récupérer les programmes (PDFs) d'un secteur."""
    secteur_url = request.args.get('secteur_url')
    if not secteur_url:
        logger.warning("Requête GET /get_programmes sans 'secteur_url'.")
        return jsonify({'error': 'URL du secteur manquante'}), 400
    programmes = []
    try:
        logger.info(f"Récupération du contenu pour le secteur : {secteur_url}")
        secteur_html = web_utils.get_page_content(secteur_url)
        if secteur_html:
            pdf_links = web_utils.extract_pdf_links_from_subpage(secteur_html, secteur_url)
            programmes = [{'url': url, 'title': title} for title, url in pdf_links]
            logger.info(f"{len(programmes)} programmes trouvés pour le secteur.")
        else:
             logger.warning(f"Impossible de récupérer le contenu pour l'URL du secteur : {secteur_url}")
             return jsonify([])
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des programmes pour {secteur_url}: {e}", exc_info=True)
        return jsonify({'error': f'Erreur serveur: {e}'}), 500
    return jsonify(programmes)

# === Route pour DÉMARRER le traitement ===
@ocr_bp.route('/start', methods=['POST'])
@login_required
def start_ocr_processing():
    """
    Démarre la tâche Celery pour traiter le PDF du programme sélectionné.
    """
    form = OcrProgrammeSelectionForm()

    # --- Re-Peuplement des Choix AVANT validation ---
    try:
        main_html = web_utils.get_page_content(constants.MAIN_PAGE)
        if main_html:
            sectors = web_utils.extract_secteur_links(main_html, constants.MAIN_PAGE)
            form.secteur_url.choices = [('', '-- Choisir un secteur --')] + [(url, name) for name, url in sectors]
        else: form.secteur_url.choices = [('', '-- Erreur chargement secteurs --')]
    except: form.secteur_url.choices = [('', '-- Erreur chargement secteurs --')]

    submitted_secteur_url = request.form.get('secteur_url')
    programme_choices_for_this_request = [('', '-- Choisir un programme --')]
    if submitted_secteur_url:
         try:
            secteur_html = web_utils.get_page_content(submitted_secteur_url)
            if secteur_html:
                pdf_links = web_utils.extract_pdf_links_from_subpage(secteur_html, submitted_secteur_url)
                programme_choices_for_this_request.extend([(url, title) for title, url in pdf_links])
            else: programme_choices_for_this_request = [('', '-- Erreur chargement programmes --')]
         except: programme_choices_for_this_request = [('', '-- Erreur chargement programmes --')]
    else: programme_choices_for_this_request = [('', '-- Choisir un secteur d\'abord --')]
    form.programme_url.choices = programme_choices_for_this_request
    # --- Fin Re-Peuplement ---

    if form.validate_on_submit():
        programme_url = form.programme_url.data
        selected_programme_text = dict(form.programme_url.choices).get(programme_url, '')
        pdf_title = form.pdf_title.data.strip() or selected_programme_text or 'PDF Programme Inconnu'

        try:
            # !!! Importation de la tâche déplacée ici !!!
            from app.tasks import process_ocr_task
            task = process_ocr_task.delay(pdf_source=programme_url, pdf_title=pdf_title)
            logger.info(f"Tâche Celery démarrée pour OCR: {task.id} pour l'URL: {programme_url} (Titre: {pdf_title})")
            return redirect(url_for('ocr.task_status_page', task_id=task.id))
        except NameError: # Si process_ocr_task n'a pas pu être importé (à cause de la circulaire)
             logger.error("Échec de l'importation de la tâche Celery 'process_ocr_task'. Vérifiez les dépendances circulaires.", exc_info=True)
             flash("Erreur interne du serveur lors du lancement de la tâche.", "danger")
             return render_template('ocr/trigger_page.html', form=form)
        except Exception as e:
            logger.error(f"Erreur lors du lancement de la tâche Celery OCR: {e}", exc_info=True)
            flash("Une erreur s'est produite lors du lancement du traitement.", "danger")
            return render_template('ocr/trigger_page.html', form=form)
    else:
        flash("Erreur de validation. Veuillez sélectionner un secteur et un programme.", "danger")
        logger.warning(f"Échec de validation du formulaire OCR : {form.errors}")
        return render_template('ocr/trigger_page.html', form=form)


# --- Route pour VÉRIFIER LE STATUT de la tâche ---
@ocr_bp.route('/status/<task_id>')
@login_required
def task_status(task_id):
    """Vérifie et retourne le statut de la tâche Celery."""
    # !!! Importation de la tâche déplacée ici !!!
    from app.tasks import process_ocr_task
    task = process_ocr_task.AsyncResult(task_id)
    # ... (le reste de la fonction est inchangé) ...
    response_data = {'task_id': task_id, 'state': task.state, 'info': {}}
    if task.state == 'PENDING':
        response_data['info'] = {'status': 'En attente...', 'message': 'La tâche est en file d\'attente ou n\'existe pas.'}
    elif task.state == 'PROGRESS':
        response_data['info'] = task.info
    elif task.state == 'SUCCESS':
        response_data['info'] = task.info
        response_data['result_url'] = url_for('ocr.task_result', task_id=task_id)
    elif task.state == 'FAILURE':
        if isinstance(task.info, dict) and 'error' in task.info:
            response_data['info'] = task.info
        else:
            response_data['info'] = {'error': str(task.info)}
    else:
        response_data['info'] = {'status': task.state}
    return jsonify(response_data)


# --- Route pour AFFICHER LES RÉSULTATS finaux ---
@ocr_bp.route('/result/<task_id>')
@login_required
def task_result(task_id):
    """Affiche les résultats finaux de la tâche."""
    # !!! Importation de la tâche déplacée ici !!!
    from app.tasks import process_ocr_task
    task = process_ocr_task.AsyncResult(task_id)
    # ... (le reste de la fonction est inchangé) ...
    results = None
    if task.state == 'SUCCESS':
        results = task.result
    elif task.state == 'FAILURE':
        if isinstance(task.info, dict):
            results = task.info
            flash(f"Le traitement a échoué: {results.get('error', 'Erreur inconnue')}", "danger")
        else:
            flash(f"Le traitement a échoué: {str(task.info)}", "danger")
            results = {"error": str(task.info), "task_id": task_id, "final_status": "FAILURE"}
    else:
        flash("Le traitement n'est pas encore terminé.", "info")
        return redirect(url_for('ocr.task_status_page', task_id=task_id))
    return render_template('ocr/results.html', results=results)

# --- Route pour afficher la page de SUIVI DE STATUT ---
@ocr_bp.route('/status-page/<task_id>')
@login_required
def task_status_page(task_id):
    """Affiche la page qui suivra la progression de la tâche."""
    return render_template('ocr/processing_page.html', task_id=task_id)
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
from app.forms import AssociateDevisForm
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

from flask_login import login_required, current_user

from app.models import (
    Programme
)

from celery_app import celery
# --- Fin Imports Projet ---

ocr_bp = Blueprint('ocr', __name__, url_prefix='/ocr')
logger = logging.getLogger(__name__)


@ocr_bp.route('/associate/<path:base_filename>')
@login_required
def associate_devis(base_filename):
    if not base_filename:
        flash("Nom de fichier de base manquant.", "danger")
        return redirect(url_for('ocr.show_trigger_page'))

    # Filtrer les programmes selon le département de l'utilisateur, etc.
    programmes_query = Programme.query
    if hasattr(current_user, 'department_id') and current_user.department_id:
         programmes_query = programmes_query.filter(Programme.department_id == current_user.department_id)
    programmes = programmes_query.order_by(Programme.nom).all()

    if not programmes:
        flash("Aucun programme trouvé dans la base de données auquel associer ce devis.", "warning")

    # Instancier le formulaire et pré-remplir le champ caché
    form = AssociateDevisForm()
    form.base_filename.data = base_filename
    # Construire la liste des choix sous la forme (id, "Nom (code)") par exemple
    form.programme_id.choices = [
        (p.id, p.nom)
        for p in programmes
    ]
    # Si vous souhaitez également afficher un titre ou autre info :
    devis_title_display = base_filename  # À améliorer si besoin

    return render_template(
        'ocr/associate_devis.html',
        form=form,
        devis_title=devis_title_display
    )


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
            logger.info(f"Tentative d'envoi de la tâche 'app.tasks.process_ocr_task' via celery.send_task")
            logger.info(f"Configuration Celery utilisée: BROKER='{celery.conf.broker_url}', BACKEND='{celery.conf.result_backend}'")

            task = celery.send_task(
                'app.tasks.process_ocr_task', # Nom de la tâche à exécuter
                args=[programme_url, pdf_title],  # Arguments positionnels de la tâche
                kwargs={}                    # Arguments nommés (aucun dans ce cas)
            )
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
    try:
        # Utiliser l'instance 'celery' importée pour obtenir le résultat
        task = celery.AsyncResult(task_id)

        response_data = {'task_id': task_id, 'state': task.state, 'info': {}}

        # Construire la réponse basée sur l'état
        if task.state == 'PENDING':
            response_data['info'] = {'status': 'En attente...', 'message': 'La tâche est en file d\'attente ou n\'existe pas.'}
        elif task.state == 'PROGRESS':
            response_data['info'] = task.info if task.info else {'status': 'En cours...'}
        elif task.state == 'SUCCESS' or task.state.startswith('COMPLETED_WITH'): # Inclure succès partiel
             # task.info contient la valeur retournée par la tâche (le dict 'results')
             response_data['info'] = task.info if task.info else {} # Utiliser task.info
             response_data['result_url'] = url_for('ocr.task_result', task_id=task_id)
        elif task.state == 'FAILURE':
            info = task.info # Contient l'exception
            error_detail = str(info)
            if isinstance(info, dict) and 'error' in info:
                error_detail = info['error']
            elif isinstance(info, Exception):
                 error_detail = f"{type(info).__name__}: {info}"
            response_data['info'] = {'error': error_detail, 'status': 'Échec'}
            # Donner l'URL des résultats même en cas d'échec pour voir le message
            response_data['result_url'] = url_for('ocr.task_result', task_id=task_id)
        else: # Autres états (REVOKED, RETRY, etc.)
            response_data['info'] = {'status': task.state}

        return jsonify(response_data)

    except Exception as e:
        # Capturer les erreurs potentielles lors de l'accès à Celery/Redis
        logger.error(f"Erreur dans task_status pour {task_id}: {e}", exc_info=True)
        # Retourner une réponse d'erreur JSON standardisée
        return jsonify({'task_id': task_id, 'state': 'ERROR', 'info': {'error': f'Erreur interne serveur: {e}'}}), 500



@ocr_bp.route('/result/<task_id>')
@login_required
def task_result(task_id):
    """Affiche les résultats finaux de la tâche."""
    try:
        # Utiliser l'instance 'celery' importée
        task = celery.AsyncResult(task_id)

        results = None
        # Vérifier les états de succès ou d'échec pour obtenir les résultats/infos
        if task.state == 'SUCCESS' or task.state.startswith('COMPLETED_WITH'):
            results = task.result # task.result contient le dict retourné par la tâche
            if not isinstance(results, dict): # Vérification de sécurité
                 logger.warning(f"Résultat inattendu (pas dict) pour tâche {task_id} réussie: {results}")
                 results = {"task_id": task_id, "final_status": task.state, "raw_result": str(results)}
            # Assurer que task_id et final_status sont là pour le template
            results['task_id'] = results.get('task_id', task_id)
            results['final_status'] = results.get('final_status', task.state)

        elif task.state == 'FAILURE':
            error_info = task.result # task.result contient l'exception
            error_detail = str(error_info)
            if isinstance(error_info, Exception):
                 error_detail = f"{type(error_info).__name__}: {error_info}"
            results = {
                "task_id": task_id, "error": error_detail, "final_status": "FAILURE",
                "pdf_title": "Inconnu (Échec)", "pdf_source": "Inconnue (Échec)"
            }
            flash(f"Le traitement a échoué: {error_detail}", "danger")

        else: # PENDING, PROGRESS, etc.
            flash("Le traitement n'est pas encore terminé ou dans un état inattendu.", "info")
            return redirect(url_for('ocr.task_status_page', task_id=task_id))

        return render_template('ocr/results.html', results=results)

    except Exception as e:
        logger.error(f"Erreur dans task_result pour {task_id}: {e}", exc_info=True)
        flash(f"Erreur lors de la récupération des résultats de la tâche: {e}", "danger")
        return redirect(url_for('ocr.task_status_page', task_id=task_id)) # Rediriger vers la page de statut


# --- Route pour afficher la page de SUIVI DE STATUT ---
@ocr_bp.route('/status-page/<task_id>')
@login_required
def task_status_page(task_id):
    """Affiche la page qui suivra la progression de la tâche."""
    return render_template('ocr/processing_page.html', task_id=task_id)
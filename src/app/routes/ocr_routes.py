# ocr_routes.py
import logging
from flask import Blueprint, request, redirect, url_for, jsonify, render_template, current_app, flash
from flask_login import login_required
from extensions import csrf
from app.forms import OcrTriggerForm  # <-- Assurez-vous d'importer le formulaire

# Créez le Blueprint
ocr_bp = Blueprint('ocr', __name__, url_prefix='/ocr')

logger = logging.getLogger(__name__)

# --- Route pour afficher la page de déclenchement (modifiée pour passer le formulaire) ---
@ocr_bp.route('/trigger')
@login_required
def show_trigger_page():
    """Affiche la page avec le formulaire pour entrer une URL."""
    form = OcrTriggerForm() # <-- Instancier le formulaire ici
    # Ce template doit maintenant utiliser 'form' pour rendre les champs et le CSRF token
    return render_template('ocr/trigger_page.html', form=form) # <-- Passer le formulaire

# --- Route pour DÉMARRER le traitement (corrigée) ---
@ocr_bp.route('/start', methods=['POST'])
@login_required
def start_ocr_processing():
    """
    Démarre la tâche Celery pour traiter un PDF.
    Utilise WTForms pour la validation et la récupération des données.
    """
    form = OcrTriggerForm() # <-- Instancier le formulaire

    # validate_on_submit() vérifie si la requête est POST et si les données sont valides (y compris le CSRF token)
    if form.validate_on_submit():
        pdf_url = form.pdf_url.data
        pdf_title = form.pdf_title.data or 'PDF Inconnu' # Utilise la valeur par défaut si vide

        try:
            # Lance la tâche Celery en arrière-plan
            from app.tasks import process_ocr_task
            task = process_ocr_task.delay(pdf_source=pdf_url, pdf_title=pdf_title)

            logger.info(f"Tâche Celery démarrée pour OCR: {task.id} pour l'URL: {pdf_url}")

            # Redirige l'utilisateur vers une page de statut, en passant l'ID de la tâche
            # Note: Redirection vers la page de statut, pas vers l'API de statut directement
            return redirect(url_for('ocr.task_status_page', task_id=task.id))

        except Exception as e:
            logger.error(f"Erreur lors du lancement de la tâche Celery OCR: {e}", exc_info=True)
            flash("Une erreur s'est produite lors du lancement du traitement.", "danger")
            # Rediriger vers la page du formulaire
            return redirect(url_for('ocr.show_trigger_page'))

    else:
        # Si la validation échoue (y compris CSRF manquant ou invalide)
        flash("Erreur de validation du formulaire. Veuillez vérifier les champs.", "danger")
        # Afficher les erreurs spécifiques (optionnel mais utile pour le debug)
        for field, errors in form.errors.items():
            for error in errors:
                # Vous pouvez utiliser logger ou flash pour afficher les erreurs détaillées
                logger.warning(f"Erreur dans le champ '{getattr(form, field).label.text if hasattr(getattr(form, field), 'label') else field}': {error}")
                # flash(f"Erreur dans le champ '{getattr(form, field).label.text}': {error}", "warning") # Décommenter pour afficher à l'utilisateur

        # Rediriger vers la page du formulaire pour que l'utilisateur corrige
        return redirect(url_for('ocr.show_trigger_page'))


# --- Route pour VÉRIFIER LE STATUT de la tâche ---
@ocr_bp.route('/status/<task_id>')
@login_required
def task_status(task_id):
    """
    Vérifie et retourne le statut de la tâche Celery.
    Sera appelée par Javascript (polling).
    """
    # Récupère l'objet résultat de la tâche Celery
    # Assurez-vous que process_ocr_task est importé ou accessible ici
    from app.tasks import process_ocr_task
    task = process_ocr_task.AsyncResult(task_id)

    response_data = {
        'task_id': task_id,
        'state': task.state,
        'info': {} # Pour stocker les métadonnées de progression ou le résultat/erreur
    }

    if task.state == 'PENDING':
        # La tâche n'a pas encore démarré ou l'ID est invalide
        response_data['info'] = {'status': 'En attente...', 'message': 'La tâche est en file d\'attente ou n\'existe pas.'}
    elif task.state == 'PROGRESS':
        # La tâche est en cours, task.info contient les métadonnées que nous avons définies avec update_state
        response_data['info'] = task.info
    elif task.state == 'SUCCESS':
        # La tâche est terminée avec succès, task.info contient la valeur retournée par la tâche
        response_data['info'] = task.info # Le dictionnaire 'results' retourné par la tâche
        # Optionnellement, ajoutez une URL vers la page de résultat finale
        response_data['result_url'] = url_for('ocr.task_result', task_id=task_id)
    elif task.state == 'FAILURE':
        # La tâche a échoué
        # task.info peut être l'exception elle-même ou un traceback.
        # Il est préférable de stocker des informations sérialisables dans task.info via la tâche Celery en cas d'échec.
        # Si vous avez bien retourné le dict 'results' même en cas d'erreur dans la tâche:
        if isinstance(task.info, dict) and 'error' in task.info:
             response_data['info'] = task.info
        else:
             # Fallback si task.info n'est pas le dict attendu
             response_data['info'] = {'error': str(task.info)} # Convertir l'exception/traceback en string
    else:
         # Autre état (RETRY, REVOKED, etc.)
         response_data['info'] = {'status': task.state}

    return jsonify(response_data)


# --- Route pour AFFICHER LES RÉSULTATS finaux ---
@ocr_bp.route('/result/<task_id>')
@login_required
def task_result(task_id):
    """
    Affiche les résultats finaux de la tâche.
    """
    from app.tasks import process_ocr_task # Import nécessaire si pas déjà fait globalement
    task = process_ocr_task.AsyncResult(task_id)

    results = None # Initialiser results à None
    if task.state == 'SUCCESS':
        results = task.result # Récupère la valeur de retour (le dictionnaire 'results')
    elif task.state == 'FAILURE':
        # Essayer de récupérer les infos (qui pourraient contenir l'erreur structurée)
        if isinstance(task.info, dict):
             results = task.info # Récupère les infos (qui contiennent l'erreur)
             flash(f"Le traitement a échoué: {results.get('error', 'Erreur inconnue')}", "danger")
        else:
            # Si task.info n'est pas un dict, afficher l'erreur brute
            flash(f"Le traitement a échoué: {str(task.info)}", "danger")
            results = {"error": str(task.info), "task_id": task_id, "final_status": "FAILURE"} # Créer un dict minimal
    else:
        # Si l'utilisateur arrive ici mais que la tâche n'est pas finie, rediriger vers le statut
        flash("Le traitement n'est pas encore terminé.", "info")
        return redirect(url_for('ocr.task_status_page', task_id=task_id))

    # Passez les résultats au template pour affichage (même en cas d'échec partiel ou complet)
    return render_template('ocr/results.html', results=results)


# --- Route pour afficher la page de SUIVI DE STATUT (inchangée) ---
@ocr_bp.route('/status-page/<task_id>')
@login_required
def task_status_page(task_id):
    """Affiche la page qui suivra la progression de la tâche."""
    return render_template('ocr/processing_page.html', task_id=task_id)
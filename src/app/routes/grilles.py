import os
import uuid
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app.forms import FileUploadForm
from app.tasks.import_grille import extract_grille_from_pdf_task  # Assurez-vous que cette tâche est bien importée dans app/tasks/__init__.py

# Créer le blueprint
grille_bp = Blueprint('grille_bp', __name__, template_folder='templates')

@grille_bp.route('/import_grille', methods=['GET', 'POST'])
@login_required
def import_grille():
    """
    Affiche un formulaire permettant d'importer un fichier PDF, lance la tâche Celery
    et redirige vers une page de suivi du statut de la tâche.
    """
    form = FileUploadForm()
    if form.validate_on_submit():
        # Récupérer le fichier uploadé
        file = form.file.data
        
        # Créer un nom de fichier unique
        filename = f"{uuid.uuid4().hex}_{file.filename}"
        # Définir le dossier d'upload depuis la config ou 'uploads' par défaut
        upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"))
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        
        # Récupérer la clé API du current_user
        openai_key = current_user.openai_key
        
        # Lancer la tâche Celery de traitement du PDF
        task = extract_grille_from_pdf_task.delay(pdf_path=filepath, openai_key=openai_key)
        
        flash("Le fichier a été importé et la tâche a été lancée. Veuillez patienter...", "info")
        # Rediriger vers la page de suivi avec le task.id
        return redirect(url_for('grille_bp.task_status', task_id=task.id))
    return render_template('import_grille.html', form=form)

@grille_bp.route('/task_status/<task_id>')
@login_required
def task_status(task_id):
    """
    Affiche le statut et le résultat de la tâche Celery.
    """
    from celery.result import AsyncResult
    task_result = AsyncResult(task_id)
    return render_template('task_status.html', task_id=task_id, state=task_result.state, result=task_result.result)

@grille_bp.route('/task_status_api/<task_id>')
# @login_required
def task_status_api(task_id):
    """Provides task status and result as JSON for AJAX requests."""
    task = extract_grille_from_pdf_task.AsyncResult(task_id)
    response_data = {
        'state': task.state,
        'result': None
    }
    if task.state == 'SUCCESS':
        # The task result itself is a dictionary {'status': 'success/error', 'result': 'json string'/'error msg', ...}
        task_output = task.result
        response_data['result'] = task_output

        # Optionally try to parse the JSON result here for validation
        # if task_output and task_output.get('status') == 'success':
        #     try:
        #         json.loads(task_output.get('result', '{}'))
        #         # JSON is valid
        #     except json.JSONDecodeError:
        #          # Handle case where 'result' isn't valid JSON
        #          task_output['status'] = 'error'
        #          task_output['message'] = 'Erreur: La sortie de l\'IA n\'était pas du JSON valide.'
        #          response_data['result'] = task_output


    elif task.state == 'FAILURE':
        # Provide error information
        response_data['result'] = {
            'status': 'error',
            'message': str(task.info) # task.info often contains the traceback or exception
        }
    elif task.state == 'PENDING':
         response_data['result'] = {'status': 'pending', 'message': 'La tâche est en attente...'}
    elif task.state == 'STARTED':
         response_data['result'] = {'status': 'started', 'message': 'La tâche a démarré...'}
    # Add other states like PROGRESS if your task updates it
    # elif task.state == 'PROGRESS':
    #    response_data['result'] = task.info # Get progress meta

    return jsonify(response_data)

@grille_bp.route('/test_template')
def test_template():
    return render_template('test.html')

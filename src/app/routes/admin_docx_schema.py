import os
import re
import time
from flask import render_template, request, jsonify, current_app
from flask_login import login_required, current_user

from ..forms import DocxToSchemaForm
from ..tasks.docx_to_schema import docx_to_json_schema_task
from .routes import main
from ...utils.decorator import role_required, ensure_profile_completed


@main.route('/docx_to_schema', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_page():
    form = DocxToSchemaForm()
    return render_template('docx_to_schema.html', form=form)


@main.route('/docx_to_schema/start', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_start():
    form = DocxToSchemaForm()
    if not form.validate_on_submit():
        return jsonify({'error': 'Invalid submission.', 'details': form.errors}), 400

    file = form.file.data
    if not file or not file.filename.lower().endswith('.docx'):
        return jsonify({'error': 'Veuillez fournir un fichier .docx.'}), 400

    upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'))
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', file.filename)
    stored_name = f"docx_schema_{int(time.time())}_{safe_name}"
    stored_path = os.path.join(upload_dir, stored_name)
    file.save(stored_path)

    model = form.model.data or 'gpt-4o-mini'
    reasoning = form.reasoning_level.data or 'medium'
    verbosity = form.verbosity.data or 'medium'

    task = docx_to_json_schema_task.delay(stored_path, model, reasoning, verbosity, current_user.id)
    return jsonify({'task_id': task.id}), 202


@main.route('/docx_to_schema/validate', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_validate():
    """Endpoint appelé lorsque l'utilisateur valide le schéma généré."""
    # Pour l'instant on accepte simplement la requête et répondons avec un succès.
    # L'intégration future pourra créer les objets nécessaires à partir du schéma.
    return jsonify({'success': True})


@main.route('/docx_schema_preview', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_preview():
    """Page d'aperçu du schéma validé, accessible via le menu principal."""
    return render_template('docx_schema_preview.html')

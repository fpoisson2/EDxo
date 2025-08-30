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
    if 'file' not in request.files:
        return jsonify({'error': 'Aucun fichier fourni.'}), 400
    file = request.files['file']
    if not file or not file.filename.lower().endswith('.docx'):
        return jsonify({'error': 'Veuillez fournir un fichier .docx.'}), 400

    upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'))
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', file.filename)
    stored_name = f"docx_schema_{int(time.time())}_{safe_name}"
    stored_path = os.path.join(upload_dir, stored_name)
    file.save(stored_path)

    model = request.form.get('model', 'gpt-4o-mini')
    reasoning = request.form.get('reasoning_level', 'medium')
    verbosity = request.form.get('verbosity', 'medium')

    task = docx_to_json_schema_task.delay(stored_path, model, reasoning, verbosity, current_user.id)
    return jsonify({'task_id': task.id}), 202

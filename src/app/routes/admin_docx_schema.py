import os
import re
import time
from flask import render_template, request, jsonify, current_app, redirect, url_for, session
from flask_login import login_required, current_user

from ..forms import DocxToSchemaForm
from ..tasks.docx_to_schema import docx_to_json_schema_task
from ..models import db, DocxSchemaPage, SectionAISettings
from .routes import main
from ...utils.decorator import role_required, ensure_profile_completed

DEFAULT_DOCX_TO_SCHEMA_PROMPT = (
    "Propose un schéma JSON simple, cohérent et normalisé pour représenter parfaitement ce document. "
    "Retourne un objet JSON avec deux clés : `schema` contenant le schéma et `markdown` contenant une version Markdown fidèle au document. "
    "Chaque champ du schéma doit inclure un titre et une description. "
    "Le schéma doit représenter parfaitement la séquence et la hiérarchie des sections. Ne retourne que cet objet JSON."
)


@main.route('/docx_to_schema', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_page():
    form = DocxToSchemaForm()
    return render_template('settings/docx_to_schema.html', form=form)


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

    sa = SectionAISettings.get_for('docx_to_schema')
    model = sa.ai_model or 'gpt-4o-mini'
    reasoning = sa.reasoning_effort or 'medium'
    verbosity = sa.verbosity or 'medium'
    system_prompt = sa.system_prompt or DEFAULT_DOCX_TO_SCHEMA_PROMPT

    task = docx_to_json_schema_task.delay(stored_path, model, reasoning, verbosity, system_prompt, current_user.id)
    return jsonify({'task_id': task.id}), 202


@main.route('/docx_to_schema/preview', methods=['GET', 'POST'])
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_preview_temp():
    if request.method == 'POST':
        data = request.get_json() or {}
        session['pending_docx_schema'] = data.get('schema')
        session['pending_docx_markdown'] = data.get('markdown')
        return jsonify({'ok': True})
    schema = session.get('pending_docx_schema')
    markdown = session.get('pending_docx_markdown')
    if not schema:
        return redirect(url_for('main.docx_to_schema_page'))
    return render_template('docx_schema_validate.html', schema=schema, markdown=markdown)


@main.route('/docx_to_schema/validate', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_validate():
    """Persiste le schéma validé et retourne l'identifiant de la nouvelle page."""
    data = request.get_json() or {}
    schema = data.get('schema')
    markdown = data.get('markdown')
    if not schema:
        return jsonify({'error': 'Schéma manquant.'}), 400

    title = schema.get('title') or schema.get('titre') or f"Schéma {int(time.time())}"
    page = DocxSchemaPage(title=title, json_schema=schema, markdown_content=markdown)
    db.session.add(page)
    db.session.commit()
    session.pop('pending_docx_schema', None)
    session.pop('pending_docx_markdown', None)
    return jsonify({'success': True, 'page_id': page.id}), 201

@main.route('/docx_schema', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_pages():
    pages = DocxSchemaPage.query.order_by(DocxSchemaPage.created_at.desc()).all()
    return render_template('docx_schema_list.html', pages=pages)


@main.route('/docx_schema/<int:page_id>', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_page_view(page_id):
    page = DocxSchemaPage.query.get_or_404(page_id)
    return render_template('docx_schema_preview.html', page=page)


@main.route('/docx_schema/<int:page_id>/json', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_page_json(page_id):
    page = DocxSchemaPage.query.get_or_404(page_id)
    return render_template('docx_schema_json.html', page=page)


@main.route('/docx_schema/<int:page_id>/edit', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_page_edit(page_id):
    """Met à jour le schéma JSON d'une page existante."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    data = request.get_json() or {}
    schema = data.get('schema')
    if not schema:
        return jsonify({'error': 'Schéma manquant.'}), 400
    page.json_schema = schema
    page.title = schema.get('title') or schema.get('titre') or page.title
    db.session.commit()
    return jsonify({'success': True})


@main.route('/docx_schema/<int:page_id>/delete', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_page_delete(page_id):
    page = DocxSchemaPage.query.get_or_404(page_id)
    db.session.delete(page)
    db.session.commit()
    return redirect(url_for('main.docx_schema_pages'))

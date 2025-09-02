import os
import re
import time
from flask import render_template, request, jsonify, current_app, redirect, url_for, session
from flask_login import login_required, current_user

from ..forms import DocxToSchemaForm
from ..tasks.docx_to_schema import docx_to_json_schema_task
from ..tasks.data_schema import (
    data_schema_generate_entry_task,
    data_schema_improve_entry_task,
    data_schema_import_from_file_task,
)
from ..models import db, DocxSchemaPage, SectionAISettings, DocxSchemaEntry, DocxSchemaSectionMap, DataSchemaLink
from .routes import main
from ...utils.decorator import role_required, ensure_profile_completed
import json
import base64

DEFAULT_DOCX_TO_SCHEMA_PROMPT = (
    "Propose un schéma JSON simple, cohérent et normalisé pour représenter parfaitement ce document. "
    "Retourne un objet structuré avec quatre clés : `title`, `description`, `schema` et `markdown`. "
    "`schema` contient le schéma JSON complet, `markdown` une version Markdown fidèle au document. "
    "Chaque champ du schéma doit inclure un titre et une description et la hiérarchie doit être respectée. "
    "Ne retourne que cet objet JSON."
)


@main.route('/docx_to_schema', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_page():
    form = DocxToSchemaForm()
    return render_template('settings/docx_to_schema.html', form=form)


def _normalize_schema_payload(raw):
    """Return a dict schema from possibly stringified inputs.
    Accepts either a schema object, or a wrapper {schema: <string|object>} or a JSON string.
    """
    schema = raw
    # Unwrap common wrapper
    if isinstance(schema, dict) and 'schema' in schema and not any(k in schema for k in ('type', 'properties', '$schema')):
        schema = schema.get('schema')
    # Parse if string
    if isinstance(schema, str):
        s = schema.strip()
        if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
            try:
                schema = json.loads(s)
            except Exception:
                pass
    # If still not a dict but has nested string under 'schema', try once more
    if isinstance(schema, dict) and isinstance(schema.get('schema'), str):
        try:
            schema = json.loads(schema.get('schema'))
        except Exception:
            pass
    return schema

# -----------------------------
# JSON Pointer helpers (schema/data)
# -----------------------------
def _unescape_ptr_token(tok: str) -> str:
    return (tok or '').replace('~1', '/').replace('~0', '~')


def _split_pointer(ptr: str):
    if not isinstance(ptr, str):
        return []
    if ptr.startswith('/'):
        ptr = '#' + ptr
    if not ptr.startswith('#/'):
        return []
    return [_unescape_ptr_token(t) for t in ptr[2:].split('/') if t != '']


def _get_schema_node(schema: dict, ptr: str):
    try:
        toks = _split_pointer(ptr)
        cur = schema
        for t in toks:
            if isinstance(cur, list):
                if t.isdigit():
                    idx = int(t)
                    if 0 <= idx < len(cur):
                        cur = cur[idx]
                    else:
                        return None
                else:
                    return None
            elif isinstance(cur, dict):
                if t in cur:
                    cur = cur[t]
                else:
                    return None
            else:
                return None
        return cur
    except Exception:
        return None


def _pointer_to_data_path(ptr: str):
    toks = _split_pointer(ptr)
    out = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == 'properties' and (i + 1) < len(toks):
            out.append(toks[i + 1])
            i += 2
            continue
        if t == 'items':
            if (i + 1) < len(toks) and toks[i + 1].isdigit():
                out.append(int(toks[i + 1]))
                i += 2
            else:
                i += 1
            continue
        if t in ('$defs', 'definitions'):
            i += 1
            continue
        out.append(t)
        i += 1
    return out


def _get_data_at_path(data, path):
    cur = data
    try:
        for p in path:
            if isinstance(p, int):
                if not isinstance(cur, list) or p >= len(cur):
                    return None
                cur = cur[p]
            else:
                if not isinstance(cur, dict) or p not in cur:
                    return None
                cur = cur[p]
        return cur
    except Exception:
        return None


def _compute_allowed_values(page: DocxSchemaPage, target_pointer: str, target_entry_id: int | None):
    """Return a set of allowed values (as strings) resolved from target schema/entries.
    - If target node has enum: return enum values.
    - Else aggregate from entries at target_pointer; supports list of strings or objects (value heuristics).
    """
    allowed = set()
    # Normalize pointer variant
    if target_pointer and target_pointer.startswith('/'):
        target_pointer = '#' + target_pointer
    schema = _normalize_schema_payload(page.json_schema)
    node = _get_schema_node(schema, target_pointer)
    if isinstance(node, dict) and isinstance(node.get('enum'), list):
        for v in node.get('enum'):
            try:
                allowed.add(str(v))
            except Exception:
                pass
        return allowed
    # Aggregate from entries
    q = DocxSchemaEntry.query.filter_by(page_id=page.id)
    if target_entry_id:
        q = q.filter_by(id=target_entry_id)
    entries = q.order_by(DocxSchemaEntry.created_at.desc()).all()
    path = _pointer_to_data_path(target_pointer)
    flat = []
    for e in entries:
        v = _get_data_at_path(e.data, path)
        if v is None:
            continue
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    def pick_value(obj):
        if not isinstance(obj, dict):
            return None
        for k in ('id', 'code', 'slug', 'value'):
            if k in obj and obj[k] not in (None, ''):
                return str(obj[k])
        try:
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return str(obj)
    for it in flat:
        if isinstance(it, (str, int, float)):
            allowed.add(str(it))
        elif isinstance(it, dict):
            vv = pick_value(it)
            if vv is not None:
                allowed.add(vv)
    return allowed


def _b64_encode_ptr(ptr: str) -> str:
    return base64.b64encode(ptr.encode('utf-8')).decode('ascii')


@main.route('/docx_to_schema/start', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_start():
    form = DocxToSchemaForm()
    if not form.validate_on_submit():
        return jsonify({'error': 'Invalid submission.', 'details': form.errors}), 400

    file = form.file.data
    if not file or not file.filename.lower().endswith(('.docx', '.pdf')):
        return jsonify({'error': 'Veuillez fournir un fichier .docx ou .pdf.'}), 400

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
        schema = _normalize_schema_payload(data.get('schema'))
        title = data.get('title')
        description = data.get('description')
        if isinstance(schema, dict):
            if title and 'title' not in schema:
                schema['title'] = title
            if description and 'description' not in schema:
                schema['description'] = description
        session['pending_docx_schema'] = schema
        session['pending_docx_markdown'] = data.get('markdown')
        session['pending_docx_title'] = title
        session['pending_docx_description'] = description
        return jsonify({'ok': True})
    schema = session.get('pending_docx_schema')
    markdown = session.get('pending_docx_markdown')
    title = session.get('pending_docx_title')
    description = session.get('pending_docx_description')
    if not schema:
        return redirect(url_for('main.docx_to_schema_page'))
    return render_template('docx_schema_validate.html', schema=schema, markdown=markdown, title=title, description=description)


@main.route('/docx_to_schema/validate', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_to_schema_validate():
    """Persiste le schéma validé et retourne l'identifiant de la nouvelle page."""
    data = request.get_json() or {}
    schema = _normalize_schema_payload(data.get('schema'))
    markdown = data.get('markdown')
    if not schema:
        return jsonify({'error': 'Schéma manquant.'}), 400

    title = data.get('title') or schema.get('title') or schema.get('titre') or f"Schéma {int(time.time())}"
    description = data.get('description') or schema.get('description')
    if isinstance(schema, dict):
        if title and 'title' not in schema:
            schema['title'] = title
        if description and 'description' not in schema:
            schema['description'] = description
    page = DocxSchemaPage(title=title, json_schema=schema, markdown_content=markdown)
    db.session.add(page)
    db.session.commit()
    session.pop('pending_docx_schema', None)
    session.pop('pending_docx_markdown', None)
    session.pop('pending_docx_title', None)
    session.pop('pending_docx_description', None)
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
    return render_template('schema_form.html', page=page)


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
    schema = _normalize_schema_payload(data.get('schema'))
    if not schema:
        return jsonify({'error': 'Schéma manquant.'}), 400
    page.json_schema = schema
    page.title = schema.get('title') or schema.get('titre') or page.title
    db.session.commit()
    return jsonify({'success': True})


@main.route('/docx_schema/<int:page_id>/rename', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_page_rename(page_id):
    """Met à jour uniquement le titre d'un schéma existant."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    data = request.get_json() or {}
    title = data.get('title')
    if not title:
        return jsonify({'error': 'Titre manquant.'}), 400
    page.title = title
    if isinstance(page.json_schema, dict):
        page.json_schema['title'] = title
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


@main.route('/docx_schema/<int:page_id>/duplicate', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_page_duplicate(page_id):
    """Duplique un schéma (crée une nouvelle page avec le même JSON)."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    try:
        new_title = f"{page.title} (copie)" if page.title else f"Schéma {int(time.time())}"
        # Deep copy schema if dict
        schema = page.json_schema
        try:
            if isinstance(schema, str):
                schema = json.loads(schema)
            else:
                schema = json.loads(json.dumps(schema))
        except Exception:
            pass
        new_page = DocxSchemaPage(title=new_title, json_schema=schema, markdown_content=page.markdown_content)
        db.session.add(new_page)
        db.session.commit()
        return jsonify({'success': True, 'page_id': new_page.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Impossible de dupliquer: {e}'}), 500


@main.route('/docx_schema/<int:page_id>/entries', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_entries_create(page_id):
    """Crée une nouvelle entrée de données pour ce schéma.

    CSRF: validée via CSRFProtect (en-tête X-CSRFToken attendu pour JSON).
    Payload attendu: {"data": <objet JSON>}
    """
    page = DocxSchemaPage.query.get_or_404(page_id)
    payload = request.get_json(silent=True) or {}
    data = payload.get('data')
    if not isinstance(data, dict):
        return jsonify({'error': 'Payload invalide: data doit être un objet JSON.'}), 400
    # Optionnel: déduire un titre depuis la donnée si présent
    title = data.get('title') or data.get('titre')
    # Server-side validation against linked choices (utilise/hérite_de)
    # and support persisted target entry filter via data['__links__']
    links_meta = {}
    if isinstance(data.get('__links__'), dict):
        links_meta = data.get('__links__')
    # Validate using DataSchemaLink for this page as source
    from ..models import DataSchemaLink
    links = DataSchemaLink.query.filter_by(source_page_id=page.id).all()
    errors = []
    for l in links:
        if l.relation_type not in ('utilise', 'herite_de'):
            continue
        # Find selected target entry id for this source pointer
        encoded_key = f"_b64_{_b64_encode_ptr(l.source_pointer)}"
        target_entry_id = None
        try:
            v = links_meta.get(encoded_key)
            if v not in (None, ''):
                target_entry_id = int(v)
        except Exception:
            target_entry_id = None
        target_page = DocxSchemaPage.query.get(l.target_page_id)
        if not target_page:
            continue
        allowed = _compute_allowed_values(target_page, l.target_pointer, target_entry_id)
        if not allowed:
            # nothing to validate against
            continue
        # Extract source value(s)
        src_path = _pointer_to_data_path(l.source_pointer)
        val = _get_data_at_path(data, src_path)
        if val is None:
            continue
        def norm_ok(x):
            try:
                return str(x) in allowed
            except Exception:
                return False
        if isinstance(val, list):
            bad = [x for x in val if not isinstance(x, dict) and not norm_ok(x)]
            if bad:
                errors.append({
                    'pointer': l.source_pointer,
                    'message': f"Valeurs hors liste: {bad}",
                })
        elif isinstance(val, dict):
            # Not supported yet; skip strict validation for objects
            continue
        else:
            if not norm_ok(val):
                errors.append({
                    'pointer': l.source_pointer,
                    'message': f"Valeur hors liste: {val}",
                })
    if errors:
        return jsonify({'error': 'Validation échouée', 'details': errors}), 400
    entry = DocxSchemaEntry(page_id=page.id, data=data, title=title, created_by_id=(current_user.id if current_user.is_authenticated else None))
    db.session.add(entry)
    db.session.commit()
    return jsonify({'success': True, 'entry_id': entry.id}), 201


@main.route('/docx_schema/<int:page_id>/entries', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_entries_list(page_id):
    """Retourne la liste des entrées pour ce schéma (JSON)."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    entries = DocxSchemaEntry.query.filter_by(page_id=page.id).order_by(DocxSchemaEntry.created_at.desc()).all()
    return jsonify({'entries': [e.to_dict() for e in entries]})


@main.route('/docx_schema/<int:page_id>/generate/start', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_generate_start(page_id):
    """Lance une génération d'entrée de données via IA pour un schéma."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    payload = request.get_json(silent=True) or {}
    extra = payload.get('additional_info') or ''
    # Per‑schema settings (generation scope)
    sa = SectionAISettings.get_for(f'docx_schema_{page.id}')
    model = sa.ai_model or 'gpt-4o-mini'
    reasoning = sa.reasoning_effort or 'medium'
    verbosity = sa.verbosity or 'medium'
    system_prompt = sa.system_prompt or 'Tu génères des données strictement conformes au schéma fourni.'
    from ...celery_app import celery
    task_func = globals().get('data_schema_generate_entry_task') or data_schema_generate_entry_task
    task = task_func.delay(page_id=page.id, user_id=current_user.id, system_prompt=system_prompt, model=model, reasoning=reasoning, verbosity=verbosity, extra_instructions=extra)
    return jsonify({'task_id': task.id}), 202


@main.route('/docx_schema/<int:page_id>/improve/start', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_improve_start(page_id):
    """Améliore une entrée existante et crée une nouvelle entrée."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    payload = request.get_json(silent=True) or {}
    entry_id = payload.get('entry_id')
    if not entry_id:
        return jsonify({'error': "Paramètre entry_id requis."}), 400
    entry = DocxSchemaEntry.query.filter_by(id=entry_id, page_id=page.id).first()
    if not entry:
        return jsonify({'error': "Entrée introuvable pour ce schéma."}), 404
    extra = payload.get('additional_info') or ''
    # Per‑schema settings (improvement scope)
    sa = SectionAISettings.get_for(f'docx_schema_{page.id}_improve')
    model = sa.ai_model or 'gpt-4o-mini'
    reasoning = sa.reasoning_effort or 'medium'
    verbosity = sa.verbosity or 'medium'
    system_prompt = sa.system_prompt or 'Tu améliores des données en respectant strictement le schéma.'
    task_func = globals().get('data_schema_improve_entry_task') or data_schema_improve_entry_task
    task = task_func.delay(page_id=page.id, entry_id=entry.id, user_id=current_user.id, system_prompt=system_prompt, model=model, reasoning=reasoning, verbosity=verbosity, extra_instructions=extra)
    return jsonify({'task_id': task.id}), 202


@main.route('/docx_schema/<int:page_id>/import/start', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_import_start(page_id):
    """Importe des données à partir d'un DOCX/PDF en respectant le schéma (crée une entrée)."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'Fichier manquant.'}), 400
    upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', file.filename)
    stored = os.path.join(upload_dir, f"schema_data_{int(time.time())}_{safe_name}")
    file.save(stored)
    # Per‑schema settings (import scope)
    sa = SectionAISettings.get_for(f'docx_schema_{page.id}_import')
    model = sa.ai_model or 'gpt-4o-mini'
    reasoning = sa.reasoning_effort or 'medium'
    verbosity = sa.verbosity or 'medium'
    system_prompt = sa.system_prompt or 'Tu extrais des données strictement conformes au schéma.'
    task_func = globals().get('data_schema_import_from_file_task') or data_schema_import_from_file_task
    task = task_func.delay(page_id=page.id, file_path=stored, user_id=current_user.id, system_prompt=system_prompt, model=model, reasoning=reasoning, verbosity=verbosity)
    return jsonify({'task_id': task.id}), 202


@main.route('/docx_schema/<int:page_id>/entries/list', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_entries_list_page(page_id):
    """Page HTML listant toutes les entrées d'un schéma avec actions."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    entries = DocxSchemaEntry.query.filter_by(page_id=page.id).order_by(DocxSchemaEntry.created_at.desc()).all()
    return render_template('docx_schema_entries_list.html', page=page, entries=entries)


@main.route('/docx_schema/<int:page_id>/entries/<int:entry_id>/delete', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_entry_delete(page_id, entry_id):
    """Supprime une entrée de données liée à un schéma (CSRF requis)."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    entry = DocxSchemaEntry.query.filter_by(id=entry_id, page_id=page.id).first_or_404()
    db.session.delete(entry)
    db.session.commit()
    if request.is_json:
        return jsonify({'success': True})
    return redirect(url_for('main.docx_schema_entries_list_page', page_id=page.id))


@main.route('/docx_schema/<int:page_id>/entries/<int:entry_id>/edit', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_entry_edit_page(page_id, entry_id):
    """Page d'édition pour une entrée existante (réutilise le formulaire schéma)."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    entry = DocxSchemaEntry.query.filter_by(id=entry_id, page_id=page.id).first_or_404()
    return render_template('schema_form.html', page=page, entry=entry)


@main.route('/docx_schema/<int:page_id>/entries/<int:entry_id>/update', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_entry_update(page_id, entry_id):
    """Met à jour le contenu JSON d'une entrée (CSRF requis)."""
    page = DocxSchemaPage.query.get_or_404(page_id)
    entry = DocxSchemaEntry.query.filter_by(id=entry_id, page_id=page.id).first_or_404()
    payload = request.get_json(silent=True) or {}
    data = payload.get('data')
    if not isinstance(data, (dict, list)):
        return jsonify({'error': 'Payload invalide: data doit être un objet ou une liste JSON.'}), 400
    # Validation with links and optional __links__ meta
    links_meta = {}
    if isinstance(data, dict) and isinstance(data.get('__links__'), dict):
        links_meta = data.get('__links__')
    from ..models import DataSchemaLink
    links = DataSchemaLink.query.filter_by(source_page_id=page.id).all()
    errors = []
    for l in links:
        if l.relation_type not in ('utilise', 'herite_de'):
            continue
        encoded_key = f"_b64_{_b64_encode_ptr(l.source_pointer)}"
        target_entry_id = None
        try:
            v = links_meta.get(encoded_key)
            if v not in (None, ''):
                target_entry_id = int(v)
        except Exception:
            target_entry_id = None
        target_page = DocxSchemaPage.query.get(l.target_page_id)
        if not target_page:
            continue
        allowed = _compute_allowed_values(target_page, l.target_pointer, target_entry_id)
        if not allowed:
            continue
        src_path = _pointer_to_data_path(l.source_pointer)
        val = _get_data_at_path(data, src_path)
        if val is None:
            continue
        def norm_ok(x):
            try:
                return str(x) in allowed
            except Exception:
                return False
        if isinstance(val, list):
            bad = [x for x in val if not isinstance(x, dict) and not norm_ok(x)]
            if bad:
                errors.append({'pointer': l.source_pointer, 'message': f"Valeurs hors liste: {bad}"})
        elif isinstance(val, dict):
            continue
        else:
            if not norm_ok(val):
                errors.append({'pointer': l.source_pointer, 'message': f"Valeur hors liste: {val}"})
    if errors:
        return jsonify({'error': 'Validation échouée', 'details': errors}), 400
    entry.data = data
    # Mettre à jour le titre si présent dans la donnée
    if isinstance(data, dict):
        entry.title = data.get('title') or data.get('titre') or entry.title
    db.session.commit()
    return jsonify({'success': True, 'entry_id': entry.id})


@main.route('/docx_schema/<int:page_id>/mapping', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_mapping_page(page_id):
    page = DocxSchemaPage.query.get_or_404(page_id)
    default_sections = [
        'session.numero',
        'cours.code',
        'cours.nom',
        'cours.heures_theorie',
        'cours.heures_laboratoire',
        'cours.heures_travail_maison',
        'cours.unites',
    ]
    existing = {m.section_key: m.pointer for m in DocxSchemaSectionMap.query.filter_by(page_id=page.id).all()}
    return render_template('docx_schema_mapping.html', page=page, default_sections=default_sections, existing=existing)


@main.route('/docx_schema/<int:page_id>/mapping', methods=['POST'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_mapping_save(page_id):
    page = DocxSchemaPage.query.get_or_404(page_id)
    payload = request.get_json(silent=True) or {}
    mappings = payload.get('mappings')
    if not isinstance(mappings, list):
        return jsonify({'error': 'Payload invalide: mappings doit être une liste.'}), 400
    for m in mappings:
        if not isinstance(m, dict):
            continue
        key = (m.get('section_key') or '').strip()
        pointer = (m.get('pointer') or '').strip()
        if not key or not pointer:
            continue
        obj = DocxSchemaSectionMap.query.filter_by(page_id=page.id, section_key=key).first()
        if not obj:
            obj = DocxSchemaSectionMap(page_id=page.id, section_key=key, pointer=pointer)
            db.session.add(obj)
        else:
            obj.pointer = pointer
    db.session.commit()
    return jsonify({'success': True})


@main.route('/docx_schema/<int:page_id>/mapping/data', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_mapping_data(page_id):
    page = DocxSchemaPage.query.get_or_404(page_id)
    items = DocxSchemaSectionMap.query.filter_by(page_id=page.id).all()
    return jsonify({'mappings': [i.to_dict() for i in items]})


@main.route('/docx_schema/<int:page_id>/programme_view', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_programme_view(page_id):
    """Affiche une entrée (et non le schéma) en mode programme (cartes par session).

    On sélectionne l'entrée via ?entry_id=..., sinon la plus récente.
    Les données d'entrée sont interprétées pour extraire: sessions[].cours[].
    """
    page = DocxSchemaPage.query.get_or_404(page_id)
    entry_id = request.args.get('entry_id', type=int)
    entry = None
    if entry_id:
        entry = DocxSchemaEntry.query.filter_by(page_id=page.id, id=entry_id).first()
        if not entry:
            return jsonify({'error': 'Entrée introuvable pour ce schéma.'}), 404
    if not entry:
        entry = (
            DocxSchemaEntry.query
            .filter_by(page_id=page.id)
            .order_by(DocxSchemaEntry.created_at.desc())
            .first()
        )
    data = entry.data if entry else {}

    def _ensure_int(val, default=0):
        try:
            return int(val)
        except Exception:
            return default

    def _get_sessions(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get('sessions'), list):
                return obj.get('sessions')
            # Support nested placement if data was shaped similarly to schema materialization
            props = obj.get('properties') or {}
            sess = props.get('sessions')
            if isinstance(sess, dict) and isinstance(sess.get('x_data'), list):
                return sess.get('x_data')
        return []

    def _norm_course(c):
        if not isinstance(c, dict):
            return None
        code = c.get('code') or c.get('codification') or ''
        nom = c.get('nom') or c.get('titre') or ''
        ht = _ensure_int(c.get('heures_theorie') or c.get('theorie') or 0)
        hl = _ensure_int(c.get('heures_laboratoire') or c.get('pratique') or 0)
        hm = _ensure_int(c.get('heures_travail_maison') or c.get('maison') or 0)
        try:
            unites = float(c.get('unites') or c.get('unite') or 0)
        except Exception:
            unites = 0.0
        return {
            'code': code,
            'nom': nom,
            'heures_theorie': ht,
            'heures_laboratoire': hl,
            'heures_travail_maison': hm,
            'nombre_unites': unites,
        }

    sessions_data = _get_sessions(data) or []
    cours_par_session = {}
    total_heures_theorie = 0
    total_heures_laboratoire = 0
    total_heures_travail_maison = 0
    total_unites = 0.0

    for sess in sessions_data:
        if not isinstance(sess, dict):
            continue
        sess_num = _ensure_int(sess.get('numero') or sess.get('session') or 0)
        cours_list = sess.get('cours') or sess.get('cours_list') or []
        normalized = []
        for c in cours_list:
            nc = _norm_course(c)
            if not nc:
                continue
            total_heures_theorie += nc['heures_theorie']
            total_heures_laboratoire += nc['heures_laboratoire']
            total_heures_travail_maison += nc['heures_travail_maison']
            total_unites += nc['nombre_unites']
            normalized.append(nc)
        if normalized:
            cours_par_session.setdefault(sess_num, []).extend(normalized)

    cours_par_session = dict(sorted(cours_par_session.items(), key=lambda kv: kv[0]))

    # Titre affiché dans la vue
    view_title = None
    if isinstance(data, dict):
        view_title = data.get('x_view_title') or data.get('title') or data.get('titre')
    if not view_title:
        view_title = entry.title if entry and entry.title else (page.title or 'Schéma')

    return render_template(
        'view_docx_schema_programme.html',
        page=page,
        entry=entry,
        view_title=view_title,
        cours_par_session=cours_par_session,
        total_heures_theorie=total_heures_theorie,
        total_heures_laboratoire=total_heures_laboratoire,
        total_heures_travail_maison=total_heures_travail_maison,
        total_unites=total_unites,
    )


# -----------------------------
# New: list links for a schema page (source)
# -----------------------------
@main.route('/docx_schema/<int:page_id>/links', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_list_links(page_id):
    page = DocxSchemaPage.query.get_or_404(page_id)
    links = DataSchemaLink.query.filter_by(source_page_id=page.id).order_by(DataSchemaLink.id.asc()).all()
    return jsonify({'links': [l.to_dict() for l in links]})


# -----------------------------
# New: choices for a target schema pointer (enum or aggregated entries)
# -----------------------------
@main.route('/docx_schema/<int:target_page_id>/choices', methods=['GET'])
@role_required('admin')
@ensure_profile_completed
def docx_schema_choices(target_page_id):
    page = DocxSchemaPage.query.get_or_404(target_page_id)
    pointer = request.args.get('pointer', type=str)
    target_entry_id = request.args.get('target_entry_id', type=int)
    if not pointer or not (pointer.startswith('#/') or pointer.startswith('/')):
        return jsonify({'error': 'Paramètre pointer requis (#/...)'}), 400
    if pointer.startswith('/'):
        pointer = '#' + pointer

    # 1) Try enum from schema
    schema = _normalize_schema_payload(page.json_schema)
    node = _get_schema_node(schema, pointer)
    if isinstance(node, dict) and isinstance(node.get('enum'), list):
        values = node.get('enum')
        choices = [{'value': v, 'label': str(v)} for v in values]
        return jsonify({'choices': choices, 'source': 'enum', 'pointer': pointer})

    # 2) Aggregate from entries
    q = DocxSchemaEntry.query.filter_by(page_id=page.id)
    if target_entry_id:
        q = q.filter_by(id=target_entry_id)
    entries = q.order_by(DocxSchemaEntry.created_at.desc()).all()
    path = _pointer_to_data_path(pointer)
    vals = []
    for e in entries:
        v = _get_data_at_path(e.data, path)
        if v is None:
            # Try items/properties/<key> pattern: collect from each item
            toks = _split_pointer(pointer)
            try:
                if 'items' in toks:
                    i = toks.index('items')
                    # Prefix up to the array container
                    prefix_ptr = '#/' + '/'.join(toks[:i]) if i > 0 else '#/'
                    arr_path = _pointer_to_data_path(prefix_ptr)
                    arr = _get_data_at_path(e.data, arr_path)
                    # Subpath inside each item: support simple 'properties/<key>'
                    sub = []
                    if (i + 1) < len(toks) and toks[i + 1] == 'properties' and (i + 2) < len(toks):
                        sub = [toks[i + 2]]
                    if isinstance(arr, list):
                        for it in arr:
                            if sub and isinstance(it, dict):
                                vv = it.get(sub[0])
                                if vv is not None:
                                    vals.append(vv)
                            else:
                                vals.append(it)
                    continue
            except Exception:
                pass
        else:
            if isinstance(v, list):
                vals.extend(v)
            else:
                vals.append(v)

    # Heuristics: if list of strings → simple options
    def _is_str(x):
        return isinstance(x, str)

    flat = []
    for v in vals:
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)

    choices = []
    # All strings → unique set
    if flat and all(_is_str(x) for x in flat):
        uniq = sorted({x for x in flat if isinstance(x, str) and x.strip() != ''})
        choices = [{'value': s, 'label': s} for s in uniq]
        return jsonify({'choices': choices, 'source': 'entries', 'pointer': pointer})

    # Objects → try value/label heuristics
    def pick_vl(obj: dict):
        if not isinstance(obj, dict):
            return None
        for k in ('id', 'code', 'slug', 'value'):
            if k in obj and obj[k] not in (None, ''):
                v = obj[k]
                break
        else:
            v = json.dumps(obj, ensure_ascii=False)
        for k in ('name', 'nom', 'label', 'title', 'titre'):
            if k in obj and obj[k] not in (None, ''):
                l = obj[k]
                break
        else:
            l = str(v)
        return {'value': v, 'label': str(l)}

    obj_items = []
    for x in flat:
        if isinstance(x, dict):
            obj_items.append(x)
    if obj_items:
        mapped = [pick_vl(o) for o in obj_items]
        # Deduplicate by value
        seen = set()
        choices = []
        for m in mapped:
            if not m:
                continue
            try:
                key = json.dumps(m['value'], sort_keys=True, ensure_ascii=False)
            except Exception:
                key = str(m['value'])
            if key in seen:
                continue
            seen.add(key)
            choices.append(m)
        return jsonify({'choices': choices, 'source': 'entries', 'pointer': pointer})

    # Fallback: scalars mixed
    scalars = [str(x) for x in flat if isinstance(x, (str, int, float))]
    uniq = sorted(set(scalars))
    choices = [{'value': s, 'label': s} for s in uniq]
    return jsonify({'choices': choices, 'source': 'entries', 'pointer': pointer})

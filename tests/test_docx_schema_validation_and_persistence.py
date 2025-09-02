from werkzeug.security import generate_password_hash
from src.app.models import User, db, DocxSchemaPage, DocxSchemaEntry
import base64


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def create_admin(app):
    with app.app_context():
        admin = User(
            username='admin_validate_links',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.commit()
        return admin.id


def b64(s: str) -> str:
    return base64.b64encode(s.encode('utf-8')).decode('ascii')


def test_validation_array_strings_with_entry_filter_and_persistence(app, client):
    admin_id = create_admin(app)
    _login(client, admin_id)
    # Target page with array of strings
    with app.app_context():
        tgt = DocxSchemaPage(title='Tgt', json_schema={'title': 'Tgt', 'type': 'object', 'properties': {'ingredients': {'type': 'array', 'items': {'type': 'string'}}}})
        db.session.add(tgt); db.session.commit()
        tgt_id = tgt.id
        e1 = DocxSchemaEntry(page_id=tgt_id, data={'ingredients': ['sel']})
        e2 = DocxSchemaEntry(page_id=tgt_id, data={'ingredients': ['sucre']})
        db.session.add_all([e1, e2]); db.session.commit()
        e1_id, e2_id = e1.id, e2.id
    # Source page with array of strings
    with app.app_context():
        src = DocxSchemaPage(title='Src', json_schema={'title': 'Src', 'type': 'object', 'properties': {'ingredients': {'type': 'array', 'items': {'type': 'string'}}}})
        db.session.add(src); db.session.commit()
        src_id = src.id
    # Link: source.ingredients uses target.ingredients.items
    payload = {
        'source_page_id': src_id,
        'source_pointer': '#/properties/ingredients',
        'relation_type': 'utilise',
        'target_page_id': tgt_id,
        'target_pointer': '#/properties/ingredients/items',
    }
    r = client.post('/settings/schemas/links', json=payload)
    assert r.status_code == 201
    # 1) With entry filter to e1, only 'sel' is allowed
    meta_key = f"_b64_{b64(payload['source_pointer'])}"
    data_ok = { 'ingredients': ['sel'], '__links__': { meta_key: e1_id } }
    r_ok = client.post(f'/docx_schema/{src_id}/entries', json={'data': data_ok})
    assert r_ok.status_code == 201
    # Ensure persisted data contains __links__ for preselection on edit
    new_id = r_ok.get_json()['entry_id']
    page_entries = client.get(f'/docx_schema/{src_id}/entries').get_json()['entries']
    saved = [e for e in page_entries if e['id'] == new_id][0]
    assert '__links__' in (saved['data'] or {})
    # 2) With same filter, 'sucre' should be rejected
    data_bad = { 'ingredients': ['sucre'], '__links__': { meta_key: e1_id } }
    r_bad = client.post(f'/docx_schema/{src_id}/entries', json={'data': data_bad})
    assert r_bad.status_code == 400
    j = r_bad.get_json()
    assert 'Validation échouée' in j.get('error', '')
    # 3) Without filter, union across entries: 'sucre' allowed
    data_union = { 'ingredients': ['sucre'] }
    r_union = client.post(f'/docx_schema/{src_id}/entries', json={'data': data_union})
    assert r_union.status_code == 201


def test_validation_scalar_string_against_enum(app, client):
    admin_id = create_admin(app)
    _login(client, admin_id)
    # Target with enum
    with app.app_context():
        tgt = DocxSchemaPage(title='Enum', json_schema={'title': 'Enum', 'type': 'object', 'properties': {'ingredient': {'type': 'string', 'enum': ['sel', 'sucre']}}})
        db.session.add(tgt); db.session.commit()
        tgt_id = tgt.id
    # Source with scalar field
    with app.app_context():
        src = DocxSchemaPage(title='Src', json_schema={'title': 'Src', 'type': 'object', 'properties': {'ingredient': {'type': 'string'}}})
        db.session.add(src); db.session.commit()
        src_id = src.id
    # Link
    payload = {
        'source_page_id': src_id,
        'source_pointer': '#/properties/ingredient',
        'relation_type': 'herite_de',
        'target_page_id': tgt_id,
        'target_pointer': '#/properties/ingredient',
    }
    r = client.post('/settings/schemas/links', json=payload)
    assert r.status_code == 201
    # OK value
    r1 = client.post(f'/docx_schema/{src_id}/entries', json={'data': {'ingredient': 'sucre'}})
    assert r1.status_code == 201
    # Bad value
    r2 = client.post(f'/docx_schema/{src_id}/entries', json={'data': {'ingredient': 'poivre'}})
    assert r2.status_code == 400
    assert 'Validation échouée' in r2.get_json().get('error', '')

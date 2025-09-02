from werkzeug.security import generate_password_hash
from src.app.models import User, db, DocxSchemaPage


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def create_admin(app):
    with app.app_context():
        admin = User(
            username='admin_schema',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.commit()
        return admin.id


def create_schema_pages(app):
    with app.app_context():
        p1 = DocxSchemaPage(title='S1', json_schema={'title': 'S1', 'type': 'object', 'properties': {'chapitres': {'type': 'array', 'items': {'type': 'string'}}}})
        p2 = DocxSchemaPage(title='S2', json_schema={'title': 'S2', 'type': 'object', 'properties': {'elements': {'type': 'object', 'properties': {'titre': {'type': 'string'}}}}})
        db.session.add_all([p1, p2])
        db.session.commit()
        return p1.id, p2.id


def test_settings_data_schemas_page(app, client):
    admin_id = create_admin(app)
    _login(client, admin_id)
    p1, p2 = create_schema_pages(app)
    r = client.get('/settings/schemas')
    assert r.status_code == 200
    assert b'Sch\xc3\xa9mas de donn\xc3\xa9es' in r.data
    assert b'Cr\xc3\xa9er le lien' in r.data


def test_create_and_list_schema_links(app, client):
    admin_id = create_admin(app)
    _login(client, admin_id)
    p1, p2 = create_schema_pages(app)
    # Create link
    payload = {
        'source_page_id': p1,
        'source_pointer': '#/properties/chapitres/items',
        'relation_type': 'herite_de',
        'target_page_id': p2,
        'target_pointer': '#/properties/elements/properties/titre',
        'comment': 'Exemple'
    }
    r = client.post('/settings/schemas/links', json=payload)
    assert r.status_code == 201
    data = r.get_json()
    link = data['link']
    assert link['relation_type'] == 'herite_de'
    assert link['source_page_id'] == p1
    assert link['target_page_id'] == p2
    assert link['source_pointer'].startswith('#/')
    assert link['target_pointer'].startswith('#/')

    # List links
    r2 = client.get('/settings/schemas/links')
    assert r2.status_code == 200
    j = r2.get_json()
    assert isinstance(j['links'], list)
    assert any(l['id'] == link['id'] for l in j['links'])

    # Delete link
    lid = link['id']
    r3 = client.post(f'/settings/schemas/links/{lid}/delete')
    assert r3.status_code == 200
    r4 = client.get('/settings/schemas/links')
    ids = [l['id'] for l in r4.get_json()['links']]
    assert lid not in ids


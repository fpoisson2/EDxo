from werkzeug.security import generate_password_hash
from src.app.models import User, db, DocxSchemaPage


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def create_admin_and_pages(app):
    with app.app_context():
        admin = User(
            username='admin_picker',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        p1 = DocxSchemaPage(title='Pick1', json_schema={
            'title': 'Root', 'type': 'object', 'properties': {
                'chapitres': {'type': 'array', 'title': 'Chapitres', 'items': {'type': 'object', 'properties': {
                    'titre': {'type': 'string', 'title': 'Titre'}
                }}}
            }
        })
        db.session.add(p1)
        db.session.commit()
        return admin.id, p1.id


def test_picker_buttons_and_modal_present(app, client):
    admin_id, _ = create_admin_and_pages(app)
    _login(client, admin_id)
    r = client.get('/settings/schemas')
    assert r.status_code == 200
    body = r.data
    assert b'id="pickSrc"' in body
    assert b'id="pickTgt"' in body
    assert b'id="schemaPointerPickerModal"' in body or b'S\xc3\xa9lectionner un \xc3\xa9l\xc3\xa9ment du sch\xc3\xa9ma' in body


def test_schema_endpoint_returns_json_schema(app, client):
    admin_id, page_id = create_admin_and_pages(app)
    _login(client, admin_id)
    r = client.get(f'/settings/schemas/page/{page_id}/schema')
    assert r.status_code == 200
    js = r.get_json()
    assert js['id'] == page_id
    assert 'schema' in js and isinstance(js['schema'], dict)
    assert js['schema'].get('type') == 'object'


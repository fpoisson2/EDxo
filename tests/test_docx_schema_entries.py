from werkzeug.security import generate_password_hash
from bs4 import BeautifulSoup

from src.app.models import User, db, OpenAIModel, DocxSchemaPage, DocxSchemaEntry


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def setup_admin_and_simple_schema(app, client):
    with app.app_context():
        admin = User(
            username='admin_entries',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        page = DocxSchemaPage(
            title='Schéma Données',
            json_schema={'title': 'Schéma Données', 'type': 'object', 'properties': {
                'titre': {'type': 'string', 'title': 'Titre'},
                'chapitres': {'type': 'array', 'items': {'type': 'string'}, 'title': 'Chapitres'}
            }},
            markdown_content='# Schéma\n- Titre\n- Chapitres'
        )
        db.session.add(page)
        db.session.commit()
        return admin.id, page.id


def test_create_and_list_entries(app, client):
    admin_id, page_id = setup_admin_and_simple_schema(app, client)
    _login(client, admin_id)

    payload = {
        'data': {
            'titre': 'Mon Document',
            'chapitres': ['Intro', 'Partie 1']
        }
    }
    r = client.post(f'/docx_schema/{page_id}/entries', json=payload)
    assert r.status_code == 201
    eid = r.get_json().get('entry_id')
    assert isinstance(eid, int)

    r2 = client.get(f'/docx_schema/{page_id}/entries')
    assert r2.status_code == 200
    data = r2.get_json()
    assert 'entries' in data and len(data['entries']) == 1
    entry = data['entries'][0]
    assert entry['data']['titre'] == 'Mon Document'
    assert entry['data']['chapitres'] == ['Intro', 'Partie 1']


def test_create_entry_requires_csrf(app, client):
    admin_id, page_id = setup_admin_and_simple_schema(app, client)
    _login(client, admin_id)
    app.config['WTF_CSRF_ENABLED'] = True

    # 1) Sans token => 400
    r = client.post(f'/docx_schema/{page_id}/entries', json={'data': {'titre': 'X'}})
    assert r.status_code == 400

    # 2) Avec token => 201
    listing = client.get('/docx_schema')
    soup = BeautifulSoup(listing.data, 'html.parser')
    token = soup.find('meta', {'name': 'csrf-token'})['content']
    r2 = client.post(
        f'/docx_schema/{page_id}/entries',
        json={'data': {'titre': 'Avec CSRF'}},
        headers={'X-CSRFToken': token}
    )
    assert r2.status_code == 201
    with app.app_context():
        assert DocxSchemaEntry.query.filter_by(page_id=page_id).count() == 1


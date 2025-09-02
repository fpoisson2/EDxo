from werkzeug.security import generate_password_hash
from src.app.models import User, db, DocxSchemaPage, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def setup_admin_and_page(app):
    with app.app_context():
        admin = User(
            username='admin_view',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        # Some environments expect model presence; add a default
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        page = DocxSchemaPage(
            title='SchemaView',
            json_schema={
                'title': 'Root', 'type': 'object', 'properties': {
                    'titre': {'type': 'string', 'title': 'Titre'},
                    'chapitres': {'type': 'array', 'title': 'Chapitres', 'items': {'type': 'object', 'properties': {
                        'nom': {'type': 'string', 'title': 'Nom'}
                    }}}
                }
            },
            markdown_content='# Titre\n- Chapitres\n  - Nom'
        )
        db.session.add(page)
        db.session.commit()
        return admin.id, page.id


def test_preview_page_has_browse_picker(app, client):
    admin_id, page_id = setup_admin_and_page(app)
    _login(client, admin_id)
    r = client.get(f'/docx_schema/{page_id}')
    assert r.status_code == 200
    body = r.data
    assert b'id="schemaBrowseBtn"' in body
    assert b'id="schemaPointerBrowseModal"' in body
    assert b'id="schemaPointerSearch"' in body


def test_json_page_has_browse_picker(app, client):
    admin_id, page_id = setup_admin_and_page(app)
    _login(client, admin_id)
    r = client.get(f'/docx_schema/{page_id}/json')
    assert r.status_code == 200
    body = r.data
    assert b'id="schemaBrowseBtn"' in body
    assert b'id="schemaPointerBrowseModal"' in body
    assert b'id="schemaPointerSearch"' in body

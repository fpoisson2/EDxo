from werkzeug.security import generate_password_hash
from src.app.models import User, db, DocxSchemaPage, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def setup_admin_and_page(app):
    with app.app_context():
        admin = User(
            username='admin_copy',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        page = DocxSchemaPage(
            title='CopyUI',
            json_schema={
                'title': 'Root', 'type': 'object', 'properties': {
                    'titre': {'type': 'string', 'title': 'Titre'},
                    'items': {'type': 'array', 'title': 'Items', 'items': {'type': 'string'}}
                }
            }
        )
        db.session.add(page)
        db.session.commit()
        return admin.id, page.id


def test_copy_icon_buttons_present_in_preview(app, client):
    admin_id, page_id = setup_admin_and_page(app)
    _login(client, admin_id)
    r = client.get(f'/docx_schema/{page_id}')
    assert r.status_code == 200
    # Presence of copy buttons rendered with data-copy-pointer attributes
    assert b'data-copy-pointer' in r.data
    # Style helper exists
    assert b'copy-btn' in r.data


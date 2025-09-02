from werkzeug.security import generate_password_hash
from bs4 import BeautifulSoup

from src.app.models import User, db, OpenAIModel, DocxSchemaPage, DocxSchemaEntry


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def setup_admin_and_schema(app):
    with app.app_context():
        admin = User(
            username='admin_list',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        page = DocxSchemaPage(title='Listable', json_schema={'title': 'Listable', 'type': 'object'})
        db.session.add(page)
        db.session.commit()
        return admin.id, page.id


def test_entries_list_page_and_delete_with_csrf(app, client):
    admin_id, page_id = setup_admin_and_schema(app)
    _login(client, admin_id)
    # Create a couple of entries via API
    client.post(f'/docx_schema/{page_id}/entries', json={'data': {'title': 'E1'}})
    client.post(f'/docx_schema/{page_id}/entries', json={'data': {'title': 'E2'}})

    # Page lists entries
    r = client.get(f'/docx_schema/{page_id}/entries/list')
    assert r.status_code == 200
    body = r.data
    assert b'E1' in body and b'E2' in body

    # Delete requires CSRF when enabled
    app.config['WTF_CSRF_ENABLED'] = True
    # Pick one entry id
    with app.app_context():
        eid = DocxSchemaEntry.query.filter_by(page_id=page_id).first().id

    r_bad = client.post(f'/docx_schema/{page_id}/entries/{eid}/delete')
    assert r_bad.status_code == 400

    page = client.get(f'/docx_schema/{page_id}/entries/list')
    soup = BeautifulSoup(page.data, 'html.parser')
    token = soup.find('meta', {'name': 'csrf-token'})['content']
    r_ok = client.post(
        f'/docx_schema/{page_id}/entries/{eid}/delete',
        headers={'X-CSRFToken': token},
        follow_redirects=True
    )
    assert r_ok.status_code == 200
    with app.app_context():
        ids = [e.id for e in DocxSchemaEntry.query.filter_by(page_id=page_id).all()]
        assert eid not in ids


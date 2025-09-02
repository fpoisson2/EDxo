from io import BytesIO
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash

from src.app.models import User, db, OpenAIModel, DocxSchemaPage
import src.app.tasks.docx_to_schema as docx_tasks


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_docx_to_schema_requires_csrf(app, client, monkeypatch):
    with app.app_context():
        admin = User(
            username='admin',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    app.config['WTF_CSRF_ENABLED'] = True

    # Patch Celery task delay to avoid running Celery
    class Dummy:
        id = 'tid'
    monkeypatch.setattr(
        docx_tasks.docx_to_json_schema_task,
        'delay',
        lambda *a, **k: Dummy()
    )

    data = {
        'file': (BytesIO(b'hi'), 'test.docx'),
    }
    # Missing CSRF token
    resp = client.post(
        '/docx_to_schema/start',
        data=data,
        content_type='multipart/form-data'
    )
    assert resp.status_code == 400

    # Fetch page to get token
    page = client.get('/docx_to_schema')
    soup = BeautifulSoup(page.data, 'html.parser')
    token = soup.find('input', {'name': 'csrf_token'})['value']

    data = {
        'csrf_token': token,
        'file': (BytesIO(b'hi'), 'test.docx'),
    }
    resp2 = client.post(
        '/docx_to_schema/start',
        data=data,
        content_type='multipart/form-data'
    )
    assert resp2.status_code == 202
    assert resp2.get_json()['task_id'] == 'tid'


def test_docx_schema_rename_requires_csrf(app, client):
    with app.app_context():
        admin = User(
            username='renamer',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        page = DocxSchemaPage(title='Old', json_schema={'title': 'Old', 'type': 'object'})
        db.session.add_all([admin, page])
        db.session.commit()
        admin_id = admin.id
        page_id = page.id

    _login(client, admin_id)
    app.config['WTF_CSRF_ENABLED'] = True

    # Missing token
    resp = client.post(f'/docx_schema/{page_id}/rename', json={'title': 'New'})
    assert resp.status_code == 400

    listing = client.get('/docx_schema')
    soup = BeautifulSoup(listing.data, 'html.parser')
    token = soup.find('meta', {'name': 'csrf-token'})['content']

    resp_ok = client.post(
        f'/docx_schema/{page_id}/rename',
        json={'title': 'Renamed'},
        headers={'X-CSRFToken': token},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.get_json()['success'] is True
    with app.app_context():
        assert db.session.get(DocxSchemaPage, page_id).title == 'Renamed'


def test_docx_to_schema_accepts_pdf(app, client, monkeypatch):
    with app.app_context():
        admin = User(
            username='admin_pdf',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)

    class Dummy:
        id = 'tid'

    monkeypatch.setattr(
        docx_tasks.docx_to_json_schema_task,
        'delay',
        lambda *a, **k: Dummy(),
    )

    data = {
        'file': (BytesIO(b'%PDF-1.4', ), 'test.pdf'),
    }
    resp = client.post(
        '/docx_to_schema/start',
        data=data,
        content_type='multipart/form-data',
    )
    assert resp.status_code == 202
    assert resp.get_json()['task_id'] == 'tid'

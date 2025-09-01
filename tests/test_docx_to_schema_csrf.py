from io import BytesIO
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash

from src.app.models import User, db, OpenAIModel
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

from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_docx_to_schema_page_contains_start_endpoint(app, client):
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
    resp = client.get('/docx_to_schema')
    assert resp.status_code == 200
    data = resp.data
    assert b'/docx_to_schema/start' in data
    assert b'id="schemaResultContainer"' in data
    assert b'id="schemaAccordion"' in data
    assert b'id="schemaResultTree"' in data
    assert b'id="schemaResultGraph"' in data
    assert b'id="schemaValidateBtn"' in data
    assert b'renderSchemaAccordion' in data
    assert b'renderSchemaGraph' in data
    assert b'normalizePlanSchema' in data
    assert b'n.parts' in data
    assert b'n.fields' in data
    assert b'd3.zoom' in data
    assert b'onDone' in data


def test_parametres_page_has_docx_to_schema_link(app, client):
    with app.app_context():
        admin = User(
            username='admin2',
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
    resp = client.get('/parametres')
    assert resp.status_code == 200
    assert b'/docx_to_schema' in resp.data
    assert b'/settings/docx_to_schema_prompts' in resp.data


def test_docx_to_schema_validate_endpoint(app, client):
    with app.app_context():
        admin = User(
            username='admin3',
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
    resp = client.post('/docx_to_schema/validate', json={})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


def test_navbar_has_docx_schema_link(app, client):
    with app.app_context():
        admin = User(
            username='admin4',
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
    resp = client.get('/', follow_redirects=True)
    assert resp.status_code == 200
    assert b'/docx_schema_preview' in resp.data


def test_docx_to_schema_prompts_page(app, client):
    with app.app_context():
        admin = User(
            username='admin5',
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
    resp = client.get('/settings/docx_to_schema_prompts')
    assert resp.status_code == 200
    assert b'Prompts DOCX' in resp.data

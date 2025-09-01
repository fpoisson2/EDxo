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
    assert b'name="model"' not in data
    assert b'name="reasoning_level"' not in data
    assert b'name="verbosity"' not in data
    assert b'onDone' in data


def test_docx_to_schema_preview_page(app, client):
    with app.app_context():
        admin = User(
            username='adminp',
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
    schema = {'title': 'Preview', 'type': 'object'}
    client.post('/docx_to_schema/preview', json={'schema': schema, 'markdown': '# Titre\nContenu', 'title': 'Preview', 'description': 'Desc'})
    resp = client.get('/docx_to_schema/preview')
    assert resp.status_code == 200
    assert b'id="schemaAccordion"' in resp.data
    assert b'id="schemaValidateBtn"' in resp.data
    assert b'id="schemaResultMarkdown"' in resp.data
    assert b'zoom.transform' in resp.data


def test_parametres_page_has_docx_conversion_links(app, client):
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
    assert b'/docx_schema"' in resp.data


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
    payload = {'schema': {'type': 'object'}, 'markdown': '# md', 'title': 'Sample', 'description': 'Desc'}
    resp = client.post('/docx_to_schema/validate', json=payload)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['success'] is True
    page_id = data['page_id']
    # Page accessible
    resp = client.get(f'/docx_schema/{page_id}')
    assert resp.status_code == 200
    assert b'Sample' in resp.data
    assert b'id="schemaEditBtn"' in resp.data
    assert b'id="schemaResultMarkdown"' in resp.data
    # Preview page uses accordion structure and tree graph
    assert b'id="schemaAccordion"' in resp.data
    assert b'd3.tree' in resp.data
    assert b'd3.drag' in resp.data
    assert b'legend' in resp.data
    assert b"n.type === 'object' && n.properties" in resp.data
    assert b'zoom.transform' in resp.data


def test_navbar_updates_with_schema_links(app, client):
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
    resp = client.get('/parametres')
    assert b'/docx_schema/' not in resp.data
    resp = client.post('/docx_to_schema/validate', json={'schema': {'title': 'Link', 'type': 'object'}, 'markdown': '# md'})
    page_id = resp.get_json()['page_id']
    resp = client.get('/parametres')
    assert f'/docx_schema/{page_id}'.encode() in resp.data


def test_docx_schema_management(app, client):
    with app.app_context():
        admin = User(
            username='admin6',
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
    # Create schema page
    resp = client.post('/docx_to_schema/validate', json={'schema': {'title': 'Manage', 'type': 'object'}, 'markdown': '# md'})
    page_id = resp.get_json()['page_id']
    # List page includes it
    resp = client.get('/docx_schema')
    assert b'>Manage<' in resp.data
    # Edit schema
    resp = client.post(f'/docx_schema/{page_id}/edit', json={'schema': {'title': 'Updated', 'type': 'object'}})
    assert resp.status_code == 200
    resp = client.get(f'/docx_schema/{page_id}')
    assert b'Updated' in resp.data
    assert b'id="schemaResultMarkdown"' in resp.data
    # View JSON
    resp = client.get(f'/docx_schema/{page_id}/json')
    assert b'Updated' in resp.data
    # Delete
    resp = client.post(f'/docx_schema/{page_id}/delete')
    assert resp.status_code == 302
    resp = client.get('/docx_schema')
    assert b'>Manage<' not in resp.data


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
    assert b'DOCX \xe2\x86\x92 JSON' in resp.data
    assert b'Prompt syst' in resp.data
    assert b'Mod' in resp.data
    assert b'Niveau de raisonnement' in resp.data
    assert b'Verbosit' in resp.data
    assert 'Propose un schéma JSON simple'.encode('utf-8') in resp.data


def test_docx_schema_preview_buttons_and_lists(app, client):
    with app.app_context():
        admin = User(
            username='array_admin',
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
    schema = {
        'title': 'ArraySample',
        'type': 'object',
        'properties': {
            'items': {
                'type': 'array',
                'items': {'type': 'string', 'title': 'It'}
            }
        }
    }
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md\n- a'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    resp = client.get(f'/docx_schema/{page_id}')
    data = resp.data
    assert b'id="schemaImportBtn"' in data
    assert b'id="schemaImproveBtn"' in data
    assert b'id="schemaGenerateBtn"' in data
    assert b'id="schemaExportBtn"' in data
    assert b'add-array-item' in data
    assert b'add-list-item' in data


def test_docx_schema_preview_plan_form(app, client):
    with app.app_context():
        admin = User(
            username='plan_admin',
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
    schema = {
        'title': 'Form',
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'title': 'Nom'},
            'tags': {'type': 'array', 'items': {'type': 'string'}}
        }
    }
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    resp = client.get(f'/docx_schema/{page_id}')
    data = resp.data
    assert b'id="planCadreForm"' in data
    assert b'id="planCadreSaveBtn"' in data
    assert b'add-form-array-item' in data


def test_docx_schema_preview_plan_form_order_and_nested(app, client):
    with app.app_context():
        admin = User(
            username='plan_order_admin',
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
    schema = {
        'title': 'Form',
        'type': 'object',
        'properties': {
            'section': {
                'title': 'Section',
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'title': {'type': 'string', 'title': 'Titre'},
                        'notes': {'type': 'array', 'items': {'type': 'string', 'title': 'Note'}}
                    }
                }
            },
            'summary': {'type': 'string', 'title': 'Résumé'}
        }
    }
    markdown = '## Section\n## Résumé'
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': markdown})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    resp = client.get(f'/docx_schema/{page_id}')
    data = resp.data.decode('utf-8')
    assert 'markdownOrder' in data
    assert 'position-absolute top-0 end-0 remove-form-array-item' in data
    assert 'Section' in data

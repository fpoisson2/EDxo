from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel
from html import unescape


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
    assert b'id="planCadreForm"' in resp.data
    assert b'id="actionBar"' in resp.data
    assert b'id="planCadreAccordion"' in resp.data
    assert b'id="schemaEditBtn"' not in resp.data
    assert b'id="schemaResultMarkdown"' not in resp.data
    assert b'id="schemaAccordion"' not in resp.data
    # JSON page now holds preview details
    resp_json = client.get(f'/docx_schema/{page_id}/json')
    assert resp_json.status_code == 200
    assert b'id="schemaEditBtn"' in resp_json.data
    assert b'id="schemaResultMarkdown"' in resp_json.data
    assert b'id="schemaAccordion"' in resp_json.data
    assert b'd3.tree' in resp_json.data
    assert b'd3.drag' in resp_json.data
    assert b'legend' in resp_json.data
    assert b"n.type === 'object' && n.properties" in resp_json.data
    assert b'zoom.transform' in resp_json.data


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
    # Rename schema
    resp = client.post(f'/docx_schema/{page_id}/rename', json={'title': 'Renamed'})
    assert resp.status_code == 200
    resp = client.get('/docx_schema')
    assert b'>Renamed<' in resp.data
    assert b'>Manage<' not in resp.data
    # Edit schema
    resp = client.post(f'/docx_schema/{page_id}/edit', json={'schema': {'title': 'Updated', 'type': 'object'}})
    assert resp.status_code == 200
    resp = client.get(f'/docx_schema/{page_id}')
    assert b'Updated' in resp.data
    assert b'id="schemaResultMarkdown"' not in resp.data
    resp_json = client.get(f'/docx_schema/{page_id}/json')
    assert b'Updated' in resp_json.data
    assert b'id="schemaResultMarkdown"' in resp_json.data
    # Delete
    resp = client.post(f'/docx_schema/{page_id}/delete')
    assert resp.status_code == 302
    resp = client.get('/docx_schema')
    assert b'>Updated<' not in resp.data


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
    # Array/list controls are now on the JSON page
    resp_json = client.get(f'/docx_schema/{page_id}/json')
    json_data = resp_json.data
    assert b'add-array-item' in json_data
    assert b'add-list-item' in json_data


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
    assert b'id="actionBar"' in data
    assert b'id="floatingSaveBtn"' in data
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
            'summary': {'type': 'string', 'title': 'Résumé'},
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
            }
        }
    }
    markdown = '## Section\n- Titre\n- Note\n## Résumé'
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': markdown})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    resp = client.get(f'/docx_schema/{page_id}')
    data = unescape(resp.data.decode('utf-8'))
    assert 'markdownOrderMap' in data
    assert 'buildMarkdownOrderMap' in data
    assert 'markdownOrderMap = buildMarkdownOrderMap(markdownData);' in data
    assert 'path.replace(/\\[[0-9]+\\]/g, \'\')' in data
    assert 'getMdOrder(' in data
    assert 'getMarkdownIndex' in data
    assert 'normalizedMarkdown' in data
    assert 'position-absolute top-0 end-0 remove-form-array-item' in data
    assert 'normalizeName(' in data


def test_markdown_plain_text_ordering():
    import unicodedata, re

    def normalize_name(s):
        s = unicodedata.normalize('NFD', s or '')
        s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
        s = re.sub(r'[^a-zA-Z0-9]+', ' ', s)
        return s.strip().lower()

    def sort_by_markdown(schema, markdown):
        norm_md = normalize_name(markdown)
        entries = list(schema['properties'].items())
        def position(item):
            key, val = item
            name = normalize_name(val.get('title') or key)
            idx = norm_md.find(name)
            return idx if idx != -1 else float('inf')
        entries.sort(key=position)
        return [k for k, _ in entries]

    schema = {
        'title': 'Plain',
        'type': 'object',
        'properties': {
            'first': {'type': 'string', 'title': 'Premier'},
            'second': {'type': 'string', 'title': 'Deuxième'},
        }
    }
    markdown = 'Deuxième\nPremier'
    ordered = sort_by_markdown(schema, markdown)
    assert ordered == ['second', 'first']


def test_markdown_nested_array_ordering():
    import unicodedata, re

    def normalize_name(s):
        s = unicodedata.normalize('NFD', s or '')
        s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
        s = re.sub(r'[^a-zA-Z0-9]+', ' ', s)
        return s.strip().lower()

    def build_markdown_order_map(markdown):
        lines = markdown.splitlines()
        order = {'root': []}
        headings = []
        list_stack = []
        for line in lines:
            m = re.match(r'^(#+)\s+(.*)', line)
            if m:
                depth = len(m.group(1))
                text = normalize_name(m.group(2))
                if len(headings) < depth - 1:
                    headings.extend([None] * (depth - 1 - len(headings)))
                headings = headings[:depth - 1]
                headings.append(text)
                list_stack = []
                parent = '.'.join(h for h in headings[:-1] if h) or 'root'
                order.setdefault(parent, []).append(text)
                continue
            m = re.match(r'^(\s*)[-*+]\s+(.*)', line)
            if m:
                indent = len(m.group(1)) // 2
                text = normalize_name(m.group(2))
                list_stack = list_stack[:indent]
                parent = '.'.join(h for h in headings + list_stack if h) or 'root'
                order.setdefault(parent, []).append(text)
                list_stack.append(text)
        return order

    def sort_props(props, md_map, path):
        entries = list(props.items())
        md_order = md_map.get(path, [])
        def pos(item):
            key, val = item
            name = normalize_name(val.get('title') or key)
            try:
                return md_order.index(name)
            except ValueError:
                return float('inf')
        entries.sort(key=pos)
        return [k for k, _ in entries]

    schema = {
        'title': 'Root',
        'type': 'object',
        'properties': {
            'section': {
                'title': 'Section',
                'type': 'array',
                'items': {
                    'title': 'Element',
                    'type': 'object',
                    'properties': {
                        'title': {'type': 'string', 'title': 'Titre'},
                        'note': {'type': 'string', 'title': 'Note'},
                    }
                }
            },
            'summary': {'type': 'string', 'title': 'Résumé'}
        }
    }

    markdown = '## Section\n- Element\n  - Titre\n  - Note\n## Résumé'
    md_map = build_markdown_order_map(markdown)
    root_order = sort_props(schema['properties'], md_map, 'root')
    assert root_order == ['section', 'summary']
    item_props = schema['properties']['section']['items']['properties']
    nested_order = sort_props(item_props, md_map, 'section.element')
    assert nested_order == ['title', 'note']

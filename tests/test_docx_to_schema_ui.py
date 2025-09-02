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


def test_stringified_schema_is_parsed_server_and_client(app, client):
    from src.app.models import User, db, OpenAIModel
    from werkzeug.security import generate_password_hash
    import json as _json
    with app.app_context():
        admin = User(
            username='string_schema_admin',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True

    obj = { 'title': 'Str', 'type': 'object', 'properties': { 'name': {'type':'string','title':'Nom'} } }
    wrapped = { 'schema': _json.dumps(obj) }

    # validate endpoint should parse stringified schema
    resp = client.post('/docx_to_schema/validate', json={'schema': wrapped, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    # JSON page renders tree/graph
    resp_json = client.get(f'/docx_schema/{page_id}/json')
    assert resp_json.status_code == 200
    data = resp_json.data.decode('utf-8')
    assert 'schemaData = ' in data
    # client also tries to parse string if any
    assert 'typeof schemaData === \u0027string\u0027' in data


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
    assert b'add-item-btn' in data


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
    assert 'remove-item-btn' in data
    assert 'normalizeName(' in data


def test_docx_schema_handles_defs_and_refs_in_preview_and_json(app, client):
    from src.app.models import User, db, OpenAIModel
    from werkzeug.security import generate_password_hash
    with app.app_context():
        admin = User(
            username='defs_admin',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True

    # Schema using $defs and $ref
    schema = {
        'title': 'Plan Défs',
        'type': 'object',
        '$defs': {
            'phase': {
                'type': 'object',
                'title': 'Phase',
                'properties': {
                    'titre': {'type': 'string', 'title': 'Titre de la phase'},
                    'periode': {'type': 'string', 'title': 'Période'}
                }
            }
        },
        'properties': {
            'phases': {
                'type': 'array',
                'title': 'Phases',
                'items': {'$ref': '#/$defs/phase'}
            },
            'resume': {'type': 'string', 'title': 'Résumé'}
        }
    }

    # Save and open preview page (form)
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '## Phases\n- Phase\n  - Titre de la phase\n  - Période\n## Résumé'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']

    # The preview page should embed JS helpers that resolve $ref with $defs
    resp_prev = client.get(f'/docx_schema/{page_id}')
    assert resp_prev.status_code == 200
    html_prev = unescape(resp_prev.data.decode('utf-8'))
    assert 'normalizePlanSchema' in html_prev
    assert 'resolveRef' in html_prev  # ensure client can resolve $ref
    assert 'items' in html_prev and 'add-item-btn' in html_prev

    # The JSON page should also include the resolver and graph builders
    resp_json = client.get(f'/docx_schema/{page_id}/json')
    assert resp_json.status_code == 200
    html_json = unescape(resp_json.data.decode('utf-8'))
    # Embedded schema should still contain $defs for reference
    assert '$defs' in html_json and '"$ref": "#/$defs/phase"' in html_json
    # And the page code should contain the $ref resolver and renderers
    assert 'normalizePlanSchema' in html_json
    assert 'resolveRef' in html_json
    assert 'renderSchemaGraph' in html_json


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


def test_docx_schema_preview_accordions_only_top_level(app, client):
    from src.app.models import User, db, OpenAIModel
    from werkzeug.security import generate_password_hash
    with app.app_context():
        admin = User(
            username='accordions_admin',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True

    # Schema with nested objects; only root-level properties should become accordions
    schema = {
        'title': 'Nesting',
        'type': 'object',
        'properties': {
            'p1': {
                'title': 'P1',
                'type': 'object',
                'properties': {
                    'p1a': {'type': 'string', 'title': 'P1A'},
                    'p1b': {
                        'title': 'P1B',
                        'type': 'object',
                        'properties': {
                            'leaf': {'type': 'string', 'title': 'Leaf'}
                        }
                    }
                }
            },
            'p2': {
                'title': 'P2',
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'x': {'type': 'string', 'title': 'X'},
                        'y': {'type': 'number', 'title': 'Y'}
                    }
                }
            },
            'p3': {'type': 'string', 'title': 'P3'}
        }
    }

    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    resp = client.get(f'/docx_schema/{page_id}')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    # Verify JS renders accordions only at root level for objects
    assert "depth === 0" in html
    assert "collapse.setAttribute('data-bs-parent', '#planCadreAccordion')" in html
    # Nested sections render as simple groups (no nested accordion-button collapsed)
    assert 'accordion-button collapsed' not in html
    # Grouping class for nested sections present in script
    assert "border rounded p-2 mb-3" in html
    # Ensure code passes suppressLegend to avoid duplicating header title inside body
    assert '{ suppressLegend: true' in html or 'suppressLegend: true' in html


def test_docx_schema_preview_nested_array_becomes_accordion_and_no_title_dup(app, client):
    from src.app.models import User, db, OpenAIModel
    from werkzeug.security import generate_password_hash
    with app.app_context():
        admin = User(
            username='nested_list_admin',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True

    # Array (sections) with an inner array (notes) inside items -> inner should be an accordion
    schema = {
        'title': 'Doc',
        'type': 'object',
        'properties': {
            'sections': {
                'title': 'Sections',
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'title': {'type': 'string', 'title': 'Titre'},
                        'notes': {
                            'title': 'Notes',
                            'type': 'array',
                            'items': {'type': 'string', 'title': 'Note'}
                        }
                    }
                }
            }
        }
    }

    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    resp = client.get(f'/docx_schema/{page_id}')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    # The script contains logic to detect nested lists and render as accordion
    assert 'hasNestedList' in html
    # In accordion body, we do not repeat the title label for the list
    # We rely on suppressLabel/showLabel flags to avoid duplication
    assert 'showLabel' in html and 'suppressLabel' in html
    # Ensure itemPath includes normalized itemName so nested order can be mapped against markdown
    assert 'const itemName = normalizeName(schema.items.title || schema.title || path);' in html
    assert 'const itemPath = path === \u0027root\u0027 ? itemName : `${path}.${itemName}`;' in html


def test_docx_schema_preview_per_item_accordion_for_capacites_phases_plan_eval(app, client):
    from src.app.models import User, db, OpenAIModel
    from werkzeug.security import generate_password_hash
    with app.app_context():
        admin = User(
            username='peritem_admin',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True

    schema = {
        'title': 'Doc',
        'type': 'object',
        'properties': {
            'partie3': {
                'type': 'object',
                'title': 'Partie 3 : Résultats visés',
                'properties': {
                    'capacites': {
                        'title': 'Capacités (objectifs intermédiaires)',
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'title': 'Capacité',
                            'properties': {
                                'titre': {'type': 'string', 'title': 'Titre de la capacité'},
                                'description': {'type': 'string', 'title': 'Description'}
                            }
                        }
                    }
                }
            },
            'partie4': {
                'type': 'object',
                'title': "Partie 4 : Indications relatives à l’organisation de l’apprentissage et de l’enseignement",
                'properties': {
                    'phases': {
                        'title': 'Organisation du cours par phases',
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'title': 'Phase',
                            'properties': {
                                'titre': {'type': 'string', 'title': 'Titre de la phase'},
                                'periode': {'type': 'string', 'title': 'Période'}
                            }
                        }
                    }
                }
            },
            'partie5': {
                'type': 'object',
                'title': "Partie 5 : Indications relatives à l’évaluation des apprentissages",
                'properties': {
                    'planGeneralDEvaluationSommative': {
                        'title': 'Tableau des paramètres de l’évaluation sommative – Plan général d’évaluation sommative',
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'title': 'Évaluation par capacité',
                            'properties': {
                                'capacite': {'type': 'string', 'title': 'Capacité'},
                                'ponderation': {'type': 'string', 'title': 'Pondération'}
                            }
                        }
                    }
                }
            }
        }
    }
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    resp = client.get(f'/docx_schema/{page_id}')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    # The JS should include the per-item accordion logic for arrays of objects (generic)
    assert 'shouldAccordionPerItem' in html
    assert "schema.items && schema.items.type === 'object'" in html
    # Remove button should exist for each accordion item
    assert 'remove-item-btn' in html
    # A label heading is added before the per-item accordion
    assert 'label.className = \'form-label fw-bold\'' in html


def test_docx_schema_preview_no_page_title_duplication(app, client):
    from src.app.models import User, db, OpenAIModel
    from werkzeug.security import generate_password_hash
    with app.app_context():
        admin = User(
            username='no_title_dup_admin',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True

    schema = {
        'title': 'Plan-cadre',
        'type': 'object',
        'properties': {
            'section': {
                'title': 'Plan cadre',  # Intentionnellement identique au titre de page (variation)
                'type': 'object',
                'properties': {
                    'field': {'type': 'string', 'title': 'Champ'}
                }
            }
        }
    }
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    resp = client.get(f'/docx_schema/{page_id}')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    # The template avoids duplicating the section H2 when it matches the page title (normalized)
    assert '<h2 class="h4 mb-3">Plan cadre</h2>' not in html
    # JS also avoids label/legend duplication inside the form
    assert 'const pageTitle = (schemaData && (schemaData.title || schemaData.titre)) || \u0027\u0027;' in html
    assert 'legendText && legendText !== pageTitle' in html
    assert 'if (labelText && labelText !== pageTitle)' in html

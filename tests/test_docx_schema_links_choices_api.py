from werkzeug.security import generate_password_hash
from src.app.models import User, db, DocxSchemaPage, DocxSchemaEntry


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def create_admin(app):
    with app.app_context():
        admin = User(
            username='admin_links_choices',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.commit()
        return admin.id


def test_docx_schema_links_endpoint_lists_source_links(app, client):
    admin_id = create_admin(app)
    _login(client, admin_id)
    # Create two pages
    with app.app_context():
        p1 = DocxSchemaPage(title='Src', json_schema={'title': 'Src', 'type': 'object', 'properties': {'ingredients': {'type': 'array', 'items': {'type': 'string'}}}})
        p2 = DocxSchemaPage(title='Tgt', json_schema={'title': 'Tgt', 'type': 'object', 'properties': {'ingredients': {'type': 'array', 'items': {'type': 'string'}}}})
        db.session.add_all([p1, p2]); db.session.commit()
        src_id, tgt_id = p1.id, p2.id

    # Create a link via settings API (already existing route)
    payload = {
        'source_page_id': src_id,
        'source_pointer': '#/properties/ingredients',
        'relation_type': 'utilise',
        'target_page_id': tgt_id,
        'target_pointer': '#/properties/ingredients/items',
        'comment': 'Use ingredients from target'
    }
    r = client.post('/settings/schemas/links', json=payload)
    assert r.status_code == 201
    link_id = r.get_json()['link']['id']

    # New endpoint: list links for source page
    r2 = client.get(f'/docx_schema/{src_id}/links')
    assert r2.status_code == 200
    links = r2.get_json()['links']
    assert any(l['id'] == link_id for l in links)


def test_docx_schema_choices_from_enum_and_entries_with_filter(app, client):
    admin_id = create_admin(app)
    _login(client, admin_id)
    # Target page with enum on property
    with app.app_context():
        p_enum = DocxSchemaPage(
            title='Enum',
            json_schema={
                'title': 'Enum', 'type': 'object',
                'properties': {
                    'ingredient': {'type': 'string', 'enum': ['sucre', 'sel']}
                }
            }
        )
        db.session.add(p_enum); db.session.commit()
        enum_id = p_enum.id

    r = client.get(f'/docx_schema/{enum_id}/choices?pointer=%23/properties/ingredient')
    assert r.status_code == 200
    j = r.get_json()
    assert j['source'] == 'enum'
    labels = [c['label'] for c in j['choices']]
    assert set(labels) == {'sucre', 'sel'}

    # Target page aggregating from entries (array of strings)
    with app.app_context():
        p_items = DocxSchemaPage(
            title='Items',
            json_schema={'title': 'Items', 'type': 'object', 'properties': {'ingredients': {'type': 'array', 'items': {'type': 'string'}}}}
        )
        db.session.add(p_items); db.session.commit()
        items_id = p_items.id
        # Entries: one with sucre/sel, one with poivre
        e1 = DocxSchemaEntry(page_id=items_id, data={'ingredients': ['sucre', 'sel']})
        e2 = DocxSchemaEntry(page_id=items_id, data={'ingredients': ['poivre']})
        db.session.add_all([e1, e2]); db.session.commit()
        e1_id = e1.id

    # All entries
    r2 = client.get(f'/docx_schema/{items_id}/choices?pointer=%23/properties/ingredients/items')
    assert r2.status_code == 200
    all_choices = [c['value'] for c in r2.get_json()['choices']]
    assert set(all_choices) == {'sucre', 'sel', 'poivre'}

    # Filter by entry
    r3 = client.get(f'/docx_schema/{items_id}/choices?pointer=%23/properties/ingredients/items&target_entry_id={e1_id}')
    assert r3.status_code == 200
    filtered = [c['value'] for c in r3.get_json()['choices']]
    assert set(filtered) == {'sucre', 'sel'}

    # Target page aggregating from entries (array of objects, pick specific property via items/properties/<key>)
    with app.app_context():
        p_objs = DocxSchemaPage(
            title='Objs',
            json_schema={'title': 'Objs', 'type': 'object', 'properties': {
                'competences': {
                    'type': 'array', 'items': {'type': 'object', 'properties': {'code': {'type': 'string'}, 'lib': {'type': 'string'}}}
                }
            }}
        )
        db.session.add(p_objs); db.session.commit()
        obj_id = p_objs.id
        e1 = DocxSchemaEntry(page_id=obj_id, data={'competences': [{'code': 'C1', 'lib': 'A'}, {'code': 'C2', 'lib': 'B'}]})
        e2 = DocxSchemaEntry(page_id=obj_id, data={'competences': [{'code': 'C3', 'lib': 'C'}]})
        db.session.add_all([e1, e2]); db.session.commit()
    r4 = client.get(f'/docx_schema/{obj_id}/choices?pointer=%23/properties/competences/items/properties/code')
    assert r4.status_code == 200
    codes = {c['value'] for c in r4.get_json()['choices']}
    assert codes == {'C1', 'C2', 'C3'}

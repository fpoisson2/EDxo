from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_mapping_page_renders_and_saves_mappings(app, client):
    with app.app_context():
        admin = User(
            username='admin_map',
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
    schema = {
        'title': 'MapPage',
        'type': 'object',
        'properties': {
            'sessions': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'cours': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'code': {'type': 'string'}
                                }
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

    # GET mapping page
    resp_map = client.get(f'/docx_schema/{page_id}/mapping')
    assert resp_map.status_code == 200
    data = resp_map.data
    assert b'id="mappingSaveBtn"' in data
    assert b'id="schemaPointerBrowseModal"' in data

    # Save one mapping
    pointer = '#/properties/sessions/items/properties/cours/items/properties/code'
    resp_save = client.post(f'/docx_schema/{page_id}/mapping', json={'mappings': [{'section_key': 'cours.code', 'pointer': pointer}]})
    assert resp_save.status_code == 200
    assert resp_save.get_json()['success'] is True

    # Fetch mapping data back
    resp_data = client.get(f'/docx_schema/{page_id}/mapping/data')
    assert resp_data.status_code == 200
    payload = resp_data.get_json()
    found = [m for m in payload['mappings'] if m['section_key'] == 'cours.code']
    assert found and found[0]['pointer'] == pointer

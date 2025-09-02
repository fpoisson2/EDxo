from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_entries_list_header_has_mapping_link(app, client):
    with app.app_context():
        admin = User(
            username='admin_entries_map_link',
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

    schema = {'title': 'Entries', 'type': 'object'}
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']

    resp_list = client.get(f'/docx_schema/{page_id}/entries/list')
    assert resp_list.status_code == 200
    html = resp_list.data
    expected_href = f'/docx_schema/{page_id}/mapping'.encode()
    assert expected_href in html
    assert b'Associer sections' in html


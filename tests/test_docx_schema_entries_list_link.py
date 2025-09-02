from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_entries_list_has_programme_view_link(app, client):
    with app.app_context():
        admin = User(
            username='admin_entries_list',
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

    # Create schema page and one entry
    schema = {'title': 'Entries Page', 'type': 'object'}
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']
    entry_data = {'title': 'Entrée 1', 'sessions': []}
    resp_entry = client.post(f'/docx_schema/{page_id}/entries', json={'data': entry_data})
    assert resp_entry.status_code == 201
    entry_id = resp_entry.get_json()['entry_id']

    resp_list = client.get(f'/docx_schema/{page_id}/entries/list')
    assert resp_list.status_code == 200
    html = resp_list.data
    # Visionner button exists and targets programme_view with entry_id
    expected_href = f'/docx_schema/{page_id}/programme_view?entry_id={entry_id}'.encode()
    assert expected_href in html


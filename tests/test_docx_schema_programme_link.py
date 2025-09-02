from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_docx_schema_page_has_programme_view_link(app, client):
    with app.app_context():
        admin = User(
            username='admin_prog_link',
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

    # Create a minimal schema page
    schema = {'title': 'Linkable', 'type': 'object'}
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']

    resp_page = client.get(f'/docx_schema/{page_id}')
    assert resp_page.status_code == 200
    html = resp_page.data
    # Button exists and links to programme_view
    assert b'id="schemaProgrammeViewBtn"' in html
    expected_href = f'/docx_schema/{page_id}/programme_view'.encode()
    assert expected_href in html


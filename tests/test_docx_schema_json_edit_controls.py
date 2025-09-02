from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def setup_admin_and_schema(app, client):
    with app.app_context():
        admin = User(
            username='admin_jsonui',
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
    resp = client.post('/docx_to_schema/validate', json={'schema': {'title': 'UIEdit', 'type': 'object', 'properties': {}}, 'markdown': '# md'})
    page_id = resp.get_json()['page_id']
    return admin_id, page_id


def test_json_page_exposes_edit_controls_strings(app, client):
    _, page_id = setup_admin_and_schema(app, client)
    r = client.get(f'/docx_schema/{page_id}/json')
    assert r.status_code == 200
    body = r.data
    # Strings that indicate the presence of UI edit controls in the JS/HTML
    assert b'Renommer le sch\xc3\xa9ma' in body
    assert b'Ajouter un champ' in body
    assert b'Renommer' in body
    assert b'Supprimer' in body
    assert b'Modifier type' in body
    assert b'Modifier description' in body
    assert b'Modifier titre' in body
    assert b'D\xc3\xa9placer' in body or b'Deplacer' in body
    assert b'Ajouter objet' in body
    assert b'Ajouter liste d\xe2\x80\x99objets' in body or b"Ajouter liste d'objets" in body
    assert b'Ajouter liste de cha\xc3\xaenes' in body or b'Ajouter liste de cha' in body
    assert b'Modifier type des \xc3\xa9l\xc3\xa9ments' in body or b"Modifier type des elements" in body
    assert b'Modifier titre des \xc3\xa9l\xc3\xa9ments' in body or b"Modifier titre des elements" in body

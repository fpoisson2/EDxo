from werkzeug.security import generate_password_hash
from src.app.models import User, db


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_relations_help_present_on_page(app, client):
    with app.app_context():
        admin = User(
            username='admin_help',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    _login(client, admin_id)
    r = client.get('/settings/schemas')
    assert r.status_code == 200
    body = r.data
    # Ensure help section lists the 4 relations
    assert b'H\xc3\xa9rite de' in body
    assert b'D\xc3\xa9rive de' in body
    assert b'\xc3\x89quivalent \xc3\xa0' in body
    assert b'Utilise' in body


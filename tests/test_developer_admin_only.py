import pytest
from werkzeug.security import generate_password_hash


def get_model_by_name(model_name, db):
    for mapper in db.Model.registry.mappers:
        if mapper.class_.__name__ == model_name:
            return mapper.class_
    return None


def create_user(app, username, role='user', first_connexion=False):
    with app.app_context():
        from src.app import db
        User = get_model_by_name('User', db)
        user = User(
            username=username,
            password=generate_password_hash('password'),
            role=role,
            credits=0.0,
            is_first_connexion=first_connexion is True and True or False,
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def login_client(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_developer_page_admin_only_redirect_for_user(client, app):
    # Non-admin should be redirected away from /settings/developer
    user_id = create_user(app, 'basic_user', role='user', first_connexion=False)
    login_client(client, user_id)

    resp = client.get('/settings/developer', follow_redirects=False)
    assert resp.status_code in (301, 302)
    with app.app_context():
        from flask import url_for
        assert resp.headers['Location'].endswith(url_for('main.index', _external=False))


def test_developer_page_admin_can_generate_token(client, app):
    # Admin can access page and generate API token
    admin_id = create_user(app, 'super_admin', role='admin', first_connexion=False)
    login_client(client, admin_id)

    # Access page
    resp = client.get('/settings/developer')
    assert resp.status_code == 200
    assert b'Espace d\xe9veloppeur' in resp.data or b'Espace d\xc3\xa9veloppeur' in resp.data

    # Post to generate token
    resp2 = client.post('/settings/developer', data={'ttl': 1, 'submit': 'G\xc3\xa9n\xc3\xa9rer un jeton'}, follow_redirects=True)
    assert resp2.status_code == 200

    # Verify token persisted on the user
    with app.app_context():
        from src.app import db
        User = get_model_by_name('User', db)
        user = db.session.get(User, admin_id)
        assert user.api_token is not None
        assert len(user.api_token) >= 16  # hex string


def test_parametres_sidebar_hides_developer_for_non_admin(client, app):
    # Non-admin: sidebar should NOT show the developer space link
    user_id = create_user(app, 'normal', role='user', first_connexion=False)
    login_client(client, user_id)
    resp = client.get('/settings/parametres')
    assert resp.status_code == 200
    assert b'/settings/developer' not in resp.data

import pytest
from flask import url_for
from werkzeug.security import generate_password_hash
from utils.decorator import roles_required
from uuid import uuid4


def get_model_by_name(model_name, db):
    for mapper in db.Model.registry.mappers:
        if mapper.class_.__name__ == model_name:
            return mapper.class_
    return None


@pytest.fixture
def protected_url(app):
    path = f"/role-protected-{uuid4().hex}"
    endpoint = f"role_protected_{uuid4().hex}"

    @app.route(path, endpoint=endpoint)
    @roles_required('admin')
    def role_protected():
        return 'restricted', 200

    return path


def create_user(app, username, role):
    with app.app_context():
        from src.app import db
        User = get_model_by_name('User', db)
        hashed = generate_password_hash('password')
        user = User(username=username, password=hashed, role=role, credits=0.0)
        db.session.add(user)
        db.session.commit()
        return user.id


def login_client(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_redirect_for_non_admin(client, app, protected_url):
    user_id = create_user(app, 'basic', 'user')
    login_client(client, user_id)

    response = client.get(protected_url, follow_redirects=False)
    assert response.status_code in (301, 302)
    with app.app_context():
        assert response.headers['Location'].endswith(url_for('main.index', _external=False))


def test_access_for_admin(client, app, protected_url):
    admin_id = create_user(app, 'super', 'admin')
    login_client(client, admin_id)

    response = client.get(protected_url)
    assert response.status_code == 200
    assert b'restricted' in response.data

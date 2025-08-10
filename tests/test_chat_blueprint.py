from werkzeug.security import generate_password_hash


def get_model_by_name(model_name, db):
    for mapper in db.Model.registry.mappers:
        if mapper.class_.__name__ == model_name:
            return mapper.class_
    return None


def fake_requests_post(url, data, **kwargs):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True, "score": 1.0}

    return FakeResponse()


def test_chat_route_protected(client):
    response = client.get('/chat')
    assert response.status_code in (301, 302)
    assert 'login' in response.headers.get('Location', '')


def test_chat_page_logged_in(client, app, monkeypatch):
    monkeypatch.setattr('requests.post', fake_requests_post)

    with app.app_context():
        from src.app import db

        User = get_model_by_name('User', db)
        assert User is not None
        if User.query.filter_by(username='admin').first() is None:
            user = User(
                username='admin',
                password=generate_password_hash('adminpass'),
                role='admin',
                credits=100.0,
                is_first_connexion=False,
            )
            db.session.add(user)
            db.session.commit()

    login_data = {
        'username': 'admin',
        'password': 'adminpass',
        'recaptcha_token': 'dummy',
        'submit': 'Se connecter',
    }
    client.post('/login', data=login_data, follow_redirects=True)

    response = client.get('/chat')
    assert response.status_code == 200
    assert b'chat-container' in response.data

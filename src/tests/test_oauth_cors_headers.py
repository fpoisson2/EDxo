import pytest


@pytest.fixture
def app():
    from src.app import create_app, db
    app = create_app(testing=True)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_register_cors_preflight_and_response(client):
    # Preflight
    pre = client.open('/register', method='OPTIONS', headers={'Origin': 'http://localhost:6274'})
    assert pre.status_code == 204
    assert pre.headers.get('Access-Control-Allow-Origin') == '*'
    assert 'POST' in (pre.headers.get('Access-Control-Allow-Methods') or '')

    # Actual registration
    resp = client.post(
        '/register',
        json={
            'client_name': 'web-client',
            'redirect_uris': ['https://example.com/cb'],
            'token_endpoint_auth_method': 'none',
        },
        headers={'Origin': 'http://localhost:6274'},
    )
    assert resp.status_code == 201
    assert resp.headers.get('Access-Control-Allow-Origin') == '*'
    data = resp.get_json()
    assert data.get('client_id')


def test_token_cors_preflight_and_response(client):
    # Register a client first
    reg = client.post(
        '/register',
        json={
            'client_name': 'web-client',
            'redirect_uris': ['https://example.com/cb'],
            'token_endpoint_auth_method': 'none',
        },
    )
    client_id = reg.get_json()['client_id']

    # Preflight
    pre = client.open('/token', method='OPTIONS', headers={'Origin': 'http://localhost:6274'})
    assert pre.status_code == 204
    assert pre.headers.get('Access-Control-Allow-Origin') == '*'
    assert 'POST' in (pre.headers.get('Access-Control-Allow-Methods') or '')

    # Actual token request
    tok = client.post(
        '/token',
        data={
            'client_id': client_id,
            'grant_type': 'client_credentials',
            'ttl': 3600,
        },
        headers={'Origin': 'http://localhost:6274'},
    )
    assert tok.status_code == 200
    assert tok.headers.get('Access-Control-Allow-Origin') == '*'
    assert tok.get_json().get('access_token')

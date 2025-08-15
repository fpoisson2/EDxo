from src.app import db
from src.app.models import Programme, Department, OAuthClient, User


def setup_data(app):
    with app.app_context():
        dept = Department(nom="Dep")
        db.session.add(dept)
        db.session.commit()
        programme = Programme(nom="Prog", department_id=dept.id)
        db.session.add(programme)
        db.session.commit()
        return programme.id


def test_oauth_registration_and_access(app, client):
    prog_id = setup_data(app)

    resp = client.post('/register', json={'name': 'client'})
    assert resp.status_code == 201
    creds = resp.get_json()
    client_id = creds['client_id']
    client_secret = creds['client_secret']

    resp = client.post('/token', json={'client_id': client_id, 'client_secret': client_secret, 'ttl': 3600})
    assert resp.status_code == 200
    token = resp.get_json()['access_token']

    headers = {'Authorization': f'Bearer {token}'}
    resp = client.get('/api/programmes', headers=headers)
    assert resp.status_code == 200
    assert any(p['id'] == prog_id for p in resp.get_json())

    bad = {'Authorization': 'Bearer wrong'}
    assert client.get('/api/programmes', headers=bad).status_code == 401

    meta = client.get('/.well-known/oauth-authorization-server')
    assert meta.status_code == 200
    data = meta.get_json()
    assert data['token_endpoint'].endswith('/token')
    assert data['registration_endpoint'].endswith('/register')


def test_authorization_code_flow(app, client):
    prog_id = setup_data(app)

    with app.app_context():
        client_obj = OAuthClient(
            client_id='cid',
            client_secret='secret',
            name='test',
            redirect_uri='https://example.com/cb',
        )
        db.session.add(client_obj)
        user = User(username='u', password='p')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    import hashlib, base64
    code_verifier = 'verifier123'
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()

    resp = client.get(
        '/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'cid',
            'redirect_uri': 'https://example.com/cb',
            'code_challenge': code_challenge,
        },
    )
    assert resp.status_code == 200

    resp = client.post(
        '/authorize?client_id=cid&redirect_uri=https://example.com/cb',
        data={'confirm': 'yes', 'code_challenge': code_challenge},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(resp.headers['Location'])
    code = parse_qs(parsed.query)['code'][0]

    token_resp = client.post(
        '/token',
        json={
            'grant_type': 'authorization_code',
            'code': code,
            'code_verifier': code_verifier,
            'client_id': 'cid',
            'client_secret': 'secret',
        },
    )
    assert token_resp.status_code == 200
    token = token_resp.get_json()['access_token']

    headers = {'Authorization': f'Bearer {token}'}
    resp = client.get('/api/programmes', headers=headers)
    assert resp.status_code == 200
    assert any(p['id'] == prog_id for p in resp.get_json())

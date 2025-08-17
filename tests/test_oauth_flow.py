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

    resp = client.post(
        '/token',
        data={
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'client_credentials',
            'ttl': 3600,
        },
    )
    assert resp.status_code == 200
    token = resp.get_json()['access_token']

    headers = {'Authorization': f'Bearer {token}'}
    resp = client.get('/api/programmes', headers=headers)
    assert resp.status_code == 200
    assert any(p['id'] == prog_id for p in resp.get_json())

    bad = {'Authorization': 'Bearer wrong'}
    unauthorized = client.get('/api/programmes', headers=bad)
    assert unauthorized.status_code == 401
    assert (
        'resource_metadata' in unauthorized.headers.get('WWW-Authenticate', '')
    )

    meta = client.get('/.well-known/oauth-authorization-server')
    assert meta.status_code == 200
    data = meta.get_json()
    assert data['token_endpoint'].endswith('/token')
    assert data['registration_endpoint'].endswith('/register')
    assert data['authorization_endpoint'].endswith('/authorize')
    assert data['response_types_supported'] == ['code']
    assert data['grant_types_supported'] == ['authorization_code', 'refresh_token']
    assert data['code_challenge_methods_supported'] == ['S256']
    assert data['token_endpoint_auth_methods_supported'] == ['none']

    res_meta = client.get('/.well-known/oauth-protected-resource')
    assert res_meta.status_code == 200
    res_data = res_meta.get_json()
    assert res_data['resource']
    assert res_data['authorization_servers'] == [res_data['resource']]


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

    app.config['WTF_CSRF_ENABLED'] = True

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
            'state': 'abc',
        },
    )
    assert resp.status_code == 200
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.data, 'html.parser')
    token = soup.find('input', {'name': 'csrf_token'})['value']

    resp = client.post(
        '/authorize?client_id=cid&redirect_uri=https://example.com/cb&state=abc',
        data={'confirm': 'yes', 'code_challenge': code_challenge, 'csrf_token': token},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(resp.headers['Location'])
    code = parse_qs(parsed.query)['code'][0]
    assert parse_qs(parsed.query)['state'][0] == 'abc'

    token_resp = client.post(
        '/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'code_verifier': code_verifier,
            'client_id': 'cid',
            'client_secret': 'secret',
            'redirect_uri': 'https://example.com/cb',
        },
    )
    assert token_resp.status_code == 200
    token = token_resp.get_json()['access_token']

    headers = {'Authorization': f'Bearer {token}'}
    resp = client.get('/api/programmes', headers=headers)
    assert resp.status_code == 200
    assert any(p['id'] == prog_id for p in resp.get_json())


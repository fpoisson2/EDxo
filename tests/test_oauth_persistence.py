import base64
import hashlib
from urllib.parse import urlparse, parse_qs

from src.app import db
from src.app.models import OAuthClient, User, OAuthAuthorizationCode


def test_auth_code_persist_and_one_time_use(app, client):
    # Arrange: create client and user
    with app.app_context():
        client_obj = OAuthClient(
            client_id='cidp',
            client_secret='secret',
            name='testp',
            redirect_uri='https://example.com/cb',
        )
        db.session.add(client_obj)
        user = User(username='up', password='pp')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    # Login user in test client
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    # Prepare PKCE
    code_verifier = 'verifier-persist-123'
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()

    # GET authorize (render form)
    resp = client.get(
        '/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'cidp',
            'redirect_uri': 'https://example.com/cb',
            'code_challenge': code_challenge,
        },
    )
    assert resp.status_code == 200

    # Extract CSRF token from form
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.data, 'html.parser')
    token = soup.find('input', {'name': 'csrf_token'})['value']

    # POST authorize to issue code (follow redirect disabled to capture Location)
    resp = client.post(
        '/authorize?client_id=cidp&redirect_uri=https://example.com/cb',
        data={'confirm': 'yes', 'code_challenge': code_challenge, 'csrf_token': token},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    parsed = urlparse(resp.headers['Location'])
    code = parse_qs(parsed.query)['code'][0]

    # Assert code persisted in DB before exchange
    with app.app_context():
        rec = OAuthAuthorizationCode.query.filter_by(code=code).first()
        assert rec is not None
        assert rec.client_id == 'cidp'

    # Exchange code for token
    token_resp = client.post(
        '/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'code_verifier': code_verifier,
            'client_id': 'cidp',
            'client_secret': 'secret',
            'redirect_uri': 'https://example.com/cb',
        },
    )
    assert token_resp.status_code == 200

    # Assert code invalidated (one-time use)
    with app.app_context():
        gone = OAuthAuthorizationCode.query.filter_by(code=code).first()
        assert gone is None


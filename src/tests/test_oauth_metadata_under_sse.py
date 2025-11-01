import pytest


@pytest.fixture
def app():
    from src.app import create_app
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


def test_oauth_metadata_under_sse_aliases(client):
    # Authorization server metadata under /sse should be reachable
    resp = client.get('/sse/.well-known/oauth-authorization-server')
    assert resp.status_code == 200
    data = resp.get_json()
    # CORS header for browser-based discovery
    assert resp.headers.get('Access-Control-Allow-Origin') == '*'
    issuer = data['issuer']
    assert issuer.startswith('http')
    assert data['authorization_endpoint'].startswith(issuer)
    assert data['token_endpoint'].startswith(issuer)
    assert data['registration_endpoint'].startswith(issuer)
    assert data['authorization_endpoint'].endswith('/authorize')
    assert data['token_endpoint'].endswith('/token')
    assert data['registration_endpoint'].endswith('/register')
    assert data['response_types_supported'] == ['code']
    assert data['grant_types_supported'] == ['authorization_code', 'refresh_token']
    assert data['code_challenge_methods_supported'] == ['S256']
    assert data['token_endpoint_auth_methods_supported'] == ['none']

    # Protected resource metadata under /sse should be reachable
    res_meta = client.get('/sse/.well-known/oauth-protected-resource')
    assert res_meta.status_code == 200
    rdata = res_meta.get_json()
    assert res_meta.headers.get('Access-Control-Allow-Origin') == '*'
    assert rdata['resource'].endswith('/sse')
    assert rdata['authorization_servers'] == [rdata['resource']]
    assert set(rdata['scopes_supported']) == {'mcp:read', 'mcp:write'}

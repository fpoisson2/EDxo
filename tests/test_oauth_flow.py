from src.app import db
from src.app.models import Programme, Department


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

    resp = client.post('/oauth/register', json={'name': 'client'})
    assert resp.status_code == 201
    creds = resp.get_json()
    client_id = creds['client_id']
    client_secret = creds['client_secret']

    resp = client.post('/oauth/token', json={'client_id': client_id, 'client_secret': client_secret, 'ttl': 3600})
    assert resp.status_code == 200
    token = resp.get_json()['access_token']

    headers = {'Authorization': f'Bearer {token}'}
    resp = client.get('/api/programmes', headers=headers)
    assert resp.status_code == 200
    assert any(p['id'] == prog_id for p in resp.get_json())

    bad = {'Authorization': 'Bearer wrong'}
    assert client.get('/api/programmes', headers=bad).status_code == 401

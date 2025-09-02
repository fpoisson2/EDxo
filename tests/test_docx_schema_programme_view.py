from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_docx_schema_programme_like_view_renders_cards_by_session(app, client):
    # Arrange: admin user
    with app.app_context():
        admin = User(
            username='admin_schema_prog',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk'
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)

    # Create a schema page (structure irrelevant for entry viewing)
    schema = {'title': 'Programme (Schéma)', 'type': 'object'}
    resp = client.post('/docx_to_schema/validate', json={'schema': schema, 'markdown': '# md'})
    assert resp.status_code == 201
    page_id = resp.get_json()['page_id']

    # Create an entry with sessions and courses
    entry_data = {
        'title': 'Grille de cours – H24',
        'sessions': [
            {
                'numero': 1,
                'cours': [
                    {'code': '101-AAA-01', 'nom': 'Intro', 'heures_theorie': 2, 'heures_laboratoire': 1, 'heures_travail_maison': 1, 'unites': 1.33},
                    {'code': '101-BBB-02', 'nom': 'Base',  'heures_theorie': 3, 'heures_laboratoire': 0, 'heures_travail_maison': 2, 'unites': 1.66},
                ],
            },
            {
                'session': 2,
                'cours': [
                    {'code': '201-CCC-03', 'nom': 'Suivi', 'heures_theorie': 2, 'heures_laboratoire': 2, 'heures_travail_maison': 1, 'unites': 2.0},
                ],
            },
        ],
    }
    resp_entry = client.post(f'/docx_schema/{page_id}/entries', json={'data': entry_data})
    assert resp_entry.status_code == 201

    # Act: view in programme-like rendering
    resp_view = client.get(f'/docx_schema/{page_id}/programme_view')
    assert resp_view.status_code == 200
    html = resp_view.data

    # Assert: accordion and cards present, with course codes and hours badge
    assert b'id="sessionsAccordion"' in html
    assert b'101-AAA-01' in html
    assert b'101-BBB-02' in html
    assert b'201-CCC-03' in html
    assert b'vp-course-card' in html
    assert b'vp-hours-badge' in html

    # Should not display programme selector dropdown from index.html
    assert b'S\xc3\xa9lectionnez un programme' not in html

    # Should not display total stats header (Theorie/Pratique/Maison/Unit\xc3\xa9s)
    assert b'vp-stat-theorie' not in html

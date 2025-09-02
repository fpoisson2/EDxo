from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel, SectionAISettings


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def setup_admin_and_schema(app, client):
    with app.app_context():
        admin = User(
            username='admin_tab',
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
    resp = client.post('/docx_to_schema/validate', json={'schema': {'title': 'Tabs', 'type': 'object'}, 'markdown': '# md'})
    page_id = resp.get_json()['page_id']
    return admin_id, page_id


def test_docx_schema_prompts_has_tabs(app, client):
    _, page_id = setup_admin_and_schema(app, client)
    r = client.get(f'/settings/docx_schema/{page_id}/prompts')
    assert r.status_code == 200
    body = r.data
    assert b'G\xc3\xa9n\xc3\xa9ration' in body
    assert b'Am\xc3\xa9lioration' in body
    assert b'Importation' in body


def test_docx_schema_prompts_save_each_scope(app, client):
    _, page_id = setup_admin_and_schema(app, client)
    # Save Generation
    r = client.post(
        f'/settings/docx_schema/{page_id}/prompts',
        data={'scope': 'gen', 'gen-system_prompt': 'GEN', 'gen-ai_model': '', 'gen-reasoning_effort': '', 'gen-verbosity': ''},
        follow_redirects=True
    )
    assert r.status_code == 200
    # Save Improve
    r = client.post(
        f'/settings/docx_schema/{page_id}/prompts',
        data={'scope': 'impv', 'impv-system_prompt': 'IMPV', 'impv-ai_model': '', 'impv-reasoning_effort': '', 'impv-verbosity': ''},
        follow_redirects=True
    )
    assert r.status_code == 200
    # Save Import
    r = client.post(
        f'/settings/docx_schema/{page_id}/prompts',
        data={'scope': 'impt', 'impt-system_prompt': 'IMPT', 'impt-ai_model': '', 'impt-reasoning_effort': '', 'impt-verbosity': ''},
        follow_redirects=True
    )
    assert r.status_code == 200

    with app.app_context():
        sa_gen = SectionAISettings.query.filter_by(section=f'docx_schema_{page_id}').first()
        sa_impv = SectionAISettings.query.filter_by(section=f'docx_schema_{page_id}_improve').first()
        sa_impt = SectionAISettings.query.filter_by(section=f'docx_schema_{page_id}_import').first()
        assert sa_gen and sa_gen.system_prompt == 'GEN'
        assert sa_impv and sa_impv.system_prompt == 'IMPV'
        assert sa_impt and sa_impt.system_prompt == 'IMPT'


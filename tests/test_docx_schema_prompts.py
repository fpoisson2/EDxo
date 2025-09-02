from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel, SectionAISettings


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_docx_schema_prompts_page(app, client):
    with app.app_context():
        admin = User(
            username='admins',
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
    resp = client.post('/docx_to_schema/validate', json={'schema': {'title': 'Test', 'type': 'object'}, 'markdown': '# md'})
    page_id = resp.get_json()['page_id']
    resp = client.get('/parametres')
    assert f'/settings/docx_schema/{page_id}/prompts'.encode() in resp.data

    # La page de paramètres doit afficher les trois onglets
    resp = client.get(f'/settings/docx_schema/{page_id}/prompts')
    assert resp.status_code == 200
    for label in (b'G\xc3\xa9n\xc3\xa9ration', b'Am\xc3\xa9lioration', b'Importation'):
        assert label in resp.data

    # Soumettre chaque formulaire et vérifier l'enregistrement
    for form_name, prompt_text in (
        ('gen', 'Gen'),
        ('impv', 'Impv'),
        ('impt', 'Impt'),
    ):
        resp = client.post(
            f'/settings/docx_schema/{page_id}/prompts',
            data={
                'form_name': form_name,
                'system_prompt': prompt_text,
                'ai_model': '',
                'reasoning_effort': '',
                'verbosity': ''
            },
            follow_redirects=True
        )
        assert resp.status_code == 200

    with app.app_context():
        sa_gen = SectionAISettings.query.filter_by(section=f'docx_schema_{page_id}').first()
        sa_impv = SectionAISettings.query.filter_by(section=f'docx_schema_{page_id}_improve').first()
        sa_impt = SectionAISettings.query.filter_by(section=f'docx_schema_{page_id}_import').first()
        assert sa_gen and sa_gen.system_prompt == 'Gen'
        assert sa_impv and sa_impv.system_prompt == 'Impv'
        assert sa_impt and sa_impt.system_prompt == 'Impt'

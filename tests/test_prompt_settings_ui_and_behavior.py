import pytest
from werkzeug.security import generate_password_hash

from src.app.models import db, User, SectionAISettings, GrillePromptSettings


def create_admin(app):
    with app.app_context():
        admin = User(
            username="admin",
            password=generate_password_hash("pw"),
            role="admin",
            is_first_connexion=False,
        )
        db.session.add(admin)
        db.session.commit()
        return admin.id


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_prompt_settings_hides_levels_and_schema(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)

    resp = client.get('/settings/prompt-settings')
    assert resp.status_code == 200
    html = resp.data
    # Should show the system prompt editor
    assert b"Prompt syst\xc3\xa8me" in html
    # Should not include removed sections
    assert b"Descriptions des niveaux" not in html
    assert b"Sch\xc3\xa9ma JSON g\xc3\xa9n\xc3\xa9r\xc3\xa9" not in html


def test_prompt_settings_post_sets_system_prompt(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)

    with app.app_context():
        # Ensure SectionAISettings exists for 'evaluation'
        sa = SectionAISettings.get_for('evaluation')
        sa.system_prompt = None
        db.session.commit()

    new_template = "SYS PROMPT TEMPLATE TEST"
    resp = client.post('/settings/prompt-settings', data={
        'prompt_template': new_template,
        # Include AI form optional fields to satisfy form structure
        'ai_model': '',
        'reasoning_effort': '',
        'verbosity': ''
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        sa2 = SectionAISettings.get_for('evaluation')
        assert (sa2.system_prompt or "").strip() == new_template

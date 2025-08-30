from src.app.models import db, User, SectionAISettings, OcrPromptSettings
from werkzeug.security import generate_password_hash
from flask import url_for


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


def test_export_prompts_includes_section_and_ocr(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)

    with app.app_context():
        sa = SectionAISettings.get_for("evaluation")
        sa.system_prompt = "Eval Prompt"
        ocr = OcrPromptSettings.get_current()
        ocr.extraction_prompt = "OCR Prompt"
        db.session.commit()

    resp = client.get("/settings/prompts/export")
    assert resp.status_code == 200
    assert "attachment; filename=prompts.md" in resp.headers.get("Content-Disposition", "")
    content = resp.data.decode()
    assert "Eval Prompt" in content
    assert "OCR Prompt" in content


def test_settings_sidebar_has_export_link(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)
    with app.test_request_context():
        export_url = url_for("settings.export_prompts")
    resp = client.get("/settings/parametres")
    assert resp.status_code == 200
    assert export_url.encode() in resp.data

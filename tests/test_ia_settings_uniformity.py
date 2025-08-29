import pytest
from werkzeug.security import generate_password_hash

from src.app.models import db, User, ChatModelConfig, SectionAISettings, OcrPromptSettings


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


def test_chat_models_uniform_layout_and_coupling(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)

    # GET page: should display uniform IA card header
    resp = client.get("/settings/chat_models")
    assert resp.status_code == 200
    assert b"Param\xc3\xa8tres IA" in resp.data  # header present
    # Ensure we do not render a distinct tool_model selector in the template
    assert b"Mod\xc3\xa8le pour l'appel d'outils" not in resp.data

    # POST: set a chat_model and verify coupling to tool_model
    with app.app_context():
        cfg_before = ChatModelConfig.get_current()
        current_model = cfg_before.chat_model

    post_resp = client.post(
        "/settings/chat_models",
        data={
            "chat_model": current_model,  # keep same but exercise path
            "reasoning_effort": "low",
            "verbosity": "high",
        },
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    with app.app_context():
        cfg = ChatModelConfig.get_current()
        assert cfg.chat_model == current_model
        # tool_model must be coupled to chat_model
        assert cfg.tool_model == current_model
        assert cfg.reasoning_effort == "low"
        assert cfg.verbosity == "high"


def test_section_ai_pages_use_uniform_template(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)

    # Representative section pages that should render the shared IA settings layout
    for path in [
        "/settings/evaluation/ai",
        "/settings/grille/ai",
        "/settings/chat/ai",
        "/settings/plan-cadre/ai",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200
        # Card header text
        assert b"Param\xc3\xa8tres IA" in resp.data
        # Form fields rendered
        assert b"Prompt syst\xc3\xa8me" in resp.data
        assert b"Niveau de raisonnement" in resp.data
        assert b"Verbosit\xc3\xa9" in resp.data


def test_ocr_prompts_updates_prompt_and_ai_params(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)

    # GET shows OCR IA params card
    resp = client.get("/settings/ocr_prompts")
    assert resp.status_code == 200
    assert b"Param\xc3\xa8tres IA \xe2\x80\x93 Devis (OCR)" in resp.data

    # POST updates both extraction prompt and section-level settings (reasoning/verbosity)
    post = client.post(
        "/settings/ocr_prompts",
        data={
            "extraction_prompt": "Test prompt extraction",
            "model_extraction": "",  # leave default
            "reasoning_effort": "medium",
            "verbosity": "low",
        },
        follow_redirects=True,
    )
    assert post.status_code == 200
    with app.app_context():
        s = SectionAISettings.get_for("ocr")
        o = OcrPromptSettings.get_current()
        assert (o.extraction_prompt or "").startswith("Test prompt")
        assert s.reasoning_effort == "medium"
        assert s.verbosity == "low"


def test_grille_settings_updates_both_sections(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)

    # GET page
    resp = client.get("/settings/grille")
    assert resp.status_code == 200
    assert b"Param\xc3\xa8tres IA" in resp.data

    # POST both prefixed forms
    post = client.post(
        "/settings/grille",
        data={
            # gen-
            "gen-system_prompt": "GEN-PROMPT",
            "gen-ai_model": "",
            "gen-reasoning_effort": "minimal",
            "gen-verbosity": "high",
            # imp-
            "imp-system_prompt": "IMP-PROMPT",
            "imp-ai_model": "",
            "imp-reasoning_effort": "high",
            "imp-verbosity": "medium",
        },
        follow_redirects=True,
    )
    assert post.status_code == 200
    with app.app_context():
        gen = SectionAISettings.get_for("grille")
        imp = SectionAISettings.get_for("grille_import")
        assert (gen.system_prompt or "").startswith("GEN-PROMPT")
        assert gen.reasoning_effort == "minimal"
        assert gen.verbosity == "high"
        assert (imp.system_prompt or "").startswith("IMP-PROMPT")
        assert imp.reasoning_effort == "high"
        assert imp.verbosity == "medium"


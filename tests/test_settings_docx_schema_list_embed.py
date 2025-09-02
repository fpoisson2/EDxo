from werkzeug.security import generate_password_hash
from src.app.models import User, db, DocxSchemaPage, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _setup_admin_with_pages(app):
    with app.app_context():
        admin = User(
            username="admin_embed",
            password=generate_password_hash("pw"),
            role="admin",
            is_first_connexion=False,
            openai_key="sk-test",
        )
        db.session.add(admin)
        # Ensure a model exists (some flows assume at least one)
        db.session.add(OpenAIModel(name="gpt-4o-mini", input_price=0.0, output_price=0.0))
        p1 = DocxSchemaPage(title="Liste A", json_schema={"title": "A", "type": "object"})
        p2 = DocxSchemaPage(title="Liste B", json_schema={"title": "B", "type": "object"})
        db.session.add(p1)
        db.session.add(p2)
        db.session.commit()
        return admin.id, p1.id, p2.id


def test_sidebar_link_points_to_settings_list(app, client):
    admin_id, *_ = _setup_admin_with_pages(app)
    _login(client, admin_id)
    r = client.get("/settings/parametres")
    assert r.status_code == 200
    # The sidebar should link to the embedded settings list, not the main page route
    assert b"/settings/schemas/list" in r.data


def test_settings_docx_schema_list_renders_in_parametres_layout(app, client):
    admin_id, p1_id, p2_id = _setup_admin_with_pages(app)
    _login(client, admin_id)
    r = client.get("/settings/schemas/list")
    assert r.status_code == 200
    body = r.data
    # Verify layout is the settings page (has the sidebar title) and includes schemas list content
    assert b"Param\xc3\xa8tres" in body  # sidebar title in parametres.html
    assert b"Sch\xc3\xa9mas DOCX valid\xc3\xa9s" in body
    # Should list the created pages and link to their views
    assert b"Liste A" in body and b"Liste B" in body
    assert f"/docx_schema/{p1_id}".encode() in body
    assert f"/docx_schema/{p2_id}".encode() in body


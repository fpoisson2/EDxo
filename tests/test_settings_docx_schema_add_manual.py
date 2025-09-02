from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel, DocxSchemaPage


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _setup_admin(app):
    with app.app_context():
        admin = User(
            username="admin_add_schema",
            password=generate_password_hash("pw"),
            role="admin",
            is_first_connexion=False,
            openai_key="sk-test",
        )
        db.session.add(admin)
        # Ensure at least one model exists
        if not OpenAIModel.query.first():
            db.session.add(OpenAIModel(name="gpt-4o-mini", input_price=0.0, output_price=0.0))
        db.session.commit()
        return admin.id


def test_settings_list_has_manual_add_ui(app, client):
    admin_id = _setup_admin(app)
    _login(client, admin_id)
    r = client.get("/settings/schemas/list")
    assert r.status_code == 200
    body = r.data
    # Check that the manual add card controls are present
    assert b"Ajouter un sch\xc3\xa9ma manuellement" in body
    assert b"Sch\xc3\xa9ma JSON" in body


def test_add_schema_manually_and_listed(app, client):
    admin_id = _setup_admin(app)
    _login(client, admin_id)
    payload = {
        "title": "Manuel",
        "schema": {"title": "Manuel", "type": "object", "properties": {}}
    }
    r = client.post('/settings/schemas/add', json=payload)
    assert r.status_code == 201
    data = r.get_json()
    page_id = data.get('page_id')
    assert isinstance(page_id, int) and page_id > 0

    r2 = client.get('/settings/schemas/list')
    assert r2.status_code == 200
    assert b"Manuel" in r2.data
    assert f"/docx_schema/{page_id}".encode() in r2.data


def test_add_schema_invalid_payload(app, client):
    admin_id = _setup_admin(app)
    _login(client, admin_id)
    # Missing schema
    r = client.post('/settings/schemas/add', json={"title": "X"})
    assert r.status_code == 400

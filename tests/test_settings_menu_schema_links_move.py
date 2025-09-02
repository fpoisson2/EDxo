from werkzeug.security import generate_password_hash
from src.app.models import User, db, OpenAIModel


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_sidebar_has_schema_links_moved_and_renamed(app, client):
    with app.app_context():
        admin = User(
            username="admin_menu",
            password=generate_password_hash("pw"),
            role="admin",
            is_first_connexion=False,
        )
        db.session.add(admin)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        admin_id = admin.id
    _login(client, admin_id)
    r = client.get('/settings/parametres')
    assert r.status_code == 200
    body = r.data
    # New label and correct target
    assert b"Liens entre les sch\xc3\xa9mas" in body
    assert b"/settings/schemas" in body
    # The link should be present (exact count may vary with layout duplication)
    assert body.count(b"/settings/schemas") >= 1

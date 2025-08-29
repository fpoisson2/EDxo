import pytest
from werkzeug.security import generate_password_hash
from src.app.models import User, db


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


def test_plan_de_cours_prompts_page_without_granular_section(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)
    resp = client.get("/settings/plan-de-cours/prompts")
    assert resp.status_code == 200
    # La section granulaire et les variables ne doivent plus apparaître
    assert b"Variables disponibles pour les prompts" not in resp.data
    assert b"granular-prompts-section" not in resp.data
    assert b"Enregistrer tout" not in resp.data
    assert b"Template du Prompt" not in resp.data


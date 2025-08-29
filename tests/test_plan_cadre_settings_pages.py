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


def test_sidebar_no_granularity_link(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)
    resp = client.get("/settings/parametres")
    assert resp.status_code == 200
    assert b"Sections (granularit" not in resp.data


def test_prompts_page_no_granularity_alert(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)
    resp = client.get("/settings/plan-cadre/prompts")
    assert resp.status_code == 200
    assert b"granularit" not in resp.data


def test_old_granularity_route_removed(app, client):
    admin_id = create_admin(app)
    login(client, admin_id)
    resp = client.get("/settings/plan_cadre")
    assert resp.status_code == 404


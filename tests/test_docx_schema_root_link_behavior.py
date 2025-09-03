from werkzeug.security import generate_password_hash
from src.app.models import User, db, DocxSchemaPage, DataSchemaLink


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def create_admin(app):
    with app.app_context():
        admin = User(
            username='admin_root_link_behavior',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk',
        )
        db.session.add(admin)
        db.session.commit()
        return admin.id


def test_root_herite_de_link_does_not_force_child_validation(app, client):
    """
    Repro: when creating only a root ('#') herite_de link, children fields must not
    be constrained server-side (UI bug fixed separately: fields should not all turn
    into selects). Ensure server accepts arbitrary child values.
    """
    admin_id = create_admin(app)
    _login(client, admin_id)
    with app.app_context():
        parent = DocxSchemaPage(title='Parent', json_schema={'title': 'P', 'type': 'object', 'properties': {
            'name': {'type': 'string'}
        }})
        db.session.add(parent); db.session.commit()
        parent_id = parent.id
        child = DocxSchemaPage(title='Child', json_schema={'title': 'C', 'type': 'object', 'properties': {
            'name': {'type': 'string'},
            'note': {'type': 'string'}
        }})
        db.session.add(child); db.session.commit()
        child_id = child.id
        # Only root link
        link_root = DataSchemaLink(
            source_page_id=child_id,
            source_pointer='#',
            relation_type='herite_de',
            target_page_id=parent_id,
            target_pointer='#'
        )
        db.session.add(link_root); db.session.commit()

    # Posting child data should not be restricted by root link
    r = client.post(f'/docx_schema/{child_id}/entries', json={'data': {'name': 'X', 'note': 'free text'}})
    assert r.status_code == 201


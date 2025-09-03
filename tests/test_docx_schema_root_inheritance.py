from src.app.models import DocxSchemaPage, DocxSchemaEntry, DataSchemaLink, User
from werkzeug.security import generate_password_hash
from src.app import db


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True



def create_admin(app):
    with app.app_context():
        admin = User(
            username='admin_root_inherit',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk',
        )
        db.session.add(admin)
        db.session.commit()
        return admin.id


def test_root_inheritance_page_has_parent_picker(app, client):
    admin_id = create_admin(app)
    _login(client, admin_id)
    with app.app_context():
        parent = DocxSchemaPage(title='Parent', json_schema={'title': 'P', 'type': 'object', 'properties': {
            'name': {'type': 'string'}
        }})
        db.session.add(parent); db.session.commit()
        parent_id = parent.id
        pe = DocxSchemaEntry(page_id=parent_id, data={'name': 'A'})
        db.session.add(pe)
        child = DocxSchemaPage(title='Child', json_schema={'title': 'C', 'type': 'object', 'properties': {
            'name': {'type': 'string'}
        }})
        db.session.add(child); db.session.commit()
        child_id = child.id
        link_root = DataSchemaLink(
            source_page_id=child_id,
            source_pointer='#',
            relation_type='herite_de',
            target_page_id=parent_id,
            target_pointer='#'
        )
        link_field = DataSchemaLink(
            source_page_id=child_id,
            source_pointer='#/properties/name',
            relation_type='herite_de',
            target_page_id=parent_id,
            target_pointer='#/properties/name'
        )
        db.session.add_all([link_root, link_field]); db.session.commit()
    resp = client.get(f'/docx_schema/{child_id}')
    assert resp.status_code == 200
    assert b'id="parentEntryPicker"' in resp.data
    links = client.get(f'/docx_schema/{child_id}/links').get_json()['links']
    assert any(l['source_pointer'] == '#' for l in links)

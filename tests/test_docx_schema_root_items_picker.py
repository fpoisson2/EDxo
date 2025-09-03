from werkzeug.security import generate_password_hash
from src.app.models import User, db, DocxSchemaPage, DocxSchemaEntry, DataSchemaLink


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def create_admin(app):
    with app.app_context():
        admin = User(
            username='admin_root_items',
            password=generate_password_hash('pw'),
            role='admin',
            is_first_connexion=False,
            openai_key='sk',
        )
        db.session.add(admin)
        db.session.commit()
        return admin.id


def test_root_items_picker_appears_with_items_pointer(app, client):
    admin_id = create_admin(app)
    _login(client, admin_id)
    with app.app_context():
        # Target schema: programme with sessions[*].cours[*] objects
        tgt = DocxSchemaPage(title='Grille de cours', json_schema={
            'title': 'G', 'type': 'object', 'properties': {
                'sessions': {'type': 'array', 'items': {
                    'type': 'object', 'properties': {
                        'cours': {'type': 'array', 'items': {
                            'type': 'object', 'properties': {
                                'code': {'type': 'string'},
                                'nom': {'type': 'string'}
                            }
                        }}
                    }
                }}
            }
        })
        db.session.add(tgt); db.session.commit()
        tgt_id = tgt.id
        # One entry with two course objects
        prog_data = {
            'sessions': [
                {
                    'cours': [
                        {'code': 'ABC', 'nom': 'Cours A'},
                        {'code': 'DEF', 'nom': 'Cours B'},
                    ]
                }
            ]
        }
        db.session.add(DocxSchemaEntry(page_id=tgt_id, data=prog_data))
        # Source schema: plan-cadre minimal
        src = DocxSchemaPage(title='Plan-cadre', json_schema={'title': 'P', 'type': 'object', 'properties': {'titre': {'type': 'string'}}})
        db.session.add(src); db.session.commit()
        src_id = src.id
        # Root herite_de pointing to cours items
        link = DataSchemaLink(
            source_page_id=src_id,
            source_pointer='#',
            relation_type='herite_de',
            target_page_id=tgt_id,
            target_pointer='#/properties/sessions/items/properties/cours/items'
        )
        db.session.add(link); db.session.commit()

    resp = client.get(f'/docx_schema/{src_id}')
    assert resp.status_code == 200
    # Both the parent entry picker and item picker should be present
    assert b'id="parentEntryPicker"' in resp.data
    assert b'data-item-picker' in resp.data

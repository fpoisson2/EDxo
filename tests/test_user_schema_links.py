from werkzeug.security import generate_password_hash


def get_model_by_name(model_name, db):
    for mapper in db.Model.registry.mappers:
        if mapper.class_.__name__ == model_name:
            return mapper.class_
    return None


def create_user(app, username, role='user', first_connexion=False, email=None):
    with app.app_context():
        from src.app import db
        User = get_model_by_name('User', db)
        user = User(
            username=username,
            password=generate_password_hash('password'),
            role=role,
            credits=0.0,
            is_first_connexion=first_connexion is True and True or False,
            email=email or f"{username}@example.com",
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def login_client(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_menu_contains_user_schema_links(app, client):
    user_id = create_user(app, 'u1', role='admin', first_connexion=False)
    login_client(client, user_id)
    r = client.get('/settings/parametres')
    assert r.status_code == 200
    assert b'/settings/data-schema/user-links' in r.data


def test_user_schema_links_page_lists_pointers_and_updates_selection(app, client):
    # Arrange: create user and one schema page with two properties
    user_id = create_user(app, 'u2', role='user', first_connexion=False)
    with app.app_context():
        from src.app import db
        DocxSchemaPage = get_model_by_name('DocxSchemaPage', db)
        User = get_model_by_name('User', db)

        schema = {'type': 'object', 'properties': {'a': {'type': 'string'}, 'b': {'type': 'number'}}}
        page = DocxSchemaPage(title='Page Test', json_schema=schema)
        db.session.add(page)
        db.session.commit()
        page_id = page.id

    login_client(client, user_id)

    # GET page shows pointers
    r = client.get('/settings/data-schema/user-links')
    assert r.status_code == 200
    body = r.data
    assert b'#/properties/a' in body
    assert b'#/properties/b' in body

    # POST select one pointer
    selected_key = f"{page_id}::#/properties/a"
    r2 = client.post('/settings/data-schema/user-links', data={
        'entries': [selected_key],
        'submit': 'Enregistrer'
    }, follow_redirects=True)
    assert r2.status_code == 200

    with app.app_context():
        from src.app import db
        User = get_model_by_name('User', db)
        user = db.session.get(User, user_id)
        selected = {(sp.page_id, sp.pointer) for sp in user.schema_pointers}
        assert selected == {(page_id, '#/properties/a')}

    # POST empty selection clears
    r3 = client.post('/settings/data-schema/user-links', data={'submit': 'Enregistrer'}, follow_redirects=True)
    assert r3.status_code == 200
    with app.app_context():
        from src.app import db
        User = get_model_by_name('User', db)
        user = db.session.get(User, user_id)
        assert len(list(user.schema_pointers)) == 0


def test_user_schema_links_grouped_ui_and_search_box(app, client):
    # Arrange: two pages
    user_id = create_user(app, 'u3', role='user', first_connexion=False)
    with app.app_context():
        from src.app import db
        DocxSchemaPage = get_model_by_name('DocxSchemaPage', db)
        p1 = DocxSchemaPage(title='Alpha Page', json_schema={'type': 'object', 'properties': {'x': {'type': 'string'}}})
        p2 = DocxSchemaPage(title='Beta Page', json_schema={'type': 'object', 'properties': {'y': {'type': 'string'}}})
        db.session.add_all([p1, p2])
        db.session.commit()

    login_client(client, user_id)
    r = client.get('/settings/data-schema/user-links')
    assert r.status_code == 200
    body = r.data
    # Page titles and pointers present
    assert b'Alpha Page' in body
    assert b'Beta Page' in body
    assert b'#/properties/x' in body
    assert b'#/properties/y' in body
    # Search input exists
    assert b'id="pointerSearch"' in body

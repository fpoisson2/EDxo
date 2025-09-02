import pytest
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


def test_edit_user_page_hides_academic_links_and_preserves_associations(app, client):
    # Arrange: create admin and a user with cegep/department/programme links
    admin_id = create_user(app, 'admin_user', role='admin', first_connexion=False)
    with app.app_context():
        from src.app import db
        ListeCegep = get_model_by_name('ListeCegep', db)
        Department = get_model_by_name('Department', db)
        Programme = get_model_by_name('Programme', db)
        User = get_model_by_name('User', db)

        cegep = ListeCegep(nom='Cégep Test', type='Public', region='Montréal')
        db.session.add(cegep)
        db.session.flush()

        dept = Department(nom='Informatique', cegep_id=cegep.id)
        db.session.add(dept)
        db.session.flush()

        prog = Programme(nom='Techniques Informatique', department_id=dept.id, cegep_id=cegep.id)
        db.session.add(prog)
        db.session.flush()

        user_id = create_user(app, 'target_user', role='invite', first_connexion=False, email='target@example.com')
        user = db.session.get(User, user_id)
        user.cegep_id = cegep.id
        user.department_id = dept.id
        user.programmes.append(prog)
        db.session.commit()

    # Act: login as admin and load edit user page
    login_client(client, admin_id)
    r = client.get(f'/edit_user/{user_id}')
    assert r.status_code == 200
    body = r.data

    # Assert: the academic fields are not visible
    assert b'C\xc3\xa9gep' not in body
    assert b'D\xc3\xa9partement' not in body
    assert b'Programmes' not in body

    # Act: submit edit (without academic fields) and ensure associations stay intact
    r2 = client.post(
        f'/edit_user/{user_id}',
        data={
            'user_id': str(user_id),
            'username': 'target_user_updated',
            'email': 'target2@example.com',
            'role': 'invite',
            'openai_key': '',
        },
        follow_redirects=True,
    )
    assert r2.status_code == 200

    with app.app_context():
        from src.app import db
        User = get_model_by_name('User', db)
        Programme = get_model_by_name('Programme', db)
        user = db.session.get(User, user_id)
        assert user.username == 'target_user_updated'
        assert user.email == 'target2@example.com'
        # Associations unchanged
        assert user.cegep_id is not None
        assert user.department_id is not None
        assert len(list(user.programmes)) == 1


def test_settings_menu_hides_academic_and_programmes_sections(app, client):
    # Arrange: login as admin to access settings menu
    admin_id = create_user(app, 'menu_admin', role='admin', first_connexion=False)
    login_client(client, admin_id)

    # Act
    r = client.get('/settings/parametres')
    assert r.status_code == 200
    body = r.data

    # Assert: sections are removed from the menu
    assert b'Gestion Acad\xc3\xa9mique' not in body
    assert b'Programmes & Comp\xc3\xa9tences' not in body


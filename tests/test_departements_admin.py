import pytest
from werkzeug.security import generate_password_hash


def get_model_by_name(model_name, db):
    for mapper in db.Model.registry.mappers:
        if mapper.class_.__name__ == model_name:
            return mapper.class_
    return None


def create_admin_and_cegep(app):
    from src.app import db
    User = get_model_by_name('User', db)
    ListeCegep = get_model_by_name('ListeCegep', db)

    with app.app_context():
        cegep = ListeCegep(nom='Cégep Test', type='Public', region='Capitale-Nationale')
        db.session.add(cegep)
        db.session.commit()

        admin = User(username='admin_test', password=generate_password_hash('password'), role='admin')
        db.session.add(admin)
        db.session.commit()

        return admin.id, cegep.id


def login_client(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_add_department_success(client, app):
    from src.app import db
    Department = get_model_by_name('Department', db)

    admin_id, cegep_id = create_admin_and_cegep(app)
    login_client(client, admin_id)

    resp = client.post(
        '/settings/gestion_departements',
        data={
            'nom': 'Département Informatique',
            'cegep_id': cegep_id,
            'ajouter_depart': '1',
        },
        follow_redirects=True,
    )

    assert resp.status_code == 200
    with app.app_context():
        dep = Department.query.filter_by(nom='Département Informatique').first()
        assert dep is not None
        assert dep.cegep_id == cegep_id


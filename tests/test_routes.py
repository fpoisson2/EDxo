from app.models import User, Programme, Cours, PlanCadre
from flask import url_for
from flask_login import login_user

def test_plan_cadre_coordo_permission_denied(client, test_db):
    """ Test où un coordo N'EST PAS attaché au programme => doit renvoyer 403 """
    programme = Programme(nom="Test", department_id=1)
    test_db.session.add(programme)
    test_db.session.commit()

    coordo = User(username="test_coordo", password="password123", role="coordo")
    test_db.session.add(coordo)  # ❌ Ne pas l'ajouter au programme
    test_db.session.commit()

    cours = Cours(programme_id=programme.id, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
    test_db.session.add(cours)
    test_db.session.commit()

    plan = PlanCadre(cours_id=cours.id)
    test_db.session.add(plan)
    test_db.session.commit()

    with client:
        client.get('/')
        with client.session_transaction() as sess:
            login_user(coordo)
            sess['_fresh'] = True

        response = client.post(
            url_for('cours.view_plan_cadre', cours_id=cours.id, plan_id=plan.id),
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )

    assert response.status_code == 403  # ✅ Il ne doit PAS avoir accès


def test_plan_cadre_coordo_permission_allowed(client, test_db):
    """ Test où un coordo A accès au programme => doit renvoyer 200 OK """
    programme = Programme(nom="Test", department_id=1)
    test_db.session.add(programme)
    test_db.session.commit()

    coordo = User(username="test_coordo", password="password123", role="coordo")
    coordo.programmes.append(programme)  # ✅ Cette fois, il a accès
    test_db.session.add(coordo)
    test_db.session.commit()

    cours = Cours(programme_id=programme.id, code="TEST101", nom="Test", nombre_unites=2.0, session=1)
    test_db.session.add(cours)
    test_db.session.commit()

    plan = PlanCadre(cours_id=cours.id)
    test_db.session.add(plan)
    test_db.session.commit()

    with client:
        client.get('/')
        with client.session_transaction() as sess:
            login_user(coordo)
            sess['_fresh'] = True

        response = client.post(
            url_for('cours.view_plan_cadre', cours_id=cours.id, plan_id=plan.id),
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )

    assert response.status_code == 200  # ✅ Il doit avoir accès


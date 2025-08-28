import pytest
from werkzeug.security import generate_password_hash

from src.app.models import db, Department, Programme, Cours, PlanCadre, User, PlanCadreCapacites


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _setup_course_and_plan(app):
    with app.app_context():
        dept = Department(nom="D")
        db.session.add(dept)
        db.session.commit()

        prog = Programme(nom="P", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()

        cours = Cours(code="C1", nom="Cours")
        db.session.add(cours)
        db.session.commit()
        cours.programmes.append(prog)
        db.session.commit()

        plan = PlanCadre(cours_id=cours.id)
        db.session.add(plan)
        db.session.commit()
        return cours.id, plan.id


def test_apply_improvement_accepts_savoirs_faire_thresholds(app, client, monkeypatch):
    # Admin user
    with app.app_context():
        admin = User(
            username="admin",
            password=generate_password_hash("pw"),
            role="admin",
            is_first_connexion=False,
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    cours_id, plan_id = _setup_course_and_plan(app)

    # Celery result stub to return a preview with proposed capacities
    class DummyAsyncResult:
        def __init__(self, *args, **kwargs):
            self.state = 'SUCCESS'
            self.result = {
                'preview': True,
                'proposed': {
                    'capacites': [
                        {
                            'capacite': 'Concevoir un module',
                            'description_capacite': 'Desc',
                            'ponderation_min': 10,
                            'ponderation_max': 20,
                            'savoirs_necessaires': ['SN1'],
                            # Note: keys reflect the generator output observed by users
                            'savoirs_faire': [
                                {
                                    'texte': 'Réaliser le schéma',
                                    'seuil_performance': 'Produire un schéma exploitable',
                                    'critere_reussite': 'Schéma complet et cohérent'
                                }
                            ],
                            'moyens_evaluation': ['Projet']
                        }
                    ]
                }
            }

    # Patch Celery AsyncResult globally (route imports it inside the function)
    monkeypatch.setattr('celery.result.AsyncResult', DummyAsyncResult)

    # Apply with replace action on capacities
    resp = client.post(
        f"/plan_cadre/{plan_id}/apply_improvement",
        data={
            'task_id': 'tid',
            'action[capacites]': 'replace',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    # Verify the savoir-faire target and threshold are persisted
    with app.app_context():
        plan = db.session.get(PlanCadre, plan_id)
        assert plan is not None
        assert plan.capacites, "A capacity should have been created"
        cap = plan.capacites[0]
        assert cap.savoirs_faire, "A savoir-faire should have been created"
        sf = cap.savoirs_faire[0]
        # cible should receive the 'seuil_performance' value from the preview
        assert sf.cible == 'Produire un schéma exploitable'
        # seuil_reussite should receive the 'critere_reussite' value from the preview
        assert sf.seuil_reussite == 'Schéma complet et cohérent'

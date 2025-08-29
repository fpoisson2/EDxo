import pytest

from src.app import create_app, db
from src.app.models import (
    Programme, Department, Cours, PlanCadre,
    PlanCadreCapacites,
)


@pytest.fixture
def app_ctx():
    app = create_app(testing=True)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _seed_plan_cadre_with_caps():
    dept = Department(nom="Génie électrique")
    db.session.add(dept)
    prog = Programme(nom="Réseaux et télécom", department=dept)
    db.session.add(prog)
    cours = Cours(code="243-1M4-LI", nom="Systèmes d’exploitation")
    # Associer cours au programme via association table (utilitaire léger)
    prog.cours_associes.append(cours)
    db.session.add(cours)
    db.session.flush()

    plan = PlanCadre(cours=cours)
    db.session.add(plan)
    db.session.flush()

    caps = [
        PlanCadreCapacites(plan_cadre=plan, capacite="Installer des systèmes d’exploitation.", description_capacite="Capacité 1"),
        PlanCadreCapacites(plan_cadre=plan, capacite="Configurer des systèmes d’exploitation.", description_capacite="Capacité 2"),
        PlanCadreCapacites(plan_cadre=plan, capacite="Dépanner des dispositifs sous divers OS.", description_capacite="Capacité 3"),
    ]
    db.session.add_all(caps)
    db.session.commit()
    return plan, caps


def test_capacity_resolution_variants(app_ctx):
    from src.app.tasks.import_plan_de_cours import _resolve_capacity_id

    plan, caps = _seed_plan_cadre_with_caps()

    # By full label
    assert _resolve_capacity_id("Configurer des systèmes d’exploitation.", plan) == caps[1].id

    # By ordinal explicit string
    assert _resolve_capacity_id("Capacité 1", plan) == caps[0].id
    assert _resolve_capacity_id("cap 2", plan) == caps[1].id
    assert _resolve_capacity_id("c 3", plan) == caps[2].id

    # By description content (fuzzy/combined)
    assert _resolve_capacity_id("Capacité : Dépanner des dispositifs", plan) == caps[2].id

    # Unresolvable should return None
    assert _resolve_capacity_id("Inconnue", plan) is None


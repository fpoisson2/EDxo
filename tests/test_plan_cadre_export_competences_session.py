import pytest

from src.app import db
from src.app.models import (
    Programme, Cours, PlanCadre,
    Competence, ElementCompetence,
    ElementCompetenceParCours, CoursProgramme
)


def test_export_context_includes_cours_session(app):
    # Créer un programme et deux cours rattachés à ce programme avec des sessions différentes
    # Contexte minimal: Cégep, Département, Programme
    from src.app.models import ListeCegep, Department
    cegep = ListeCegep(nom="Cegep X", type="Public", region="R1")
    db.session.add(cegep)
    db.session.commit()

    dept = Department(nom="Dept X", cegep_id=cegep.id)
    db.session.add(dept)
    db.session.commit()

    prog = Programme(nom="Prog", department_id=dept.id, cegep_id=cegep.id)
    db.session.add(prog)
    db.session.commit()

    cours_a = Cours(code="A101", nom="Cours A")
    cours_b = Cours(code="B202", nom="Cours B")
    db.session.add_all([cours_a, cours_b])
    db.session.commit()

    # Associer cours au programme avec sessions spécifiques
    db.session.add(CoursProgramme(cours_id=cours_a.id, programme_id=prog.id, session=1))
    db.session.add(CoursProgramme(cours_id=cours_b.id, programme_id=prog.id, session=2))
    db.session.commit()

    # Plan-cadre pour cours A (c'est celui qu'on exporte)
    plan = PlanCadre(cours_id=cours_a.id)
    db.session.add(plan)
    db.session.commit()

    # Créer une compétence et un élément
    comp = Competence(code="C1", nom="Comp 1", programme_id=prog.id)
    db.session.add(comp)
    db.session.commit()

    elem = ElementCompetence(competence_id=comp.id, nom="Elem 1")
    db.session.add(elem)
    db.session.commit()

    # Lier l'élément aux deux cours avec des statuts différents
    db.session.add(ElementCompetenceParCours(cours_id=cours_a.id, element_competence_id=elem.id, status='Développé significativement'))
    db.session.add(ElementCompetenceParCours(cours_id=cours_b.id, element_competence_id=elem.id, status='Atteint'))
    db.session.commit()

    # Construire le contexte d'export
    from src.utils.utils import build_plan_cadre_docx_context
    ctx = build_plan_cadre_docx_context(plan.id)

    # Sanity checks
    assert ctx is not None
    assert 'competences_info' in ctx
    assert isinstance(ctx['competences_info'], list)

    # Trouver l'élément et vérifier la présence des sessions pour les cours associés
    found_sessions = {}
    for comp_info in ctx['competences_info']:
        for el in comp_info.get('elements', []):
            for ca in el.get('cours_associes', []):
                found_sessions[(ca['cours_code'], ca['cours_nom'])] = ca.get('cours_session')

    # Les deux cours doivent avoir une session correctement renseignée
    assert found_sessions.get(("A101", "Cours A")) == 1
    assert found_sessions.get(("B202", "Cours B")) == 2

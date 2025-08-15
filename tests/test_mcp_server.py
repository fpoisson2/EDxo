from src.app import db
from src.app.models import (
    Programme,
    Department,
    Cours,
    PlanCadre,
    PlanDeCours,
    Competence,
)

from src.mcp_server.server import (
    programmes,
    programme_courses,
    programme_competences,
    competence_details,
    cours,
    cours_details,
    cours_plan_cadre,
    cours_plans_de_cours,
    plan_cadre_section,
)


def setup_data(app):
    with app.app_context():
        dept = Department(nom="Dep")
        db.session.add(dept)
        db.session.commit()

        programme = Programme(nom="Prog", department_id=dept.id)
        db.session.add(programme)
        db.session.commit()

        cours_obj = Cours(
            code="C101",
            nom="Course",
            heures_theorie=0,
            heures_laboratoire=0,
            heures_travail_maison=0,
        )
        db.session.add(cours_obj)
        db.session.commit()
        cours_obj.programmes.append(programme)
        db.session.commit()

        plan_cadre = PlanCadre(cours_id=cours_obj.id)
        db.session.add(plan_cadre)
        plan_de_cours = PlanDeCours(cours_id=cours_obj.id, session="A25")
        db.session.add(plan_de_cours)

        comp = Competence(programme_id=programme.id, code="COMP1", nom="Comp 1")
        db.session.add(comp)
        db.session.commit()

        return programme.id, cours_obj.id, plan_cadre.id, plan_de_cours.id, comp.id
def test_mcp_resources(app):
    prog_id, cours_id, plan_cadre_id, plan_de_cours_id, comp_id = setup_data(app)

    with app.app_context():
        assert any(p["id"] == prog_id for p in programmes())
        assert programme_courses(prog_id)[0]["id"] == cours_id
        assert programme_competences(prog_id)[0]["id"] == comp_id
        assert competence_details(comp_id)["id"] == comp_id
        assert any(c["id"] == cours_id for c in cours())
        assert cours_details(cours_id)["code"] == "C101"
        assert cours_plan_cadre(cours_id)["id"] == plan_cadre_id
        assert cours_plans_de_cours(cours_id)[0]["id"] == plan_de_cours_id
        assert "place_intro" in plan_cadre_section(plan_cadre_id, "place_intro")

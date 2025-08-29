import json
import pytest
from werkzeug.security import generate_password_hash
from src.app.models import (
    Department,
    Programme,
    Cours,
    CoursProgramme,
    CoursPrealable,
    PlanCadre,
    GlobalGenerationSettings,
    SectionAISettings,
    Competence,
    ElementCompetence,
    ElementCompetenceParCours,
    ElementCompetenceCriteria,
    User,
    db,
)
from src.app.tasks.generation_plan_cadre import generate_plan_cadre_content_task
from src.utils import get_plan_cadre_data


class DummySelf:
    request = type('Req', (), {'id': 'task-id'})()

    def update_state(self, *args, **kwargs):
        pass


def setup_plan(app):
    with app.app_context():
        dept = Department(nom="Dep")
        db.session.add(dept)
        db.session.commit()

        prog = Programme(nom="Prog", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()

        cours = Cours(code="C101", nom="Course")
        db.session.add(cours)
        db.session.commit()

        db.session.add(CoursProgramme(cours_id=cours.id, programme_id=prog.id, session=1))
        db.session.commit()

        plan = PlanCadre(cours_id=cours.id, place_intro="EXISTING INTRO")
        db.session.add(plan)
        db.session.commit()

        ggs = GlobalGenerationSettings(section="Intro et place du cours", use_ai=True, text_content="Prompt")
        db.session.add(ggs)
        db.session.commit()

        user = User(
            username="tester",
            password=generate_password_hash("pw"),
            role="admin",
            openai_key="sk",
            credits=1.0,
            is_first_connexion=False,
        )
        user.programmes.append(prog)
        db.session.add(user)
        db.session.commit()
        return plan.id, user.id


def setup_plan_with_prerequisite(app):
    with app.app_context():
        dept = Department(nom="Dep")
        db.session.add(dept)
        db.session.commit()

        prog = Programme(nom="Prog", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()

        prereq = Cours(code="P100", nom="Prereq")
        cours = Cours(code="C101", nom="Course")
        db.session.add_all([prereq, cours])
        db.session.commit()

        db.session.add_all([
            CoursProgramme(cours_id=prereq.id, programme_id=prog.id, session=1),
            CoursProgramme(cours_id=cours.id, programme_id=prog.id, session=2),
        ])
        db.session.commit()

        db.session.add(CoursPrealable(cours_id=cours.id, cours_prealable_id=prereq.id))
        db.session.commit()

        plan_main = PlanCadre(cours_id=cours.id, place_intro="EXISTING INTRO")
        plan_prereq = PlanCadre(cours_id=prereq.id, place_intro="PREREQ INTRO")
        db.session.add_all([plan_main, plan_prereq])
        db.session.commit()

        ggs = GlobalGenerationSettings(section="Intro et place du cours", use_ai=True, text_content="Prompt")
        db.session.add(ggs)
        db.session.commit()

        user = User(
            username="tester",
            password=generate_password_hash("pw"),
            role="admin",
            openai_key="sk",
            credits=1.0,
            is_first_connexion=False,
        )
        user.programmes.append(prog)
        db.session.add(user)
        db.session.commit()
        return plan_main.id, user.id, prereq


"""Test removed on request: relies on captured OpenAI call."""


"""Test removed on request: relies on captured OpenAI call."""


"""Test removed on request: relies on captured OpenAI call."""


"""Test removed on request: relies on captured OpenAI call."""


"""Test removed on request: schema capture not enforced anymore."""

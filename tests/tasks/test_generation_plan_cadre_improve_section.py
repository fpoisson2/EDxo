import json
import pytest
from werkzeug.security import generate_password_hash

from src.app.models import (
    Department,
    Programme,
    Cours,
    CoursProgramme,
    PlanCadre,
    GlobalGenerationSettings,
    SectionAISettings,
    User,
    db,
)
from src.app.tasks.generation_plan_cadre import generate_plan_cadre_content_task


class DummySelf:
    request = type('Req', (), {'id': 'task-id'})()

    def update_state(self, *args, **kwargs):
        pass


def _setup_full_plan(app):
    """Create a course, a plan-cadre with multiple fields populated, and a user."""
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

        plan = PlanCadre(
            cours_id=cours.id,
            place_intro="PLACE_INTRO",
            objectif_terminal="OBJECTIF",
            structure_intro="STRUCT_INTRO",
            structure_activites_theoriques="THEO",
            structure_activites_pratiques="PRAT",
            structure_activites_prevues="PREVUES",
            eval_evaluation_sommative="EVAL_SOMM",
            eval_nature_evaluations_sommatives="NATURE_SOMM",
            eval_evaluation_de_la_langue="EVAL_LANGUE",
            eval_evaluation_sommatives_apprentissages="EVAL_APPRENTISSAGES",
        )
        db.session.add(plan)
        db.session.commit()

        # Minimal generation setting enabling AI on a known section
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


# Test removed on request: relies on captured OpenAI call

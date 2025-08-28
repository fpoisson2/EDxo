from unittest.mock import patch

import json
import pytest

from src.app.models import (
    Department,
    Programme,
    User,
    Cours,
    PlanCadre,
    PlanDeCours,
    CoursProgramme,
    SectionAISettings,
    AnalysePlanCoursPrompt,
    GlobalGenerationSettings,
    PlanDeCoursPromptSettings,
    db,
)
from src.app.tasks.analyse_plan_de_cours import analyse_plan_de_cours_task
from src.app.tasks.generation_plan_cadre import generate_plan_cadre_content_task
from src.app.tasks.generation_plan_de_cours import generate_plan_de_cours_field_task


class DummySelf:
    def __init__(self):
        self.updates = []
        self.request = type('R', (), {'id': 'task-id'})()

    def update_state(self, state=None, meta=None):
        self.updates.append(meta or {})


class DummyEvent:
    def __init__(self, name, delta=None, summary=None, use_event=False):
        if use_event:
            self.event = name
        else:
            self.type = name
        self.delta = delta
        self.summary = summary


class DummyStream:
    def __init__(self, events, final_text):
        self.events = events
        self.final_text = final_text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_response(self):
        parsed = None
        try:
            data = json.loads(self.final_text)
            if isinstance(data, dict) and "champ_description" in data:
                parsed = type('Parsed', (), {"champ_description": data["champ_description"]})()
        except Exception:
            parsed = None

        class Resp:
            output_text = self.final_text

            class usage:
                input_tokens = 0
                output_tokens = 0

        if parsed is not None:
            content = type('C', (), {'parsed': parsed})
            Resp.output = [type('O', (), {'content': [content]})]
        else:
            Resp.output = []
        return Resp()


class DummyResponses:
    def __init__(self, events, final_text):
        self._events = events
        self._final_text = final_text

    def stream(self, **kwargs):
        return DummyStream(self._events, self._final_text)


class DummyClient:
    def __init__(self, events, final_text):
        self.responses = DummyResponses(events, final_text)


# --- Setup helpers --------------------------------------------------------

def setup_analyse_plan_user(app):
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
        plan_cadre = PlanCadre(cours_id=cours.id)
        db.session.add(plan_cadre)
        db.session.commit()
        plan = PlanDeCours(cours_id=cours.id, session="S1")
        db.session.add(plan)
        db.session.commit()
        db.session.add(CoursProgramme(cours_id=cours.id, programme_id=prog.id, session=1))
        db.session.commit()
        db.session.add(AnalysePlanCoursPrompt(prompt_template="Prompt"))
        db.session.add(SectionAISettings(section='analyse_plan_cours'))
        db.session.commit()
        user = User(
            username="u",
            password="pw",
            role="user",
            openai_key="sk",
            credits=1.0,
            is_first_connexion=False,
        )
        user.programmes.append(prog)
        db.session.add(user)
        db.session.commit()
        return plan.id, user.id


def setup_generate_plan_user(app):
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
        db.session.add(CoursProgramme(cours_id=cours.id, programme_id=prog.id, session=1))
        db.session.commit()
        plan = PlanCadre(cours_id=cours.id)
        db.session.add(plan)
        db.session.commit()
        ggs = GlobalGenerationSettings(
            section="Intro et place du cours", use_ai=True, text_content="Prompt"
        )
        db.session.add(ggs)
        db.session.commit()
        user = User(
            username="u",
            password="pw",
            role="user",
            openai_key="sk",
            credits=1.0,
            is_first_connexion=False,
        )
        user.programmes.append(prog)
        db.session.add(user)
        db.session.commit()
        return plan.id, user.id


def setup_improve_field_user(app):
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
        db.session.add(CoursProgramme(cours_id=cours.id, programme_id=prog.id, session=1))
        db.session.commit()
        plan_cadre = PlanCadre(cours_id=cours.id)
        db.session.add(plan_cadre)
        db.session.commit()
        plan = PlanDeCours(cours_id=cours.id, session="S1")
        db.session.add(plan)
        db.session.commit()
        db.session.add(PlanDeCoursPromptSettings(field_name="presentation_du_cours", prompt_template="Prompt"))
        db.session.add(SectionAISettings(section="plan_de_cours"))
        db.session.commit()
        user = User(
            username="u",
            password="pw",
            role="user",
            openai_key="sk",
            credits=1.0,
            is_first_connexion=False,
        )
        user.programmes.append(prog)
        db.session.add(user)
        db.session.commit()
        return plan.id, user.id


# --- Task runners --------------------------------------------------------

def run_analyse(dummy, plan_id, user_id):
    orig = analyse_plan_de_cours_task.__wrapped__.__func__
    return orig(dummy, plan_id, user_id)


def run_generate(dummy, plan_id, user_id):
    orig = generate_plan_cadre_content_task.__wrapped__.__func__
    return orig(dummy, plan_id, {"stream": True}, user_id)


def run_improve_field(dummy, plan_id, user_id):
    orig = generate_plan_de_cours_field_task.__wrapped__.__func__
    return orig(dummy, plan_id, "presentation_du_cours", None, user_id)


@pytest.mark.parametrize(
    "setup_fn, runner, openai_path, final_text, output_delta",
    [
        (
            setup_analyse_plan_user,
            run_analyse,
            "src.app.tasks.analyse_plan_de_cours.OpenAI",
            "{}",
            '{"compatibility_percentage": 0.5}',
        ),
        (
            setup_generate_plan_user,
            run_generate,
            "src.app.tasks.generation_plan_cadre.OpenAI",
            '{"place_intro":"Salut","objectif_terminal":"o","structure_intro":"s","structure_activites_theoriques":"s","structure_activites_pratiques":"s","structure_activites_prevues":"s","eval_evaluation_sommative":"s","eval_nature_evaluations_sommatives":"s","eval_evaluation_de_la_langue":"s","eval_evaluation_sommatives_apprentissages":"s","competences_developpees":[{"texte":"t","description":"d"}],"competences_certifiees":[{"texte":"t","description":"d"}],"cours_corequis":[{"texte":"t","description":"d"}],"objets_cibles":[{"texte":"t","description":"d"}],"cours_relies":[{"texte":"t","description":"d"}],"cours_prealables":[{"texte":"t","description":"d"}],"savoir_etre":["s"],"capacites":[{"capacite":"c","description_capacite":"d","ponderation_min":1,"ponderation_max":2,"savoirs_necessaires":["s"],"savoirs_faire":[{"texte":"t","cible":"c","seuil_reussite":"r"}],"moyens_evaluation":["m"]}]}',
            '{"place_intro":"Salut","objectif_terminal":"o","structure_intro":"s","structure_activites_theoriques":"s","structure_activites_pratiques":"s","structure_activites_prevues":"s","eval_evaluation_sommative":"s","eval_nature_evaluations_sommatives":"s","eval_evaluation_de_la_langue":"s","eval_evaluation_sommatives_apprentissages":"s","competences_developpees":[{"texte":"t","description":"d"}],"competences_certifiees":[{"texte":"t","description":"d"}],"cours_corequis":[{"texte":"t","description":"d"}],"objets_cibles":[{"texte":"t","description":"d"}],"cours_relies":[{"texte":"t","description":"d"}],"cours_prealables":[{"texte":"t","description":"d"}],"savoir_etre":["s"],"capacites":[{"capacite":"c","description_capacite":"d","ponderation_min":1,"ponderation_max":2,"savoirs_necessaires":["s"],"savoirs_faire":[{"texte":"t","cible":"c","seuil_reussite":"r"}],"moyens_evaluation":["m"]}]}',
        ),
        (
            setup_improve_field_user,
            run_improve_field,
            "src.app.tasks.generation_plan_de_cours.OpenAI",
            '{"champ_description":"Salut"}',
            '{"champ_description":"Salut"}',
        ),
    ],
)
@pytest.mark.parametrize("use_event", [False, True])
def test_task_status_updates(app, setup_fn, runner, openai_path, final_text, output_delta, use_event):
    if runner is run_improve_field and use_event:
        pytest.skip("legacy event naming not supported for field generation")
    plan_id, user_id = setup_fn(app)
    dummy = DummySelf()
    events = [
        DummyEvent(
            "response.output_text.delta",
            delta=output_delta,
            use_event=use_event,
        ),
        DummyEvent(
            "response.reasoning_summary_text.delta",
            delta="raisonnement",
            use_event=use_event,
        ),
        DummyEvent("response.completed", use_event=use_event),
    ]
    with patch(openai_path, return_value=DummyClient(events, final_text)):
        result = runner(dummy, plan_id, user_id)
    assert result["status"] == "success"
    assert result.get("reasoning_summary") == "raisonnement"
    assert any(u.get("stream_chunk") and u.get("message") for u in dummy.updates)
    assert any(
        u.get("reasoning_summary") == "raisonnement" and u.get("message") == "Résumé du raisonnement"
        for u in dummy.updates
    )


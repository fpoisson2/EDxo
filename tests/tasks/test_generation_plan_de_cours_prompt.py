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
    db,
)
from src.app.tasks.generation_plan_de_cours import generate_plan_de_cours_all_task


class DummySelf:
    def __init__(self):
        self.updates = []
        self.request = type('R', (), {'id': 'task-id'})()

    def update_state(self, state=None, meta=None):
        self.updates.append(meta or {})


class DummyStream:
    def __init__(self, events, final_resp_builder):
        self.events = events
        self._final_resp_builder = final_resp_builder

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_response(self):
        return self._final_resp_builder()


class DummyResponses:
    def __init__(self, events, final_resp_builder, capture):
        self._events = events
        self._final_resp_builder = final_resp_builder
        self.capture = capture

    def stream(self, **kwargs):
        # Capture the input payload passed to OpenAI
        self.capture['last_stream_kwargs'] = kwargs
        return DummyStream(self._events, self._final_resp_builder)

    # Provide parse to avoid AttributeError in downstream calls within the task
    def parse(self, **kwargs):
        return self._final_resp_builder()


class DummyClient:
    def __init__(self, events, final_resp_builder, capture):
        self.responses = DummyResponses(events, final_resp_builder, capture)


def _final_resp():
    # Minimal object exposing usage and a parsed payload compatible with task expectations
    class Parsed:
        presentation_du_cours = "X"
        objectif_terminal_du_cours = "X"
        organisation_et_methodes = "X"
        accomodement = "X"
        evaluation_formative_apprentissages = "X"
        evaluation_expression_francais = "X"
        seuil_reussite = "X"
        materiel = "X"
        calendriers = []

    class Content:
        parsed = Parsed()

    class OutputItem:
        content = [Content]

    class Usage:
        input_tokens = 0
        output_tokens = 0

    class Resp:
        usage = Usage()
        output = [OutputItem]

    return Resp()


def _final_resp_with_evals():
    # Build a parsed payload that includes evaluations
    class Cap:
        capacite = "CapA"
        ponderation = "30%"

    class EvalItem:
        titre_evaluation = "Eval 1"
        description = "Desc"
        semaine = 1
        capacites = [Cap()]

    class Parsed:
        presentation_du_cours = "X"
        objectif_terminal_du_cours = "X"
        organisation_et_methodes = "X"
        accomodement = "X"
        evaluation_formative_apprentissages = "X"
        evaluation_expression_francais = "X"
        seuil_reussite = "X"
        materiel = "X"
        calendriers = []
        evaluations = [EvalItem()]

    class Content:
        parsed = Parsed()

    class OutputItem:
        content = [Content]

    class Usage:
        input_tokens = 0
        output_tokens = 0

    class Resp:
        usage = Usage()
        output = [OutputItem]

    return Resp()


class DummyResponsesNoParse(DummyResponses):
    def parse(self, **kwargs):
        raise AssertionError("parse() should not be called when streaming succeeds and evals are included")


def setup_two_courses(app):
    with app.app_context():
        dept = Department(nom="D")
        db.session.add(dept)
        db.session.commit()
        prog = Programme(nom="P", department_id=dept.id)
        db.session.add(prog)
        db.session.commit()

        # Course A (target)
        cours_a = Cours(code="CA", nom="Cours A")
        db.session.add(cours_a)
        db.session.commit()
        plan_cadre_a = PlanCadre(cours_id=cours_a.id, place_intro="PLACE_A")
        db.session.add(plan_cadre_a)
        db.session.commit()
        plan_a = PlanDeCours(cours_id=cours_a.id, session="S1")
        db.session.add(plan_a)
        db.session.commit()

        # Course B (other)
        cours_b = Cours(code="CB", nom="Cours B")
        db.session.add(cours_b)
        db.session.commit()
        plan_cadre_b = PlanCadre(cours_id=cours_b.id, place_intro="PLACE_B")
        db.session.add(plan_cadre_b)
        db.session.commit()

        db.session.add(CoursProgramme(cours_id=cours_a.id, programme_id=prog.id, session=1))
        db.session.add(CoursProgramme(cours_id=cours_b.id, programme_id=prog.id, session=1))
        db.session.commit()

        # Ensure SectionAISettings exists to avoid None
        db.session.add(SectionAISettings(section='plan_de_cours'))
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

        return plan_a.id, user.id


def run_generate_all(dummy, plan_id, user_id, contaminated_prompt):
    orig = generate_plan_de_cours_all_task.__wrapped__.__func__
    # ai_model arbitrary; contaminated prompt simulates a prompt containing other course data
    return orig(dummy, plan_id, contaminated_prompt, "gpt-5", user_id)


def run_generate_all_improve(dummy, plan_id, user_id, contaminated_prompt):
    orig = generate_plan_de_cours_all_task.__wrapped__.__func__
    return orig(dummy, plan_id, contaminated_prompt, "gpt-5", user_id, True)


def test_all_task_uses_only_same_plan_cadre_in_prompt(app):
    plan_id, user_id = setup_two_courses(app)
    dummy = DummySelf()

    # Prepare a prompt that wrongly contains PLACE_B to simulate contamination
    contaminated_prompt = "Manual prompt with PLACE_B that should NOT be used"

    # Capture dict to inspect what is sent to OpenAI
    capture = {}

    events = []  # No deltas needed for this test

    with patch("src.app.tasks.generation_plan_de_cours.OpenAI", return_value=DummyClient(events, _final_resp, capture)):
        result = run_generate_all(dummy, plan_id, user_id, contaminated_prompt)

    assert result["status"] == "success"

    # Inspect captured input passed to OpenAI.responses.stream
    kwargs = capture.get('last_stream_kwargs')
    assert kwargs is not None, "OpenAI.responses.stream was not called"
    input_payload = kwargs.get('input')
    # Expect the 'user' message only contains the plan-cadre for the same course (PLACE_A)
    # and not the contaminated PLACE_B string
    # Input is an array of messages with roles; find the user one
    user_msgs = [m for m in input_payload if m.get('role') == 'user']
    assert user_msgs, "No user message found in input payload"
    user_text = "\n".join([c.get('text', '') for c in user_msgs[0].get('content', []) if c.get('type') == 'input_text'])
    assert "PLACE_A" in user_text
    assert "PLACE_B" not in user_text


def test_all_task_does_not_call_second_openai_for_evaluations(app):
    plan_id, user_id = setup_two_courses(app)
    dummy = DummySelf()

    # Add a capacity to the plan_cadre of course A so mapping can succeed
    with app.app_context():
        from src.app.models import PlanDeCours, PlanCadre, PlanCadreCapacites
        plan = db.session.get(PlanDeCours, plan_id)
        pc = plan.cours.plan_cadre
        cap = PlanCadreCapacites(plan_cadre_id=pc.id, capacite="CapA", description_capacite=None)
        db.session.add(cap)
        db.session.commit()

    contaminated_prompt = "anything"
    capture = {}
    events = []

    # Use a DummyClient whose responses.parse raises if called
    class DummyClientNoParse:
        def __init__(self, events, final_resp_builder, capture):
            self.responses = DummyResponsesNoParse(events, final_resp_builder, capture)

    with patch("src.app.tasks.generation_plan_de_cours.OpenAI", return_value=DummyClientNoParse(events, _final_resp_with_evals, capture)):
        result = run_generate_all(dummy, plan_id, user_id, contaminated_prompt)

    assert result["status"] == "success"
    # Ensure at least one evaluation was produced and persisted
    with app.app_context():
        from src.app.models import PlanDeCours
        plan = db.session.get(PlanDeCours, plan_id)
        assert plan.evaluations and len(plan.evaluations) == 1
        ev = plan.evaluations[0]
        assert ev.titre_evaluation == "Eval 1"


def test_all_task_includes_additional_info_from_prompt(app):
    plan_id, user_id = setup_two_courses(app)
    dummy = DummySelf()

    # Build a fake prompt that contains the marker used by build_all_prompt
    contaminated_prompt = "Header lines...\nInformations complémentaires: BESOIN_SPECIFIQUE_A_INCLURE"
    capture = {}
    events = []

    with patch("src.app.tasks.generation_plan_de_cours.OpenAI", return_value=DummyClient(events, _final_resp, capture)):
        result = run_generate_all(dummy, plan_id, user_id, contaminated_prompt)

    assert result["status"] == "success"
    kwargs = capture.get('last_stream_kwargs')
    assert kwargs is not None
    input_payload = kwargs.get('input')
    user_msgs = [m for m in input_payload if m.get('role') == 'user']
    assert user_msgs
    user_text = "\n".join([c.get('text', '') for c in user_msgs[0].get('content', []) if c.get('type') == 'input_text'])
    assert "BESOIN_SPECIFIQUE_A_INCLURE" in user_text


def test_all_task_improve_mode_uses_current_plan_and_improve_settings(app):
    plan_id, user_id = setup_two_courses(app)
    dummy = DummySelf()

    # Seed current plan with a recognizable string
    with app.app_context():
        from src.app.models import PlanDeCours, SectionAISettings
        plan = db.session.get(PlanDeCours, plan_id)
        plan.materiel = "MATERIEL_EXISTANT"
        db.session.add(plan)
        # Ensure improve settings exist with a distinctive system prompt
        s = SectionAISettings.get_for('plan_de_cours_improve')
        s.system_prompt = "SYS_IMPROVE_PROMPT"
        db.session.add(s)
        db.session.commit()

    contaminated_prompt = "Informations complémentaires: BESOIN_IMPROVE"
    capture = {}
    events = []

    with patch("src.app.tasks.generation_plan_de_cours.OpenAI", return_value=DummyClient(events, _final_resp, capture)):
        result = run_generate_all_improve(dummy, plan_id, user_id, contaminated_prompt)

    assert result["status"] == "success"

    kwargs = capture.get('last_stream_kwargs')
    assert kwargs is not None
    input_payload = kwargs.get('input')
    sys_msgs = [m for m in input_payload if m.get('role') == 'system']
    assert sys_msgs and any("SYS_IMPROVE_PROMPT" in c.get('text','') for c in sys_msgs[0].get('content', []))
    user_msgs = [m for m in input_payload if m.get('role') == 'user']
    assert user_msgs
    user_text = "\n".join([c.get('text', '') for c in user_msgs[0].get('content', []) if c.get('type') == 'input_text'])
    assert "MATERIEL_EXISTANT" in user_text
    assert "BESOIN_IMPROVE" in user_text

from src.app.tasks.import_plan_de_cours import import_plan_de_cours_task
from src.app.models import Programme, Department, Cours, PlanCadre, PlanDeCours, User, SectionAISettings
from src.extensions import db


class FakeFiles:
    def __init__(self, recorder):
        self.recorder = recorder
    def create(self, file=None, purpose=None):  # noqa: ARG002
        return type('Up', (), {'id': 'file-id'})()


def make_event(t, delta):
    return type('Ev', (), {'type': t, 'delta': delta, 'text': delta})()


def make_final_response():
    usage = type('U', (), {'input_tokens': 4, 'output_tokens': 7})()
    output_parsed = {
        'presentation_du_cours': 'P',
        'objectif_terminal_du_cours': 'O',
        'organisation_et_methodes': 'M',
        'accomodement': 'A',
        'evaluation_formative_apprentissages': 'E1',
        'evaluation_expression_francais': 'E2',
        'materiel': 'Mat',
        'calendriers': [],
        'disponibilites': [],
        'mediagraphies': [],
        'evaluations': [],
    }
    return type('Resp', (), {'usage': usage, 'output_parsed': output_parsed})()


class FakeResponses:
    class _Stream:
        def __init__(self, events):
            self._events = list(events)
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False
        def __iter__(self):
            return iter(self._events)
        def get_final_response(self):
            return make_final_response()

    def __init__(self, recorder):
        self.recorder = recorder
    def stream(self, **kwargs):
        self.recorder['input'] = kwargs.get('input')
        # Simulate text and reasoning summary deltas
        events = [
            make_event('response.output_text.delta', 'Hello '),
            make_event('response.reasoning_summary_text.delta', 'Why: because'),
            make_event('response.output_text.delta', 'world!'),
        ]
        return FakeResponses._Stream(events)


class FakeOpenAI:
    last_instance = None
    def __init__(self, api_key=None):  # noqa: ARG002
        self.calls = {}
        self.files = FakeFiles(self.calls)
        self.responses = FakeResponses(self.calls)
        FakeOpenAI.last_instance = self


def test_streaming_updates_push_meta(app):
    # Arrange DB
    with app.app_context():
        dept = Department(nom='D')
        db.session.add(dept)
        db.session.flush()
        prog = Programme(nom='P', department_id=dept.id)
        db.session.add(prog)
        db.session.flush()
        cours = Cours(code='C1', nom='Cours', heures_theorie=0, heures_laboratoire=0, heures_travail_maison=0)
        db.session.add(cours)
        db.session.flush()
        cours.programmes.append(prog)
        db.session.flush()
        pc = PlanCadre(cours_id=cours.id)
        db.session.add(pc)
        db.session.flush()
        plan = PlanDeCours(cours_id=cours.id, session='A25')
        db.session.add(plan)
        db.session.flush()
        user = User(username='u', password='x', email='u@example.com', openai_key='sk-test', credits=100.0)
        db.session.add(user)
        db.session.add(SectionAISettings(section='plan_de_cours_import', system_prompt=''))
        db.session.commit()

        updates = []
        class DummySelf:
            request = type('R', (), {'id': 'tid'})()
            def update_state(self, state=None, meta=None):  # noqa: ANN001
                updates.append((state, meta or {}))

        # Act
        orig = import_plan_de_cours_task.__wrapped__.__func__
        result = orig(DummySelf(), plan.id, 'text', 'gpt-5', user.id, None, FakeOpenAI)

        # Assert
        assert result.get('status') == 'success'
        # Ensure we pushed both stream chunks and reasoning summary at least once
        has_stream = any('stream_chunk' in (m or {}) for (_, m) in updates)
        has_reason = any('reasoning_summary' in (m or {}) for (_, m) in updates)
        assert has_stream, 'stream_chunk was not pushed via update_state'
        assert has_reason, 'reasoning_summary was not pushed via update_state'


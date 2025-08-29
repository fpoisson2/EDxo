from unittest.mock import patch

from src.app.tasks.import_plan_de_cours import import_plan_de_cours_task
from src.app.models import Programme, Department, Cours, PlanCadre, PlanDeCours, User, SectionAISettings
from src.extensions import db


class FakeResponses:
    class _Stream:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False
        def __iter__(self):
            return iter(())
        def get_final_response(self):
            usage = type('U', (), {'input_tokens': 1, 'output_tokens': 1})()
            output_parsed = {
                'presentation_du_cours': 'NEW',
                'objectif_terminal_du_cours': '',
                'organisation_et_methodes': '',
                'accomodement': '',
                'evaluation_formative_apprentissages': '',
                'evaluation_expression_francais': '',
                'materiel': '',
                'calendriers': [],
                'disponibilites': [],
                'mediagraphies': [],
                'evaluations': [],
            }
            return type('Resp', (), {'usage': usage, 'output_parsed': output_parsed})()

    def __init__(self, recorder):
        self.recorder = recorder

    def stream(self, **kwargs):  # noqa: ARG002
        return FakeResponses._Stream()


class FakeFiles:
    def __init__(self, recorder):
        self.recorder = recorder
    def create(self, file=None, purpose=None):  # noqa: ARG002
        return type('Up', (), {'id': 'file-id'})()


class FakeOpenAI:
    def __init__(self, api_key=None):  # noqa: ARG002
        self.calls = {}
        self.files = FakeFiles(self.calls)
        self.responses = FakeResponses(self.calls)


def test_review_confirm_applies_changes_only_on_confirm(app, client):
    with app.app_context():
        dept = Department(nom='D'); db.session.add(dept); db.session.flush()
        prog = Programme(nom='P', department_id=dept.id); db.session.add(prog); db.session.flush()
        cours = Cours(code='C', nom='Cours', heures_theorie=0, heures_laboratoire=0, heures_travail_maison=0)
        db.session.add(cours); db.session.flush(); cours.programmes.append(prog); db.session.flush()
        pc = PlanCadre(cours_id=cours.id); db.session.add(pc); db.session.flush()
        plan = PlanDeCours(cours_id=cours.id, session='A25', presentation_du_cours='OLD'); db.session.add(plan); db.session.flush()
        user = User(username='u', password='x', email='u@example.com', openai_key='sk', credits=10.0, is_first_connexion=False)
        db.session.add(user); db.session.add(SectionAISettings(section='plan_de_cours_import', system_prompt=''))
        db.session.commit()

        class DummySelf:
            request = type('R', (), {'id': 'tid-123'})()
            def update_state(self, state=None, meta=None):  # noqa: ANN001,ARG002
                return None

        # Run task -> should NOT change DB
        orig = import_plan_de_cours_task.__wrapped__.__func__
        result = orig(DummySelf(), plan.id, 'text', 'gpt-5', user.id, None, FakeOpenAI)
        assert result.get('status') == 'success'
        db.session.refresh(plan)
        assert plan.presentation_du_cours == 'OLD', 'DB must not be updated before confirmation'

        # Patch AsyncResult inside route to return our result payload
        class DummyAsync:
            def __init__(self, result):
                self._result = result
            @property
            def result(self):
                return self._result

        with patch('src.app.routes.plan_de_cours.AsyncResult', return_value=DummyAsync(result)):
            # Authenticate the test client
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user.id)
            # Confirm changes
            resp = client.post(f'/plan_de_cours/review/{plan.id}/apply', json={'action': 'confirm', 'task_id': 'tid-123'})
            assert resp.status_code == 200
            db.session.refresh(plan)
            assert plan.presentation_du_cours == 'NEW', 'DB must be updated on confirm'

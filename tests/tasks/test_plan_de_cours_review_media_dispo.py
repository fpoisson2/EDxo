from unittest.mock import patch

from src.app.tasks.import_plan_de_cours import import_plan_de_cours_task
from src.app.models import Programme, Department, Cours, PlanCadre, PlanDeCours, User, SectionAISettings, PlanDeCoursMediagraphie, PlanDeCoursDisponibiliteEnseignant
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
                'presentation_du_cours': '',
                'objectif_terminal_du_cours': '',
                'organisation_et_methodes': '',
                'accomodement': '',
                'evaluation_formative_apprentissages': '',
                'evaluation_expression_francais': '',
                'materiel': '',
                'calendriers': [],
                'disponibilites': [
                    {'jour_semaine': 'Mardi', 'plage_horaire': '10-12', 'lieu': 'B-101'},
                ],
                'mediagraphies': [
                    {'reference_bibliographique': 'Ref nouvelle'},
                ],
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


def test_task_exposes_old_media_and_dispo_and_review_shows_them(app, client):
    with app.app_context():
        dept = Department(nom='D'); db.session.add(dept); db.session.flush()
        prog = Programme(nom='P', department_id=dept.id); db.session.add(prog); db.session.flush()
        cours = Cours(code='C', nom='Cours', heures_theorie=0, heures_laboratoire=0, heures_travail_maison=0)
        db.session.add(cours); db.session.flush(); cours.programmes.append(prog); db.session.flush()
        pc = PlanCadre(cours_id=cours.id); db.session.add(pc); db.session.flush()
        plan = PlanDeCours(cours_id=cours.id, session='A25'); db.session.add(plan); db.session.flush()
        # Seed existing media/dispo
        db.session.add(PlanDeCoursMediagraphie(plan_de_cours_id=plan.id, reference_bibliographique='Ref ancienne'))
        db.session.add(PlanDeCoursDisponibiliteEnseignant(plan_de_cours_id=plan.id, jour_semaine='Lundi', plage_horaire='8-10', lieu='A-100'))
        user = User(username='u', password='x', email='u@example.com', openai_key='sk', credits=10.0, is_first_connexion=False)
        db.session.add(user); db.session.add(SectionAISettings(section='plan_de_cours_import', system_prompt=''))
        db.session.commit()

        class DummySelf:
            request = type('R', (), {'id': 'tid-abc'})()
            def update_state(self, state=None, meta=None):  # noqa: ANN001,ARG002
                return None

        # Run task
        orig = import_plan_de_cours_task.__wrapped__.__func__
        result = orig(DummySelf(), plan.id, 'text', 'gpt-5', user.id, None, FakeOpenAI)
        assert result.get('status') == 'success'
        # Ensure old keys are present
        assert result.get('old_mediagraphies')
        assert result.get('old_disponibilites')

        # Call review and ensure labels present
        class DummyAsync:
            def __init__(self, result):
                self._result = result
            @property
            def result(self):
                return self._result

        with patch('src.app.routes.plan_de_cours.AsyncResult', return_value=DummyAsync(result)):
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user.id)
            resp = client.get(f'/plan_de_cours/review/{plan.id}?task_id=tid-abc')
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)
            assert 'Médiagraphie' in html
            assert 'Disponibilités' in html


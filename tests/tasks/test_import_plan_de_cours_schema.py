from src.app.models import Programme, Department, Cours, PlanCadre, PlanDeCours, User, SectionAISettings
from src.extensions import db
from src.app.tasks.import_plan_de_cours import import_plan_de_cours_task


class FakeResponses:
    class _Stream:
        def __init__(self, recorder):
            self.recorder = recorder
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def __iter__(self):
            return iter(())
        def get_final_response(self):
            usage = type('U', (), {'input_tokens': 1, 'output_tokens': 1})()
            output_parsed = {
                "presentation_du_cours": "",
                "objectif_terminal_du_cours": "",
                "organisation_et_methodes": "",
                "accomodement": "",
                "evaluation_formative_apprentissages": "",
                "evaluation_expression_francais": "",
                "materiel": "",
                "calendriers": [],
                "nom_enseignant": "",
                "telephone_enseignant": "",
                "courriel_enseignant": "",
                "bureau_enseignant": "",
                "disponibilites": [],
                "mediagraphies": [],
                "evaluations": [],
            }
            return type('Resp', (), {'usage': usage, 'output_parsed': output_parsed})()
    def __init__(self, recorder):
        self.recorder = recorder
    def stream(self, **kwargs):
        self.recorder['text'] = kwargs.get('text')
        return FakeResponses._Stream(self.recorder)


class FakeFiles:
    def __init__(self, recorder):
        self.recorder = recorder
    def create(self, file=None, purpose=None):  # noqa: ARG002
        return type('Up', (), {'id': 'file-id'})()


class FakeOpenAI:
    last = None
    def __init__(self, api_key=None):  # noqa: ARG002
        self.calls = {}
        self.files = FakeFiles(self.calls)
        self.responses = FakeResponses(self.calls)
        FakeOpenAI.last = self


def test_schema_has_no_defs(app):
    with app.app_context():
        dept = Department(nom='D'); db.session.add(dept); db.session.flush()
        prog = Programme(nom='P', department_id=dept.id); db.session.add(prog); db.session.flush()
        cours = Cours(code='C', nom='Cours', heures_theorie=0, heures_laboratoire=0, heures_travail_maison=0)
        db.session.add(cours); db.session.flush(); cours.programmes.append(prog); db.session.flush()
        pc = PlanCadre(cours_id=cours.id); db.session.add(pc); db.session.flush()
        plan = PlanDeCours(cours_id=cours.id, session='A25'); db.session.add(plan); db.session.flush()
        user = User(username='u', password='x', email='u@example.com', openai_key='sk', credits=10.0)
        db.session.add(user); db.session.add(SectionAISettings(section='plan_de_cours_import', system_prompt=''))
        db.session.commit()

        class DummySelf:
            request = type('R', (), {'id': 'tid'})()
            def update_state(self, state=None, meta=None):  # noqa: ANN001,ARG002
                return None

        orig = import_plan_de_cours_task.__wrapped__.__func__
        result = orig(DummySelf(), plan.id, 'text', 'gpt-5', user.id, None, FakeOpenAI)
        assert result.get('status') == 'success'
        schema = FakeOpenAI.last.calls.get('text', {}).get('format', {}).get('schema', {})
        assert schema
        assert '$defs' not in schema
        assert schema.get('additionalProperties') is False
        assert set(schema['required']) == set(schema['properties'].keys())
        cal_item = schema['properties']['calendriers']['items']
        assert set(cal_item['required']) == set(cal_item['properties'].keys())
        for prop in ['disponibilites', 'mediagraphies', 'evaluations']:
            item = schema['properties'][prop]['items']
            assert set(item['required']) == set(item['properties'].keys())
        cap_item = schema['properties']['evaluations']['items']['properties']['capacites']['items']
        assert set(cap_item['required']) == set(cap_item['properties'].keys())

import os
import tempfile

from src.app.tasks.import_plan_de_cours import import_plan_de_cours_task
from src.app.models import Programme, Department, Cours, PlanCadre, PlanDeCours, User, SectionAISettings
from src.extensions import db


class FakeFiles:
    def __init__(self, recorder):
        self.recorder = recorder

    def create(self, file=None, purpose=None):
        # record uploaded file path and purpose
        try:
            # TextIOBase has .name, werkzeug FileStorage may wrap a path
            path = getattr(file, 'name', None)
        except Exception:
            path = None
        self.recorder['uploaded_path'] = path
        self.recorder['purpose'] = purpose
        return type('Up', (), {'id': 'file-test-id'})()


def make_fake_response(text_format):
    parsed_obj = text_format(
        presentation_du_cours="Texte PDC",
        objectif_terminal_du_cours="Obj",
        organisation_et_methodes="Org",
        accomodement="Acc",
        evaluation_formative_apprentissages="Form",
        evaluation_expression_francais="Lang",
        materiel="Mat",
        calendriers=[],
        disponibilites=[],
        mediagraphies=[],
        evaluations=[],
    )

    content = type('Cont', (), {'parsed': parsed_obj})()
    out = type('Out', (), {'content': [content]})()
    usage = type('U', (), {'input_tokens': 10, 'output_tokens': 20})()
    return type('Resp', (), {'usage': usage, 'output': [out]})()


class FakeResponses:
    def __init__(self, recorder):
        self.recorder = recorder

    def parse(self, model=None, input=None, text_format=None):  # noqa: A002
        # record the input structure
        self.recorder['input'] = input
        self.recorder['model'] = model
        return make_fake_response(text_format)


class FakeOpenAI:
    last_instance = None

    def __init__(self, api_key=None):  # noqa: ARG002
        self.calls = {}
        self.files = FakeFiles(self.calls)
        self.responses = FakeResponses(self.calls)
        FakeOpenAI.last_instance = self


def test_import_plan_de_cours_task_uses_file_upload_when_path_given(app, monkeypatch):
    # Arrange minimal DB objects
    with app.app_context():
        dept = Department(nom="Dep")
        db.session.add(dept)
        db.session.flush()
        prog = Programme(nom="Prog", department_id=dept.id)
        db.session.add(prog)
        db.session.flush()
        cours = Cours(code="C1", nom="Cours", heures_theorie=0, heures_laboratoire=0, heures_travail_maison=0)
        db.session.add(cours)
        db.session.flush()
        cours.programmes.append(prog)
        db.session.flush()
        pc = PlanCadre(cours_id=cours.id)
        db.session.add(pc)
        db.session.flush()
        plan = PlanDeCours(cours_id=cours.id, session="A25")
        db.session.add(plan)
        db.session.flush()
        user = User(username="u", password="x", email="u@example.com", openai_key="sk-test", credits=100.0)
        db.session.add(user)
        db.session.add(SectionAISettings(section='plan_de_cours_import', system_prompt=''))
        db.session.commit()

        # Create a temporary DOCX file
        from docx import Document
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            doc = Document()
            doc.add_paragraph("Plan de cours test")
            doc.save(path)

            # Call underlying function (avoid Celery runtime)
            class DummySelf:
                request = type('R', (), {'id': 'task-id'})()
                def update_state(self, state=None, meta=None):  # noqa: D401, ANN001
                    return None

            orig = import_plan_de_cours_task.__wrapped__.__func__
            result = orig(DummySelf(), plan.id, "texte brut", "gpt-5", user.id, path, FakeOpenAI)

            # Assert: success and file uploaded as PDF and input includes input_file block
            assert result.get('status') == 'success'
            uploaded = FakeOpenAI.last_instance.calls.get('uploaded_path')
            assert uploaded is not None and uploaded.endswith('.pdf')
            recorded_input = FakeOpenAI.last_instance.calls.get('input')
            assert isinstance(recorded_input, list)
            # ensure presence of an input_file item
            assert any(any(c.get('type') == 'input_file' for c in blk.get('content', [])) for blk in recorded_input)
        finally:
            if os.path.exists(path):
                os.remove(path)

import io
import os
from werkzeug.datastructures import FileStorage

from src.app.models import Programme, Department, Cours, PlanCadre, PlanDeCours, User, SectionAISettings
from src.app import db


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


class FakeFiles:
    def __init__(self, recorder):
        self.recorder = recorder

    def create(self, file=None, purpose=None):
        self.recorder['purpose'] = purpose
        self.recorder['uploaded_path'] = getattr(file, 'name', None)
        return type('Up', (), {'id': 'file-sync-id'})()


def _fake_response(text_format):
    parsed = text_format(
        presentation_du_cours="P",
        objectif_terminal_du_cours="O",
        organisation_et_methodes="M",
        accomodement="A",
        evaluation_formative_apprentissages="F",
        evaluation_expression_francais="L",
        materiel="X",
        calendriers=[], disponibilites=[], mediagraphies=[], evaluations=[],
    )
    content = type('Cont', (), {'parsed': parsed})()
    out = type('Out', (), {'content': [content]})()
    usage = type('U', (), {'input_tokens': 10, 'output_tokens': 20})()
    return type('Resp', (), {'usage': usage, 'output': [out]})()


class FakeResponses:
    def __init__(self, recorder):
        self.recorder = recorder

    def parse(self, model=None, input=None, text_format=None):
        self.recorder['input'] = input
        self.recorder['model'] = model
        return _fake_response(text_format)


class FakeOpenAI:
    last = None
    def __init__(self, api_key=None):  # noqa: ARG002
        self.calls = {}
        self.files = FakeFiles(self.calls)
        self.responses = FakeResponses(self.calls)
        FakeOpenAI.last = self


def test_import_docx_sync_uses_pdf_upload(client, app, monkeypatch, tmp_path):
    # Setup DB
    with app.app_context():
        dept = Department(nom="D")
        db.session.add(dept); db.session.flush()
        prog = Programme(nom="P", department_id=dept.id)
        db.session.add(prog); db.session.flush()
        cours = Cours(code="C1", nom="C", heures_theorie=0, heures_laboratoire=0, heures_travail_maison=0)
        db.session.add(cours); db.session.flush()
        cours.programmes.append(prog); db.session.flush()
        pc = PlanCadre(cours_id=cours.id)
        db.session.add(pc); db.session.flush()
        pdc = PlanDeCours(cours_id=cours.id, session="A25")
        db.session.add(pdc); db.session.flush()
        user = User(username="u", password="x", openai_key="sk", credits=100.0, is_first_connexion=False)
        db.session.add(user)
        db.session.add(SectionAISettings(section='plan_de_cours_import', system_prompt=''))
        db.session.commit()

        _login(client, user.id)

        # Create a minimal DOCX file in memory and save to temp path for our POST
        from docx import Document
        doc = Document(); doc.add_paragraph("Hello Sync")
        buffer = io.BytesIO(); doc.save(buffer); buffer.seek(0)
        fs = (io.BytesIO(buffer.read()), 'test.docx')

        # Monkeypatch OpenAI
        import openai as openai_pkg
        monkeypatch.setattr(openai_pkg, 'OpenAI', FakeOpenAI)
        import sys
        mod = sys.modules.get('src.app.routes.plan_de_cours')
        if mod is not None:
            monkeypatch.setattr(mod, 'OpenAI', FakeOpenAI, raising=False)

        data = {
            'cours_id': str(cours.id),
            'session': 'A25',
        }
        resp = client.post('/import_docx', data={
            'file': fs,
            **data
        }, content_type='multipart/form-data')

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['fields']['presentation_du_cours'] == 'P'
        # Ensure an input_file was provided
        recorded_input = FakeOpenAI.last.calls.get('input')
        assert isinstance(recorded_input, (list, tuple))
        assert any(any(c.get('type') == 'input_file' for c in blk.get('content', [])) for blk in recorded_input)

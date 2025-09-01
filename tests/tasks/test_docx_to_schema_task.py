from pathlib import Path
from types import SimpleNamespace
import logging

from docx import Document

from src.app.models import User, db, OpenAIModel
class DummySelf:
    def __init__(self):
        self.request = type('R', (), {'id': 'tid'})()
        self.updates = []

    def update_state(self, state=None, meta=None):
        self.updates.append(meta or {})


class DummyEvent:
    def __init__(self, t, delta):
        self.type = t
        self.delta = delta


class FakeStream:
    def __init__(self, events, final):
        self.events = events
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_response(self):
        return self._final


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        events = [
            DummyEvent('response.output_text.delta', 'hello'),
            DummyEvent('response.reasoning_summary_text.delta', 'because')
        ]
        class Usage:
            input_tokens = 1
            output_tokens = 2
        class Resp:
            output_parsed = {
                'title': 'T',
                'description': 'D',
                'type': 'object',
                'properties': {}
            }
            usage = Usage()
        return FakeStream(events, Resp())


class FakeFiles:
    def create(self, file=None, purpose=None):  # noqa: ARG002
        return type('F', (), {'id': 'fid'})()


class FakeOpenAI:
    last_instance = None
    def __init__(self, api_key=None):  # noqa: ARG002
        self.files = FakeFiles()
        self.responses = FakeResponses()
        FakeOpenAI.last_instance = self


def test_docx_to_schema_streaming(app, tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    docx_path = tmp_path / 'test.docx'
    doc = Document()
    doc.add_paragraph('Hello world')
    doc.save(docx_path)

    def fake_run(cmd, **kwargs):  # noqa: ARG001
        assert 'libreoffice' in cmd[0]
        pdf_path = Path(cmd[-1]).with_suffix('.pdf')
        pdf_path.write_bytes(b'%PDF-1.4')
        return SimpleNamespace(returncode=0)

    import src.app.tasks.docx_to_schema as module
    monkeypatch.setattr(module, 'subprocess', SimpleNamespace(run=fake_run))

    with app.app_context():
        user = User(username='u', password='pw', role='user', openai_key='sk', credits=1.0, is_first_connexion=False)
        db.session.add(user)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        db.session.commit()
        uid = user.id

    dummy = DummySelf()
    orig = module.docx_to_json_schema_task.__wrapped__.__func__
    prompt = "Propose un schéma JSON simple"
    result = orig(dummy, str(docx_path), 'gpt-4o-mini', 'medium', 'medium', prompt, uid, FakeOpenAI)
    assert result['status'] == 'success'
    assert any('stream_chunk' in u for u in dummy.updates)
    assert any(u.get('stream_chunk') and u.get('message') == 'Analyse en cours...' for u in dummy.updates)
    assert any(u.get('message') == 'Résumé du raisonnement' for u in dummy.updates)
    assert result['result']['title'] == 'T'
    called_kwargs = FakeOpenAI.last_instance.responses.kwargs
    assert called_kwargs['store'] is True
    assert 'format' not in called_kwargs.get('text', {})
    assert 'Propose un schéma JSON simple' in called_kwargs['input'][0]['content'][0]['text']
    assert 'OpenAI usage' in caplog.text

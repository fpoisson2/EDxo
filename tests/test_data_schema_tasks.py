import json
from types import SimpleNamespace

from src.app.models import db, User, DocxSchemaPage, OpenAIModel, DocxSchemaEntry


class DummySelf:
    def __init__(self):
        self.request = type('R', (), {'id': 'tid'})()
        self.updates = []

    def update_state(self, state=None, meta=None):  # noqa: ARG002
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
    def __init__(self, output_text):
        self.kwargs = None
        self.output_text = output_text

    def stream(self, **kwargs):
        self.kwargs = kwargs
        events = [
            DummyEvent('response.output_text.delta', 'chunk1'),
            DummyEvent('response.output_text.delta', 'chunk2'),
            DummyEvent('response.reasoning_summary_text.delta', 'reasoning...'),
        ]

        class Usage:
            input_tokens = 10
            output_tokens = 20

        class Resp:
            usage = Usage()
            output_parsed = None
            output_text = self.output_text

        return FakeStream(events, Resp())


class FakeOpenAI:
    last_instance = None
    expected_json = None

    def __init__(self, api_key=None):  # noqa: ARG002
        self.responses = FakeResponses(json.dumps(FakeOpenAI.expected_json))
        self.files = SimpleNamespace(create=lambda file=None, purpose=None: SimpleNamespace(id='fid'))
        FakeOpenAI.last_instance = self


def _make_page(app):
    with app.app_context():
        user = User(username='u', password='pw', role='user', openai_key='sk', credits=10.0, is_first_connexion=False)
        db.session.add(user)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        schema = {
            'title': 'Programme',
            'type': 'object',
            'properties': {
                'title': {'type': 'string', 'title': 'Titre'},
                'sessions': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'numero': {'type': 'integer', 'title': 'Session'},
                            'cours': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'code': {'type': 'string'},
                                        'nom': {'type': 'string'},
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        page = DocxSchemaPage(title='P', json_schema=schema)
        db.session.add(page)
        db.session.commit()
        return user.id, page.id


def test_generate_entry_task_persists_entry(app, monkeypatch):
    uid, page_id = _make_page(app)
    FakeOpenAI.expected_json = {
        'title': 'Programme Test',
        'sessions': [{'numero': 1, 'cours': [{'code': 'AAA', 'nom': 'Intro'}]}]
    }

    import src.app.tasks.data_schema as module
    dummy = DummySelf()
    res = module.data_schema_generate_entry_task.__wrapped__.__func__(
        dummy,
        page_id=page_id,
        user_id=uid,
        system_prompt='Génère un programme.',
        model='gpt-4o-mini',
        reasoning='medium',
        verbosity='medium',
        extra_instructions='Aucune contrainte',
        openai_cls=FakeOpenAI,
    )
    assert res['status'] == 'success'
    assert 'entry_id' in res['result']
    assert res['validation_url'].endswith(f"/docx_schema/{page_id}/entries/{res['result']['entry_id']}/edit")
    with app.app_context():
        entry = db.session.get(DocxSchemaEntry, res['result']['entry_id'])
        assert entry is not None
        assert entry.page_id == page_id
        assert entry.data['title'] == 'Programme Test'


def test_improve_entry_task_creates_new_entry(app, monkeypatch):
    uid, page_id = _make_page(app)
    with app.app_context():
        entry = DocxSchemaEntry(page_id=page_id, data={'title': 'Old', 'sessions': []})
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    FakeOpenAI.expected_json = {'title': 'Improved', 'sessions': []}
    import src.app.tasks.data_schema as module
    dummy = DummySelf()
    res = module.data_schema_improve_entry_task.__wrapped__.__func__(
        dummy,
        page_id=page_id,
        entry_id=entry_id,
        user_id=uid,
        system_prompt='Améliore.',
        model='gpt-4o-mini',
        reasoning='low',
        verbosity='low',
        extra_instructions='Conserver la structure',
        openai_cls=FakeOpenAI,
    )
    assert res['status'] == 'success'
    with app.app_context():
        new_id = res['result']['entry_id']
        assert new_id != entry_id
        new_entry = db.session.get(DocxSchemaEntry, new_id)
        assert new_entry is not None
        assert new_entry.data['title'] == 'Improved'


def test_import_from_file_task_uses_schema_and_persists(app, tmp_path, monkeypatch):
    uid, page_id = _make_page(app)
    fake_pdf = tmp_path / 'x.pdf'
    fake_pdf.write_bytes(b'%PDF-1.4')

    # Monkeypatch the _docx_to_pdf to bypass libreoffice
    import src.app.tasks.data_schema as module
    monkeypatch.setattr(module, '_docx_to_pdf', lambda p: str(fake_pdf))

    FakeOpenAI.expected_json = {'title': 'Importé', 'sessions': []}
    dummy = DummySelf()
    res = module.data_schema_import_from_file_task.__wrapped__.__func__(
        dummy,
        page_id=page_id,
        file_path=str(fake_pdf),
        user_id=uid,
        system_prompt='Importe ce document selon le schéma.',
        model='gpt-4o-mini',
        reasoning='high',
        verbosity='high',
        openai_cls=FakeOpenAI,
    )
    assert res['status'] == 'success'
    with app.app_context():
        new_id = res['result']['entry_id']
        e = db.session.get(DocxSchemaEntry, new_id)
        assert e is not None
        assert e.data['title'] == 'Importé'


import json
from types import SimpleNamespace

from src.app.models import db, User, DocxSchemaPage


class DummySelf:
    def __init__(self):
        self.request = type('R', (), {'id': 'tid'})()
        self.updates = []
    def update_state(self, state=None, meta=None):
        self.updates.append(meta or {})


class FakeResponses:
    def __init__(self, output_text):
        self.kwargs = None
        self.output_text = output_text
    def stream(self, **kwargs):
        self.kwargs = kwargs
        class Usage:
            input_tokens = 0
            output_tokens = 0
        class Resp:
            usage = Usage()
            output_parsed = None
            output_text = self.output_text
        class Stream:
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, exc_type, exc, tb):
                return False
            def __iter__(self_inner):
                return iter(())
            def get_final_response(self_inner):
                return Resp()
        return Stream()


class FakeOpenAI:
    last_instance = None
    def __init__(self, api_key=None):  # noqa: ARG002
        self.responses = FakeResponses(json.dumps({'ok': True}))
        self.files = SimpleNamespace(create=lambda file=None, purpose=None: SimpleNamespace(id='fid'))
        FakeOpenAI.last_instance = self


def test_strict_schema_injects_additional_properties_false_everywhere(app, tmp_path, monkeypatch):
    with app.app_context():
        user = User(username='su', password='pw', role='user', openai_key='sk', is_first_connexion=False)
        db.session.add(user)
        page = DocxSchemaPage(
            title='T',
            json_schema={
                'title': 'Programme',
                'type': 'object',
                'properties': {
                    'Code et nom du programme': {
                        'type': 'object',
                        'properties': {
                            'code': {'type': 'string'},
                            'nom': {'type': 'string'},
                        }
                    }
                }
            },
        )
        db.session.add(page)
        db.session.commit()
        uid, pid = user.id, page.id

    # Use a simple fake PDF
    fake_pdf = tmp_path / 'x.pdf'
    fake_pdf.write_bytes(b'%PDF-1.4')
    import src.app.tasks.data_schema as module
    monkeypatch.setattr(module, '_docx_to_pdf', lambda p: str(fake_pdf))

    dummy = DummySelf()
    res = module.data_schema_import_from_file_task.__wrapped__.__func__(
        dummy,
        page_id=pid,
        file_path=str(fake_pdf),
        user_id=uid,
        system_prompt='Extrait',
        model='gpt-4o-mini',
        reasoning='medium',
        verbosity='medium',
        openai_cls=FakeOpenAI,
    )
    # Ensure we passed a strict schema with additionalProperties: false at nested object
    kwargs = FakeOpenAI.last_instance.responses.kwargs or {}
    tf = kwargs.get('text') or {}
    fmt = tf.get('format') or {}
    schema = fmt.get('schema') or {}
    assert schema.get('additionalProperties') is False
    # Required must include all properties
    assert isinstance(schema.get('required'), list)
    assert set(schema['required']) == set(schema['properties'].keys())
    inner = schema['properties']['Code et nom du programme']
    assert inner.get('additionalProperties') is False
    assert isinstance(inner.get('required'), list)
    assert set(inner['required']) == set(inner['properties'].keys())
    # And task still reports success
    assert res['status'] == 'success'

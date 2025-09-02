from types import SimpleNamespace

from src.app.models import db, DocxSchemaPage, SectionAISettings, DocxSchemaEntry, User, OpenAIModel


class DummyDelay:
    def __init__(self):
        self.called = False
        self.kwargs = None
        self.id = 'tid'

    def __call__(self, **kwargs):
        self.called = True
        self.kwargs = kwargs
        return SimpleNamespace(id=self.id)


def _ensure_page(app):
    with app.app_context():
        from werkzeug.security import generate_password_hash
        user = User(username='u3', password=generate_password_hash('pw'), role='admin', openai_key='sk', credits=1.0, is_first_connexion=False)
        db.session.add(user)
        db.session.add(OpenAIModel(name='gpt-4o-mini', input_price=0.0, output_price=0.0))
        page = DocxSchemaPage(title='S', json_schema={'type': 'object', 'properties': {'title': {'type': 'string'}}})
        db.session.add(page)
        db.session.commit()
        return user.id, page.id


def test_generate_start_uses_per_page_settings(app, client, monkeypatch):
    uid, page_id = _ensure_page(app)
    with app.app_context():
        sa = SectionAISettings.get_for(f'docx_schema_{page_id}')
        sa.system_prompt = 'GEN SYS'
        sa.ai_model = 'gpt-4o-mini'
        sa.reasoning_effort = 'low'
        sa.verbosity = 'high'
        db.session.commit()

    dummy = DummyDelay()
    # Patch the task symbol in the route function globals (no easy import path)
    from flask import current_app as _ca
    with app.app_context():
        func = app.view_functions.get('main.docx_schema_generate_start')
        assert func is not None
        # unwrap decorators
        real = func
        while hasattr(real, '__wrapped__'):
            real = real.__wrapped__
        real.__globals__['data_schema_generate_entry_task'] = SimpleNamespace(delay=dummy)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True
    r = client.post(f'/docx_schema/{page_id}/generate/start', json={'additional_info': 'ctx'})
    assert r.status_code == 202
    assert dummy.called
    assert dummy.kwargs['page_id'] == page_id
    assert dummy.kwargs['model'] == 'gpt-4o-mini'
    assert dummy.kwargs['system_prompt'] == 'GEN SYS'


def test_improve_start_uses_per_page_settings(app, client, monkeypatch):
    uid, page_id = _ensure_page(app)
    with app.app_context():
        entry = DocxSchemaEntry(page_id=page_id, data={'title': 'x'})
        db.session.add(entry)
        sa = SectionAISettings.get_for(f'docx_schema_{page_id}_improve')
        sa.system_prompt = 'IMP SYS'
        sa.ai_model = 'gpt-4o-mini'
        sa.reasoning_effort = 'medium'
        sa.verbosity = 'low'
        db.session.commit()
        eid = entry.id

    dummy = DummyDelay()
    with app.app_context():
        func = app.view_functions.get('main.docx_schema_improve_start')
        assert func is not None
        real = func
        while hasattr(real, '__wrapped__'):
            real = real.__wrapped__
        real.__globals__['data_schema_improve_entry_task'] = SimpleNamespace(delay=dummy)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True
    r = client.post(f'/docx_schema/{page_id}/improve/start', json={'entry_id': eid, 'additional_info': 'ctx'})
    assert r.status_code == 202
    assert dummy.called
    assert dummy.kwargs['entry_id'] == eid
    assert dummy.kwargs['model'] == 'gpt-4o-mini'
    assert dummy.kwargs['system_prompt'] == 'IMP SYS'


def test_import_start_uses_per_page_settings(app, client, tmp_path, monkeypatch):
    uid, page_id = _ensure_page(app)
    with app.app_context():
        sa = SectionAISettings.get_for(f'docx_schema_{page_id}_import')
        sa.system_prompt = 'IMPT SYS'
        sa.ai_model = 'gpt-4o-mini'
        sa.reasoning_effort = 'high'
        sa.verbosity = 'high'
        db.session.commit()

    dummy = DummyDelay()
    with app.app_context():
        func = app.view_functions.get('main.docx_schema_import_start')
        assert func is not None
        real = func
        while hasattr(real, '__wrapped__'):
            real = real.__wrapped__
        real.__globals__['data_schema_import_from_file_task'] = SimpleNamespace(delay=dummy)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True
    fake = tmp_path / 't.pdf'
    fake.write_bytes(b'%PDF-1.4')
    with open(fake, 'rb') as fh:
        r = client.post(f'/docx_schema/{page_id}/import/start', data={'file': (fh, 't.pdf')})
    assert r.status_code == 202
    assert dummy.called
    assert dummy.kwargs['page_id'] == page_id
    assert dummy.kwargs['system_prompt'] == 'IMPT SYS'
    assert dummy.kwargs['model'] == 'gpt-4o-mini'

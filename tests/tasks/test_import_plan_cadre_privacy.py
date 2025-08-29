from src.app.tasks.import_plan_cadre import import_plan_cadre_preview_task


class DummySelf:
    def __init__(self):
        self.updates = []
        self.request = type('R', (), {'id': 'task-id'})()

    def update_state(self, state=None, meta=None):
        # Record meta for assertions
        self.updates.append(meta or {})


def test_import_plan_cadre_preview_task_does_not_emit_verbose_messages(app):
    dummy = DummySelf()
    # Call the underlying function directly to avoid Celery runtime
    orig = import_plan_cadre_preview_task.__wrapped__.__func__
    # Use a non-existent plan_cadre_id to exit early after the first progress push
    result = orig(dummy, plan_cadre_id=999999, doc_text="x", ai_model="gpt-5", user_id=123, file_path=None)

    # Should have emitted at least one PROGRESS update, but without 'message'/'stream_buffer'
    assert any(u for u in dummy.updates), "Expected at least one state update"
    for u in dummy.updates:
        assert 'stream_buffer' not in (u or {}), "stream_buffer must not be sent in status updates"
        # Allow 'Résumé du raisonnement' message elsewhere in the task, but not here
        assert 'message' not in (u or {}), "verbose 'message' must not be sent for plan-cadre import preview"

    # Task returns an error for missing plan-cadre, which is fine for this test
    assert result.get('status') in {"error", "success"}


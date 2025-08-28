import os


def test_task_orchestrator_injects_spinner_css_twice():
    """
    The orchestrator should ensure spinner CSS is injected not only in the quick modal
    but also when the main tracking modal is created. This guards the fix for missing
    blue spinner on import tasks that use only the file modal.
    """
    js_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'static', 'js', 'task_orchestrator.js')
    js_path = os.path.normpath(js_path)
    with open(js_path, 'r', encoding='utf-8') as fh:
        content = fh.read()
    # We expect the spinner style id to appear in both quick modal and main modal initializers
    assert content.count('edxo-task-spinner-style') >= 2


import os
import pathlib
import pytest


pytestmark = pytest.mark.skipif(os.environ.get('EDXO_E2E', '0') != '1', reason='Skip E2E unless EDXO_E2E=1')


def _read_js():
    here = pathlib.Path(__file__).resolve()
    js_path = here.parents[2] / 'src' / 'static' / 'js' / 'task_orchestrator.js'
    return js_path.read_text(encoding='utf-8')


def test_modal_receives_stream_and_reasoning(page):
    js = _read_js()
    html = f"""
    <html>
      <head>
        <meta charset='utf-8'>
        <style>body {{ font-family: sans-serif; }}</style>
        <script>
          // Bootstrap minimal stub
          window.bootstrap = {{
            Modal: {{
              getOrCreateInstance(el) {{
                return {{ show(){{}}, hide(){{}} }};
              }}
            }}
          }};
          // Notifications stub
          window.addNotification = function(){{}};
          // SSE stub (unused)
          window.EventSource = function(){{ return {{ addEventListener(){{}}, close(){{}} }}; }};
          // fetch stub to serve status snapshots
          const responses = {{
            '/tasks/status/t-1': {{ state: 'PROGRESS', meta: {{ stream_buffer: 'Bonjour ', reasoning_summary: 'Raison' }} }},
          }};
          window.fetch = async function(url, opts) {{
            if (typeof url === 'string' && url.includes('/start')) {{
              return new Response(JSON.stringify({{ task_id: 't-1' }}), {{ headers: {{ 'Content-Type': 'application/json' }} }});
            }}
            if (typeof url === 'string' && url.includes('/tasks/status/t-1')) {{
              return new Response(JSON.stringify(responses['/tasks/status/t-1']), {{ headers: {{ 'Content-Type': 'application/json' }} }});
            }}
            return new Response(JSON.stringify({{}}), {{ headers: {{ 'Content-Type': 'application/json' }} }});
          }};
        </script>
        <script>{js}</script>
      </head>
      <body>
      </body>
    </html>
    """
    page.set_content(html)
    # Open modal and trigger initial snapshot
    page.evaluate("window.EDxoTasks.openTaskModal('t-1', { title: 'Test' })")
    # Wait for DOM
    page.wait_for_selector('#taskStartModal, #taskOrchModal', state='attached')
    # Expect the stream text and reasoning to be visible (initialSnap uses status fetch)
    page.wait_for_selector('#task-orch-stream-text')
    stream_text = page.eval_on_selector('#task-orch-stream-text', 'el => el.textContent')
    reasoning = page.eval_on_selector('#task-orch-reasoning', 'el => el.textContent')
    assert 'Bonjour' in stream_text
    assert 'Raison' in reasoning


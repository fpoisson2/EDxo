import json
from src.app.routes.chat.stream import simple_stream


def test_simple_stream_outputs_message():
    gen = simple_stream('hello', [])
    data = list(gen)
    first = json.loads(data[0].split(': ', 1)[1])
    assert first['content'] == 'hello'
    assert data[-1].strip() == 'data: {"type": "done"}'

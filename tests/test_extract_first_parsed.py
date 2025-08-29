from src.app.tasks.generation_plan_de_cours import _extract_first_parsed


class DummyContent:
    def __init__(self, parsed=None):
        self.parsed = parsed


class DummyItem:
    def __init__(self, content=None):
        self.content = content or []


class DummyResponse:
    def __init__(self, output=None, output_parsed=None):
        if output is not None:
            self.output = output
        if output_parsed is not None:
            self.output_parsed = output_parsed


def test_extract_from_output_parsed():
    parsed_obj = {"a": 1}
    response = DummyResponse(output_parsed=[parsed_obj])
    assert _extract_first_parsed(response) == parsed_obj


def test_extract_from_nested_content():
    parsed_obj = {"b": 2}
    response = DummyResponse(output=[DummyItem([DummyContent(parsed_obj)])])
    assert _extract_first_parsed(response) == parsed_obj

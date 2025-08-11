import tiktoken
from src.app.routes.chat import estimate_tokens_for_text


class DummyEncoding:
    def encode(self, text: str):
        return text.split()


def test_estimate_tokens_for_text_fallback(monkeypatch):
    def mock_encoding_for_model(model):
        raise KeyError("unknown model")

    def mock_get_encoding(name):
        assert name == "cl100k_base"
        return DummyEncoding()

    monkeypatch.setattr(tiktoken, "encoding_for_model", mock_encoding_for_model)
    monkeypatch.setattr(tiktoken, "get_encoding", mock_get_encoding)

    text = "Un petit test de tokenisation"
    manual_count = len(text.split())
    estimated = estimate_tokens_for_text(text, model="modele-fictif")
    assert estimated == manual_count

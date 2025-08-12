import pytest
from utils.recaptcha import verify_recaptcha


def test_verify_recaptcha_success(app, monkeypatch):
    """The helper returns True when the API validates the token."""
    def mock_post(url, data, timeout=None):
        class MockResponse:
            def json(self):
                return {"success": True, "score": 0.9}
        return MockResponse()

    monkeypatch.setattr("utils.recaptcha.requests.post", mock_post)
    with app.test_request_context('/'):
        assert verify_recaptcha("token") is True


def test_verify_recaptcha_failure(app, monkeypatch):
    """The helper returns False when verification fails."""
    def mock_post(url, data, timeout=None):
        class MockResponse:
            def json(self):
                return {"success": False, "score": 0.1}
        return MockResponse()

    monkeypatch.setattr("utils.recaptcha.requests.post", mock_post)
    with app.test_request_context('/'):
        assert verify_recaptcha("token") is False


def test_verify_recaptcha_missing_token(app):
    """A missing token should return False without calling the API."""
    with app.test_request_context('/'):
        assert verify_recaptcha("") is False


def test_verify_recaptcha_exception(app, monkeypatch):
    """The helper returns False when requests.post raises an exception."""

    def mock_post(url, data, timeout=None):
        raise RuntimeError("boom")

    monkeypatch.setattr("utils.recaptcha.requests.post", mock_post)
    with app.test_request_context('/'):
        assert verify_recaptcha("token") is False

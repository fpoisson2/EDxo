"""Tests ensuring the Flask application can be imported without errors."""

import importlib
from types import ModuleType


def test_wsgi_application_import(monkeypatch) -> None:
    """Import the WSGI entrypoint and ensure the app instance is created."""

    # Provide required environment variables so ``create_app`` validation passes
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.setenv("RECAPTCHA_PUBLIC_KEY", "test")
    monkeypatch.setenv("RECAPTCHA_PRIVATE_KEY", "test")
    # Prevent scheduler start up during tests
    monkeypatch.setenv("CELERY_WORKER", "1")

    # Ensure configuration module observes the new environment
    import config.env as env
    importlib.reload(env)

    wsgi: ModuleType = importlib.import_module("src.wsgi")

    assert getattr(wsgi, "application", None) is not None


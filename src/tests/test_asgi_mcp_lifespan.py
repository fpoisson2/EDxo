import importlib


def test_parent_asgi_app_uses_mcp_lifespan(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "testing")
    monkeypatch.setenv("RECAPTCHA_PUBLIC_KEY", "testing")
    monkeypatch.setenv("RECAPTCHA_PRIVATE_KEY", "testing")
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "cache+memory://")
    import src.config.env as env
    monkeypatch.setattr(env, "SECRET_KEY", "testing", raising=False)
    monkeypatch.setattr(env, "RECAPTCHA_PUBLIC_KEY", "testing", raising=False)
    monkeypatch.setattr(env, "RECAPTCHA_PRIVATE_KEY", "testing", raising=False)

    # Create a dummy ASGI app with a recognizable lifespan callable
    class DummyASGI:
        async def __call__(self, scope, receive, send):
            pass

    async def dummy_lifespan(app):  # sentinel object to assert identity
        yield

    dummy = DummyASGI()
    setattr(dummy, "lifespan", dummy_lifespan)

    # Patch MCP factory to return our dummy app
    import src.mcp_server.server as srv
    monkeypatch.setattr(srv, "get_mcp_asgi_app", lambda: dummy, raising=True)

    # Reload the ASGI hub to rebuild with our patched MCP app
    asgi_mod = importlib.import_module("src.asgi")
    importlib.reload(asgi_mod)

    # The CORSMiddleware-wrapped MCP app should preserve the child's lifespan attribute
    wrapped = asgi_mod.mcp_asgi_app
    assert getattr(wrapped, "lifespan", None) is dummy_lifespan

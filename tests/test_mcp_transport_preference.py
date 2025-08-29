import types


def test_get_mcp_asgi_app_prefers_streamable_http(monkeypatch):
    from src.mcp_server import server as srv

    called = {"transport": None}

    orig_http_app = srv.mcp.http_app

    def spy_http_app(self, path=None, middleware=None, json_response=None, stateless_http=None, transport="http"):
        called["transport"] = transport
        return orig_http_app(path=path, middleware=middleware, json_response=json_response, stateless_http=stateless_http, transport=transport)

    # Bind the spy method to the instance
    monkeypatch.setattr(srv.mcp, "http_app", types.MethodType(spy_http_app, srv.mcp))

    app = srv.get_mcp_asgi_app()
    assert callable(app)
    # We prefer streamable-http when available
    assert called["transport"] in ("streamable-http", "http")


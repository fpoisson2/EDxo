import pytest

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def make_app(mw):
    async def echo_auth(request):
        # Starlette lowercases header lookup; returns None if missing
        auth = request.headers.get("authorization")
        return JSONResponse({"authorization": auth})

    app = Starlette(routes=[Route("/", echo_auth)])
    return mw(app)


def test_injects_authorization_from_query_when_missing():
    from src.asgi import InjectAuthFromQuery

    app = make_app(InjectAuthFromQuery)
    with TestClient(app) as client:
        r = client.get("/?access_token=abc123")
        assert r.status_code == 200
        assert r.json()["authorization"] == "Bearer abc123"


def test_does_not_override_existing_authorization_header():
    from src.asgi import InjectAuthFromQuery

    app = make_app(InjectAuthFromQuery)
    with TestClient(app) as client:
        r = client.get("/?access_token=abc123", headers={"Authorization": "Bearer preexisting"})
        assert r.status_code == 200
        # Should keep the preexisting header
        assert r.json()["authorization"] == "Bearer preexisting"


def test_no_injection_without_query_param():
    from src.asgi import InjectAuthFromQuery

    app = make_app(InjectAuthFromQuery)
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["authorization"] is None


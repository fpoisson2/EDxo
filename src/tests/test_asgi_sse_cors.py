from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount
from starlette.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient
import pytest


@pytest.mark.asyncio
async def test_tasks_events_sse_includes_cors_header_direct():
    # Call the SSE handler directly to validate response headers
    from src.asgi import sse_task_events
    from starlette.requests import Request

    scope = {
        "type": "http",
        "path_params": {"task_id": "dummy"},
        "headers": [],
    }
    req = Request(scope)
    resp = await sse_task_events(req)
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"


def test_cors_preflight_on_sse_mount_style():
    # Simulate the /sse mount wrapped with CORSMiddleware similar to asgi.py
    async def pong(_request):
        return JSONResponse({"ok": True})

    mcp_like = Starlette(routes=[Route("/", pong)])
    mcp_with_cors = CORSMiddleware(
        mcp_like,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
        allow_credentials=False,
    )

    hub = Starlette(routes=[Mount("/sse", app=mcp_with_cors)])

    with TestClient(hub) as client:
        pre = client.options(
            "/sse/",
            headers={
                "Origin": "https://example.dev",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert pre.status_code in (200, 204)
        assert pre.headers.get("Access-Control-Allow-Origin") == "*"
        allow_methods = pre.headers.get("Access-Control-Allow-Methods") or ""
        assert "POST" in allow_methods or allow_methods == "*"

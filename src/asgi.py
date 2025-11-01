"""ASGI hub: mounts MCP under /sse and Flask under /."""

import os

# Ensure Flask side does not try to mount SSE endpoints; ASGI handles /sse
os.environ.setdefault("EDXO_MCP_SSE_DISABLE", "1")

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.responses import StreamingResponse
from urllib.parse import parse_qs
from starlette.middleware.wsgi import WSGIMiddleware
from starlette.middleware.cors import CORSMiddleware
import asyncio
import json

# Reuse Celery app and helper checks
from src.celery_app import celery
from src.app.routes.tasks import _is_cancel_requested, _is_task_known


async def sse_task_events(request: Request):
    """ASGI-native SSE stream for task progress to avoid blocking WSGI threads."""
    try:
        task_id = request.path_params.get("task_id")
        if not task_id:
            return StreamingResponse(iter(()), status_code=400)

        async def event_iter():
            yield "event: open\ndata: {}\n\n"
            last_nonstream_snapshot = None
            last_stream_len = 0
            last_reason_len = 0
            while True:
                try:
                    from celery.result import AsyncResult
                    res = AsyncResult(task_id, app=celery)
                    state = res.state
                    meta = res.info if isinstance(res.info, dict) else {}

                    # Mirror best-effort REVOKED mapping from Flask route
                    if state == "PENDING":
                        if _is_cancel_requested(task_id):
                            state = "REVOKED"
                            meta = {**(meta or {}), "message": meta.get("message") or "Tâche annulée (avant démarrage)."}
                        else:
                            # Periodic existence check is done in Flask route every ~15s; keep it lean here
                            pass

                    # Prepare lightweight meta for streaming: send only deltas for large fields
                    out_meta = dict(meta or {})
                    sent_chunk = False
                    # Stream buffer delta
                    try:
                        sb = out_meta.get("stream_buffer")
                        if isinstance(sb, str):
                            if len(sb) > last_stream_len:
                                chunk = sb[last_stream_len:]
                                out_meta["stream_chunk"] = chunk
                                sent_chunk = True
                                last_stream_len = len(sb)
                            # Avoid resending full buffer on progress
                            out_meta.pop("stream_buffer", None)
                    except Exception:
                        pass
                    # Reasoning summary: send delta if it grew; keep full for context
                    try:
                        rs = out_meta.get("reasoning_summary")
                        if isinstance(rs, str):
                            if len(rs) < last_reason_len:
                                # reset detected (new phase)
                                last_reason_len = 0
                            if len(rs) > last_reason_len:
                                rchunk = rs[last_reason_len:]
                                out_meta["reasoning_chunk"] = rchunk
                                last_reason_len = len(rs)
                    except Exception:
                        pass

                    # Change detection without heavy buffers
                    try:
                        nonstream = dict(out_meta)
                        nonstream.pop("stream_chunk", None)
                        nonstream.pop("stream_buffer", None)
                        snapshot = (state, json.dumps(nonstream, sort_keys=True, ensure_ascii=False))
                    except Exception:
                        snapshot = (state, "{}")

                    if sent_chunk or snapshot != last_nonstream_snapshot:
                        payload = {"state": state, "meta": out_meta}
                        yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        last_nonstream_snapshot = snapshot

                    if state in ("SUCCESS", "FAILURE", "REVOKED"):
                        # On final event, include full meta (with complete stream_buffer if present)
                        final_result = res.result if state == "SUCCESS" else None
                        try:
                            if state == "SUCCESS" and isinstance(final_result, dict) and final_result.get('status') == 'error':
                                state = "FAILURE"
                        except Exception:
                            pass
                        payload = {"state": state, "result": (final_result if state == "SUCCESS" else None), "meta": meta}
                        yield f"event: done\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        return

                    yield "event: ping\ndata: {}\n\n"
                    await asyncio.sleep(0.10)
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    err = {"error": str(e)}
                    yield f"event: error\ndata: {json.dumps(err, ensure_ascii=False)}\n\n"
                    return

        headers = {
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            # Allow cross-origin EventSource consumers
            "Access-Control-Allow-Origin": "*",
        }
        return StreamingResponse(event_iter(), media_type="text/event-stream", headers=headers)
    except Exception:
        # As a last resort, indicate SSE not available
        return StreamingResponse(iter(()), status_code=500)

from src.app.__init__ import create_app
from src.mcp_server.server import get_mcp_asgi_app, TOOL_NAMES
from src.utils.logging_config import get_logger

# Create the Flask WSGI app and wrap it for ASGI
flask_app = create_app(testing=False)
flask_asgi = WSGIMiddleware(flask_app)

# Obtain the MCP ASGI app (robust to missing integrations), capture lifespan, then wrap with CORS
mcp_asgi_app = get_mcp_asgi_app()
mcp_lifespan = getattr(mcp_asgi_app, "lifespan", None)

# Configure permissive CORS for the MCP mount to support browser clients
# Allowed origins can be tuned via EDXO_MCP_CORS_ORIGINS (comma-separated)
try:
    cors_origins_env = os.getenv("EDXO_MCP_CORS_ORIGINS", "*").strip()
    allow_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()] or ["*"]
except Exception:
    allow_origins = ["*"]

mcp_asgi_app = CORSMiddleware(
    mcp_asgi_app,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    allow_credentials=False,
)

# Preserve lifespan reference for parent Starlette app construction
if mcp_lifespan is not None:
    try:
        setattr(mcp_asgi_app, "lifespan", mcp_lifespan)
    except Exception:
        pass


class InjectAuthFromQuery:
    """ASGI middleware: promote `?access_token=` to Authorization header.

    Some clients (e.g., MCP Inspector or simple SSE consumers) cannot always set
    custom headers. Per RFC 6750 (section 2.3), allow passing the bearer token
    via URI query parameter `access_token`. If present and no `Authorization`
    header is set, inject `Authorization: Bearer <token>` into the request.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            if scope.get("type") == "http":
                headers = list(scope.get("headers") or [])
                has_auth = any(k.lower() == b"authorization" for k, _ in headers)
                if not has_auth:
                    raw_qs = scope.get("query_string") or b""
                    if raw_qs:
                        qs = parse_qs(raw_qs.decode("utf-8"), keep_blank_values=True)
                        token = None
                        vals = qs.get("access_token")
                        if isinstance(vals, list) and vals:
                            token = vals[-1]
                        if token:
                            headers.append((b"authorization", f"Bearer {token}".encode("utf-8")))
                            scope = dict(scope)
                            scope["headers"] = headers
        except Exception:
            # Best-effort: never block the request due to middleware errors
            pass
        return await self.app(scope, receive, send)

logger = get_logger(__name__)
try:
    is_fallback = getattr(mcp_asgi_app, "edxo_mcp_fallback", False)
    if is_fallback:
        logger.info(
            "MCP ASGI fallback active at /sse/ (root=501)",
            extra={"tools": TOOL_NAMES},
        )
    else:
        logger.info("MCP ASGI endpoint mounted at /sse/", extra={"tools": TOOL_NAMES})
except Exception:
    pass

# Compose the ASGI hub
lifespan = mcp_lifespan if mcp_lifespan is not None else getattr(mcp_asgi_app, "lifespan", None)
kwargs = {"routes": [
    # ASGI-native SSE for Celery task events; declared before Flask mount to take precedence
    Route("/tasks/events/{task_id}", endpoint=sse_task_events),
    # Allow passing OAuth tokens via `?access_token=` to the MCP SSE mount
    Mount("/sse", app=InjectAuthFromQuery(mcp_asgi_app)),
    Mount("/", app=flask_asgi),
]}
if lifespan is not None:
    kwargs["lifespan"] = lifespan
app = Starlette(**kwargs)

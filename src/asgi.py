"""ASGI hub: mounts MCP under /sse and Flask under /."""

import os

# Ensure Flask side does not try to mount SSE endpoints; ASGI handles /sse
os.environ.setdefault("EDXO_MCP_SSE_DISABLE", "1")

from asgiref.wsgi import WsgiToAsgi
from starlette.applications import Starlette
from starlette.routing import Mount

from src.app.__init__ import create_app
from src.mcp_server.server import get_mcp_asgi_app, TOOL_NAMES
from src.utils.logging_config import get_logger

# Create the Flask WSGI app and wrap it for ASGI
flask_app = create_app(testing=False)
flask_asgi = WsgiToAsgi(flask_app)

# Obtain the MCP ASGI app (robust to missing integrations)
def _normalize_root_path(app):
    async def _app(scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path") or ""
            if path == "":
                # Some clients hit the mount root without a trailing slash.
                # Normalize empty path to '/' so sub-apps don't 404.
                scope = dict(scope)
                scope["path"] = "/"
        return await app(scope, receive, send)

    return _app

mcp_asgi_app = _normalize_root_path(get_mcp_asgi_app())

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
lifespan = getattr(mcp_asgi_app, "lifespan", None)
kwargs = {"routes": [
    Mount("/sse", app=mcp_asgi_app),
    Mount("/", app=flask_asgi),
]}
if lifespan is not None:
    kwargs["lifespan"] = lifespan
app = Starlette(**kwargs)

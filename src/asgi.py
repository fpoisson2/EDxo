"""ASGI hub: mounts MCP under /sse and Flask under /."""

import os

from asgiref.wsgi import WsgiToAsgi
from starlette.applications import Starlette
from starlette.routing import Mount

from src.app.__init__ import create_app
from src.mcp_server.server import get_mcp_asgi_app, TOOL_NAMES
from src.utils.logging_config import get_logger


# Ensure Flask side does not try to mount SSE endpoints; ASGI handles /sse
os.environ.setdefault("EDXO_MCP_SSE_DISABLE", "1")

# Create the Flask WSGI app and wrap it for ASGI
flask_app = create_app(testing=False)
flask_asgi = WsgiToAsgi(flask_app)

# Obtain the MCP ASGI app (robust to missing integrations)
mcp_asgi_app = get_mcp_asgi_app()

# Log a clear mount message for operational visibility
logger = get_logger(__name__)
try:
    logger.info("MCP ASGI endpoint mounted at /sse/", extra={"tools": TOOL_NAMES})
except Exception:
    pass

# Compose the ASGI hub
app = Starlette(
    routes=[
        # MCP (SSE) first so it takes precedence over Flask for /sse/*
        Mount("/sse", app=mcp_asgi_app),
        # Flask for everything else
        Mount("/", app=flask_asgi),
    ]
)

"""ASGI hub: mounts MCP under /sse and Flask under /."""

from asgiref.wsgi import WsgiToAsgi
from starlette.applications import Starlette
from starlette.routing import Mount

from src.app.__init__ import create_app
from src.mcp_server.server import get_mcp_asgi_app


# Create the Flask WSGI app and wrap it for ASGI
flask_app = create_app(testing=False)
flask_asgi = WsgiToAsgi(flask_app)

# Obtain the MCP ASGI app (robust to missing integrations)
mcp_asgi_app = get_mcp_asgi_app()

# Compose the ASGI hub
app = Starlette(
    routes=[
        # MCP (SSE) first so it takes precedence over Flask for /sse/*
        Mount("/sse", app=mcp_asgi_app),
        # Flask for everything else
        Mount("/", app=flask_asgi),
    ]
)


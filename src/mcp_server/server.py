"""MCP server exposing programme and course resources with OAuth protection.

Mounts an SSE endpoint under ``/sse/`` for ChatGPT/Deep Research.
If ``fastmcp`` isn't available (e.g., during tests), this module degrades
gracefully: resources/tools are not registered, but imports still succeed.
"""

from functools import wraps
import logging
import os
from typing import Optional, Any

try:  # FastMCP may not be available in some environments (tests)
    from fastmcp import FastMCP
    from fastmcp.server.auth import AccessToken, TokenVerifier
    _FASTMCP_AVAILABLE = True
except Exception:  # pragma: no cover - best effort fallback
    FastMCP = None  # type: ignore
    AccessToken = None  # type: ignore

    class TokenVerifier:  # minimal placeholder
        async def verify_token(self, token: str):
            return None

    _FASTMCP_AVAILABLE = False

    class _DummyMCP:  # minimal stub for tests without fastmcp installed
        def __init__(self, auth=None):
            self.auth = auth

        def resource(self, *_args, **_kwargs):
            def decorator(func):
                return func
            return decorator

        def tool(self, func):  # no-op
            return func

        def mount_flask(self, *_args, **_kwargs):  # no-op
            return None

from src.app.models import (
    Programme,
    Cours,
    Competence,
    PlanCadre,
    PlanDeCours,
    OAuthToken,
)
from src.app.routes.oauth import TOKEN_RESOURCES

# ---------------------------------------------------------------------------
# Flask application binding
# ---------------------------------------------------------------------------
flask_app = None
from src.utils.logging_config import get_logger, redact_headers

logger = get_logger(__name__)

server_instructions = (
    "This MCP server provides search and document retrieval capabilities for ChatGPT. "
    "Use the search tool to find relevant items, then fetch to retrieve full content."
)


def init_app(app):
    """Bind Flask app, and mount the MCP SSE endpoint under ``/sse/``.

    - Keeps OAuth verification via DBTokenVerifier (Bearer token).
    - If FastMCP is unavailable, logs a warning and skips mounting.
    """
    global flask_app
    flask_app = app
    if not _FASTMCP_AVAILABLE:
        logger.warning("fastmcp is not installed; MCP SSE endpoint not mounted.")
        # Continue to register /sse/debug route for diagnostics below

    # Allow disabling SSE mounting via env flag (ops control)
    if str(os.getenv("EDXO_MCP_SSE_DISABLE", "")).lower() in {"1", "true", "yes", "on"}:
        logger.info("MCP SSE mounting disabled by EDXO_MCP_SSE_DISABLE")
        _register_debug_route(app)
        return

    # Try to expose SSE via a Flask blueprint or helper
    if _FASTMCP_AVAILABLE:
        try:
            import importlib.util as _util
            has_bp = bool(
                _util.find_spec("fastmcp.integrations.flask") or _util.find_spec("fastmcp.flask")
            )

            if has_bp:
                try:
                    # Preferred: explicit blueprint factory (newer fastmcp)
                    from fastmcp.integrations.flask import create_blueprint  # type: ignore
                except Exception:
                    # Alternate path used by some releases
                    from fastmcp.flask import create_blueprint  # type: ignore

                try:
                    bp = create_blueprint(mcp, url_prefix="/sse")  # type: ignore[misc]
                    app.register_blueprint(bp)
                except TypeError:
                    # Older/newer versions without url_prefix in factory
                    bp = create_blueprint(mcp)
                    app.register_blueprint(bp, url_prefix="/sse")
                logger.info("MCP SSE endpoint mounted at /sse/", extra={"tools": TOOL_NAMES})
            elif hasattr(mcp, "mount_flask"):
                mcp.mount_flask(app, url_prefix="/sse")  # type: ignore[attr-defined]
                logger.info("MCP SSE endpoint mounted via mcp.mount_flask at /sse/", extra={"tools": TOOL_NAMES})
            else:
                # No Flask integration available in fastmcp; log informative message and continue quietly
                version: Optional[str] = None
                try:
                    import importlib.metadata as _md
                    version = _md.version("fastmcp")
                except Exception:
                    try:
                        import fastmcp as _fm  # type: ignore
                        version = getattr(_fm, "__version__", None)
                    except Exception:
                        version = None
                logger.info(
                    "MCP SSE not mounted: no Flask integration in fastmcp (version=%s). Set EDXO_MCP_SSE_DISABLE=1 to silence.",
                    version or "unknown",
                )
        except Exception as e:  # pragma: no cover - best effort
            # Missing integration modules are expected in some deployments → info
            msg = str(e)
            level = logger.warning
            if (
                isinstance(e, ModuleNotFoundError)
                or "No module named 'fastmcp.integrations'" in msg
                or "No module named 'fastmcp.flask'" in msg
            ):
                level = logger.info
            version: Optional[str] = None
            try:
                import importlib.metadata as _md
                version = _md.version("fastmcp")
            except Exception:
                version = None
            level(
                "Failed to evaluate MCP Flask integration (fastmcp=%s): %s",
                version or "unknown",
                e,
            )
    _register_debug_route(app)


def _register_debug_route(app):
    """Register a small debug endpoint at /sse/debug regardless of mounting status."""
    try:
        from flask import jsonify

        def _sse_debug():
            return jsonify({
                "fastmcp": _FASTMCP_AVAILABLE,
                "tools": TOOL_NAMES,
            }), 200

        # Mark as public (bypass auth redirect)
        _sse_debug.is_public = True  # type: ignore[attr-defined]
        app.add_url_rule("/sse/debug", "sse_debug", _sse_debug, methods=["GET"])  # type: ignore[arg-type]
    except Exception:
        pass


def get_mcp_asgi_app() -> Any:
    """Return an ASGI app for MCP if available, otherwise a tiny fallback.

    Tries FastMCP ASGI integration via multiple import paths or object methods.
    Falls back to a minimal Starlette app that exposes a debug endpoint.
    """
    # If FastMCP is unavailable entirely, we return a minimal ASGI app
    # that provides a debug route only, to avoid breaking the hub.
    if not _FASTMCP_AVAILABLE:
        return _fallback_asgi()

    # Prefer FastMCP's first-party ASGI factories when available
    try:
        if hasattr(mcp, "http_app"):
            try:
                # Use legacy SSE transport to match /sse/ expectations, but mount at '/sse'
                # by setting path to '/' so the hub's Mount('/sse', ...) yields '/sse/'.
                return mcp.http_app(transport="sse", path="/")  # type: ignore[attr-defined]
            except TypeError:
                # Older signatures without keyword args
                return mcp.http_app("sse", "/")  # type: ignore[misc]
    except Exception:
        pass

    # Try known integration modules with a create function
    try:
        from fastmcp.integrations.asgi import create_app as _create_app  # type: ignore
        try:
            return _create_app(mcp)  # type: ignore[misc]
        except TypeError:
            return _create_app(mcp=mcp)  # type: ignore[misc]
    except Exception:
        pass

    try:
        from fastmcp.asgi import create_app as _create_app2  # type: ignore
        try:
            return _create_app2(mcp)  # type: ignore[misc]
        except TypeError:
            return _create_app2(mcp=mcp)  # type: ignore[misc]
    except Exception:
        pass

    # Try instance-provided attributes
    for attr in ("asgi_app", "asgi", "app", "router"):
        try:
            candidate = getattr(mcp, attr, None)
            if candidate is None:
                continue
            if callable(candidate):
                app = candidate()
            else:
                app = candidate
            # rudimentary check that it looks like an ASGI callable
            if callable(app):
                return app
        except Exception:
            continue

    # Last resort: provide a tiny Starlette app with a debug route
    return _fallback_asgi()


def _fallback_asgi() -> Any:
    """Minimal ASGI app for environments without FastMCP ASGI integration."""
    try:
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse, PlainTextResponse
        from starlette.routing import Route

        async def not_enabled(_request):
            return PlainTextResponse("MCP SSE is not enabled on this server", status_code=501)

        async def debug(_request):
            return JSONResponse({
                "fastmcp": _FASTMCP_AVAILABLE,
                "tools": TOOL_NAMES,
                "asgi_fallback": True,
            })

        app = Starlette(routes=[
            Route("/", not_enabled),
            Route("/debug", debug),
        ])
        # Mark this as fallback so the hub can log accordingly
        setattr(app, "edxo_mcp_fallback", True)
        return app
    except Exception:
        # If Starlette is missing, return a no-op ASGI app
        async def app(scope, receive, send):  # type: ignore[no-redef]
            if scope["type"] != "http":
                return
            await send({
                "type": "http.response.start",
                "status": 501,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({
                "type": "http.response.body",
                "body": b"MCP SSE is not enabled",
            })
        return app


def with_app_context(func):
    """Ensure the wrapped function runs within the Flask application context."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        from flask import current_app

        app = flask_app or current_app._get_current_object()
        with app.app_context():
            return func(*args, **kwargs)

    return wrapper


class DBTokenVerifier(TokenVerifier):
    """Validate bearer tokens against the application's OAuthToken table."""

    async def verify_token(self, token: str):  # pragma: no cover - async
        from flask import current_app, has_request_context, request

        app = flask_app or current_app._get_current_object()
        with app.app_context():
            # Optional audience binding check based on resource parameter
            presented_resource = None
            if has_request_context():
                base = request.url_root.rstrip('/')
                presented_resource = f"{base}/sse"
                try:
                    logger.info(
                        "MCP: token verification started",
                        extra={
                            "path": request.path,
                            "presented_resource": presented_resource,
                            "headers": redact_headers(request.headers),
                        },
                    )
                except Exception:
                    pass
            oauth = OAuthToken.query.filter_by(token=token).first()
            if oauth and oauth.is_valid():
                stored_resource = TOKEN_RESOURCES.get(token)
                # Normalize trailing slashes for audience comparison
                norm_stored = stored_resource.rstrip('/') if stored_resource else None
                norm_presented = presented_resource.rstrip('/') if presented_resource else None
                if norm_stored and norm_presented and norm_stored != norm_presented:
                    logger.info(
                        "MCP: audience mismatch",
                        extra={
                            "client_id": oauth.client_id,
                            "stored_resource": stored_resource,
                            "presented_resource": presented_resource,
                        },
                    )
                    return None
                if AccessToken is None:  # fastmcp not available (tests)
                    logger.info(
                        "MCP: token accepted (fallback)",
                        extra={
                            "client_id": oauth.client_id,
                            "exp": int(oauth.expires_at.timestamp()),
                        },
                    )
                    return {
                        "token": token,
                        "client_id": oauth.client_id,
                        "scopes": [],
                        "expires_at": int(oauth.expires_at.timestamp()),
                    }
                logger.info(
                    "MCP: token accepted",
                    extra={
                        "client_id": oauth.client_id,
                        "exp": int(oauth.expires_at.timestamp()),
                    },
                )
                return AccessToken(
                    token=token,
                    client_id=oauth.client_id,
                    scopes=[],
                    expires_at=int(oauth.expires_at.timestamp()),
                )
            logger.info("MCP: token rejected or expired")
            return None


TOOL_NAMES = []  # simple registry for debug visibility
mcp = FastMCP(name="EDxoMCP", auth=DBTokenVerifier(), instructions=server_instructions) if _FASTMCP_AVAILABLE else _DummyMCP(auth=DBTokenVerifier())


@with_app_context
def programmes():
    """Retourne la liste des programmes."""
    return [{"id": p.id, "nom": p.nom} for p in Programme.query.all()]


@with_app_context
def programme_courses(programme_id: int):
    """Cours associés à un programme."""
    programme = Programme.query.get(programme_id)
    if not programme:
        raise ValueError("Programme introuvable")
    return [{"id": c.id, "code": c.code, "nom": c.nom} for c in programme.cours]


@with_app_context
def programme_competences(programme_id: int):
    """Compétences ministérielles d'un programme."""
    comps = Competence.query.filter_by(programme_id=programme_id).order_by(Competence.code).all()
    return [{"id": c.id, "code": c.code, "nom": c.nom} for c in comps]


@with_app_context
def competence_details(competence_id: int):
    """Détails d'une compétence."""
    comp = Competence.query.get(competence_id)
    if not comp:
        raise ValueError("Compétence introuvable")
    elements = [
        {"id": e.id, "nom": e.nom, "criteres": [c.criteria for c in e.criteria]}
        for e in comp.elements
    ]
    return {
        "id": comp.id,
        "programme_id": comp.programme_id,
        "code": comp.code,
        "nom": comp.nom,
        "criteria_de_performance": comp.criteria_de_performance,
        "contexte_de_realisation": comp.contexte_de_realisation,
        "elements": elements,
    }


@with_app_context
def cours():
    """Liste de tous les cours."""
    return [{"id": c.id, "code": c.code, "nom": c.nom} for c in Cours.query.all()]


@with_app_context
def cours_details(cours_id: int):
    """Informations sur un cours."""
    cours_obj = Cours.query.get(cours_id)
    if not cours_obj:
        raise ValueError("Cours introuvable")
    return {"id": cours_obj.id, "code": cours_obj.code, "nom": cours_obj.nom}


@with_app_context
def cours_plan_cadre(cours_id: int):
    """Plan cadre lié à un cours."""
    plan = PlanCadre.query.filter_by(cours_id=cours_id).first()
    return plan.to_dict() if plan else {}


@with_app_context
def cours_plans_de_cours(cours_id: int):
    """Plans de cours associés à un cours."""
    plans = PlanDeCours.query.filter_by(cours_id=cours_id).all()
    return [p.to_dict() for p in plans]


@with_app_context
def plan_cadre_section(plan_id: int, section: str):
    """Récupère une section spécifique d'un plan cadre."""
    plan = PlanCadre.query.get(plan_id)
    if not plan or not hasattr(plan, section):
        raise ValueError("Section inconnue")
    return {section: getattr(plan, section)}


# Enregistrement des ressources auprès du serveur MCP (si dispo)
if mcp:
    mcp.resource("api://programmes")(programmes)
    mcp.resource("api://programmes/{programme_id}/cours")(programme_courses)
    mcp.resource("api://programmes/{programme_id}/competences")(programme_competences)
    mcp.resource("api://competences/{competence_id}")(competence_details)
    mcp.resource("api://cours")(cours)
    mcp.resource("api://cours/{cours_id}")(cours_details)
    mcp.resource("api://cours/{cours_id}/plan_cadre")(cours_plan_cadre)
    mcp.resource("api://cours/{cours_id}/plans_de_cours")(cours_plans_de_cours)
    mcp.resource("api://plan_cadre/{plan_id}/section/{section}")(plan_cadre_section)

@with_app_context
def search(query: str):
    """Search programmes and courses and return a list of result ids.

    Returns a list of objects: [{"id": "programme:1"}, {"id": "cours:2"}, ...]
    This matches tests and legacy callers; ChatGPT MCP can map these to ids.
    """
    q = (query or "").strip()
    ids: list[str] = []

    # Programmes: par nom
    prog_q = Programme.query
    if q and q != "*":
        prog_q = prog_q.filter(Programme.nom.ilike(f"%{q}%"))
    else:
        prog_q = prog_q.limit(50)
    for p in prog_q.all():
        ids.append(f"programme:{p.id}")

    # Cours: par nom OU code
    cours_q = Cours.query
    if q and q != "*":
        cours_q = cours_q.filter(
            (Cours.nom.ilike(f"%{q}%")) | (Cours.code.ilike(f"%{q}%"))
        )
    else:
        cours_q = cours_q.limit(100)
    for c in cours_q.all():
        ids.append(f"cours:{c.id}")

    return [{"id": _id} for _id in ids]


@with_app_context
def fetch(id: str):
    """Récupère le contenu complet d'un résultat de recherche."""
    try:
        kind, _id = id.split(":", 1)
        _id = int(_id)
    except ValueError:
        raise ValueError("identifiant invalide")
    if kind == "programme":
        p = Programme.query.get(_id)
        if not p:
            raise ValueError("programme introuvable")
        return {
            "id": id,
            "title": p.nom,
            "text": p.nom,
            "url": f"/api/programmes/{p.id}",
        }
    if kind == "cours":
        c = Cours.query.get(_id)
        if not c:
            raise ValueError("cours introuvable")
        return {
            "id": id,
            "title": c.nom,
            "text": f"{c.code} — {c.nom}",
            "url": f"/api/cours/{c.id}",
            "metadata": {"code": c.code, "nom": c.nom}
        }
    raise ValueError("type inconnu")


# Enregistrement des outils (si dispo)
if mcp:
    # Expose only the two tools required by ChatGPT MCP spec
    mcp.tool(search); TOOL_NAMES.append("search")
    mcp.tool(fetch); TOOL_NAMES.append("fetch")
    try:
        logger.info("MCP: tools registered", extra={"tools": TOOL_NAMES})
    except Exception:
        pass
    # Add small health/debug endpoints on the MCP ASGI app if supported
    try:
        if hasattr(mcp, "custom_route"):
            from starlette.responses import JSONResponse

            @mcp.custom_route("/health", methods=["GET"])  # type: ignore[attr-defined]
            async def _health(_request):
                return JSONResponse({"status": "healthy", "tools": TOOL_NAMES})

            @mcp.custom_route("/debug", methods=["GET"])  # type: ignore[attr-defined]
            async def _debug(_request):
                return JSONResponse({
                    "fastmcp": _FASTMCP_AVAILABLE,
                    "tools": TOOL_NAMES,
                    "server": "asgi",
                })
    except Exception:
        pass

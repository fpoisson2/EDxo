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
    User,
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
            # 1) OAuth token path (Authorization: Bearer <oauth_token>)
            oauth = OAuthToken.query.filter_by(token=token).first()
            if oauth and oauth.is_valid():
                stored_resource = TOKEN_RESOURCES.get(token)
                # Normalize trailing slashes for audience comparison
                norm_stored = stored_resource.rstrip('/') if stored_resource else None
                norm_presented = presented_resource.rstrip('/') if presented_resource else None
                # Allow bypass if audience is absent or feature-flagged to ignore
                ignore_aud = str(os.getenv("EDXO_MCP_IGNORE_AUDIENCE", "")).lower() in {"1", "true", "yes", "on"}
                mismatch = (
                    bool(norm_stored) and bool(norm_presented) and norm_stored != norm_presented
                )
                if mismatch and not ignore_aud:
                    logger.warning(
                        "MCP: OAuth token rejected (aud mismatch)",
                        extra={
                            "client_id": oauth.client_id,
                            "stored": stored_resource,
                            "presented": presented_resource,
                        },
                    )
                    return None
                if mismatch and ignore_aud:
                    logger.info(
                        "MCP: audience mismatch ignored by flag",
                        extra={
                            "client_id": oauth.client_id,
                            "stored": stored_resource,
                            "presented": presented_resource,
                        },
                    )
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
            # 2) User API token path (Authorization: Bearer <user_api_token>)
            user = User.query.filter_by(api_token=token).first()
            if user and user.api_token_expires_at and user.api_token_expires_at > __import__("datetime").datetime.utcnow():
                # For user tokens, we do not enforce audience binding; these are first-party keys
                client_id = f"user:{user.id}"
                exp_ts = int(user.api_token_expires_at.timestamp()) if user.api_token_expires_at else None
                if AccessToken is None:  # fastmcp not available (tests)
                    logger.info(
                        "MCP: user API token accepted (fallback)",
                        extra={
                            "client_id": client_id,
                            "exp": exp_ts,
                        },
                    )
                    return {
                        "token": token,
                        "client_id": client_id,
                        "scopes": [],
                        "expires_at": exp_ts,
                    }
                logger.info(
                    "MCP: user API token accepted",
                    extra={
                        "client_id": client_id,
                        "exp": exp_ts,
                    },
                )
                return AccessToken(
                    token=token,
                    client_id=client_id,
                    scopes=[],
                    expires_at=exp_ts,
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
    try:
        logger.info("MCP: search start", extra={"query": q})
    except Exception:
        pass

    # Programmes: par nom
    prog_q = Programme.query
    if q and q != "*":
        prog_q = prog_q.filter(Programme.nom.ilike(f"%{q}%"))
    else:
        prog_q = prog_q.limit(50)
    _prog = prog_q.all()
    for p in _prog:
        ids.append(f"programme:{p.id}")

    # Cours: par nom OU code
    cours_q = Cours.query
    if q and q != "*":
        cours_q = cours_q.filter(
            (Cours.nom.ilike(f"%{q}%")) | (Cours.code.ilike(f"%{q}%"))
        )
    else:
        cours_q = cours_q.limit(100)
    # If the query looks like a course code embedded in natural text (e.g. "détails du cours 243-2J5"),
    # try to extract a code-like token and include it in matching.
    import re as _re
    code_token = None
    if q and q != "*":
        m = _re.search(r"\b\d{3}-[0-9A-Za-z]{2,}\b", q, _re.IGNORECASE)
        if m:
            code_token = m.group(0)
            try:
                from sqlalchemy import or_ as _or
                cours_q = Cours.query.filter(
                    _or(
                        (Cours.nom.ilike(f"%{q}%")) | (Cours.code.ilike(f"%{q}%")),
                        Cours.code.ilike(f"%{code_token}%"),
                    )
                )
            except Exception:
                pass
    _cours = cours_q.all()
    for c in _cours:
        ids.append(f"cours:{c.id}")

    # Plan-cadres: associer au cours et champs principaux
    pc_q = PlanCadre.query.join(Cours, PlanCadre.cours_id == Cours.id)
    if q and q != "*":
        pc_filters = [Cours.nom.ilike(f"%{q}%"), Cours.code.ilike(f"%{q}%")]
        # Recherche sommaire dans quelques champs textuels du plan-cadre
        for col in (
            PlanCadre.objectif_terminal,
            PlanCadre.structure_intro,
            PlanCadre.structure_activites_prevues,
            PlanCadre.eval_nature_evaluations_sommatives,
        ):
            pc_filters.append(col.ilike(f"%{q}%"))
        from sqlalchemy import or_ as _or
        pc_q = pc_q.filter(_or(*pc_filters))
    else:
        pc_q = pc_q.limit(100)
    _pc = pc_q.all()
    for pc in _pc:
        ids.append(f"plan_cadre:{pc.id}")

    # Plans de cours: associer au cours et quelques champs clés
    pdc_q = PlanDeCours.query.join(Cours, PlanDeCours.cours_id == Cours.id)
    if q and q != "*":
        from sqlalchemy import or_ as _or
        pdc_q = pdc_q.filter(
            _or(
                Cours.nom.ilike(f"%{q}%"),
                Cours.code.ilike(f"%{q}%"),
                PlanDeCours.session.ilike(f"%{q}%"),
                PlanDeCours.nom_enseignant.ilike(f"%{q}%"),
            )
        )
    else:
        pdc_q = pdc_q.limit(100)
    _pdc = pdc_q.all()
    for pdc in _pdc:
        ids.append(f"plan_de_cours:{pdc.id}")

    # Compétences: par code, nom, ou nom du programme
    comp_q = Competence.query
    if q and q != "*":
        from sqlalchemy import or_ as _or
        # Jointure facultative vers Programme via 'programme_id' simple
        comp_q = comp_q.filter(
            _or(
                Competence.code.ilike(f"%{q}%"),
                Competence.nom.ilike(f"%{q}%"),
            )
        )
    else:
        comp_q = comp_q.limit(100)
    _comp = comp_q.all()
    for comp in _comp:
        ids.append(f"competence:{comp.id}")

    try:
        logger.info(
            "MCP: search summary",
            extra={
                "query": q,
                "programme": len(_prog),
                "cours": len(_cours),
                "plan_cadre": len(_pc),
                "plan_de_cours": len(_pdc),
                "competence": len(_comp),
                "total": len(ids),
                "code_token": code_token,
                "ids_preview": ids[:5],
            },
        )
    except Exception:
        pass
    return [{"id": _id} for _id in ids]


@with_app_context
def fetch(id: str):
    """Récupère le contenu complet d'un résultat de recherche."""
    try:
        kind, _id = id.split(":", 1)
        _id = int(_id)
    except ValueError:
        logger.warning("MCP: fetch bad id format", extra={"id": id})
        raise ValueError("identifiant invalide")
    try:
        logger.info("MCP: fetch start", extra={"id": id, "kind": kind})
    except Exception:
        pass
    if kind == "programme":
        p = Programme.query.get(_id)
        if not p:
            logger.info("MCP: programme introuvable", extra={"id": id})
            raise ValueError("programme introuvable")
        # Inclure un bref aperçu des cours et compétences dans les métadonnées
        meta = {
            "cours": [{"id": c.id, "code": c.code, "nom": c.nom} for c in p.cours],
        }
        try:
            comps = Competence.query.filter_by(programme_id=p.id).order_by(Competence.code).all()
            meta["competences"] = [{"id": c.id, "code": c.code, "nom": c.nom} for c in comps]
        except Exception:
            pass
        return {
            "id": id,
            "title": p.nom,
            "text": p.nom,
            "url": f"/api/programmes/{p.id}",
            "metadata": meta,
        }
    if kind == "cours":
        c = Cours.query.get(_id)
        if not c:
            logger.info("MCP: cours introuvable", extra={"id": id})
            raise ValueError("cours introuvable")
        # Ajouter liens vers plan-cadre et plans de cours dans metadata
        meta = {}
        try:
            if getattr(c, "plan_cadre", None):
                meta["plan_cadre_id"] = c.plan_cadre.id
            if getattr(c, "plans_de_cours", None):
                meta["plans_de_cours_ids"] = [p.id for p in c.plans_de_cours]
        except Exception:
            pass
        return {
            "id": id,
            "title": c.nom,
            "text": f"{c.code} — {c.nom}",
            "url": f"/api/cours/{c.id}",
            "metadata": {"code": c.code, "nom": c.nom, **meta}
        }
    if kind == "plan_cadre":
        pc = PlanCadre.query.get(_id)
        if not pc:
            logger.info("MCP: plan_cadre introuvable", extra={"id": id})
            raise ValueError("plan_cadre introuvable")
        cours_info = f"{pc.cours.code} — {pc.cours.nom}" if getattr(pc, "cours", None) else ""
        # Texte concis: objectif + quelques sections si présentes
        summary_parts = []
        for attr in ("objectif_terminal", "structure_intro", "structure_activites_prevues"):
            val = getattr(pc, attr, None)
            if val:
                summary_parts.append(f"{attr}: {val}")
        text = "\n\n".join(summary_parts) or f"Plan-cadre du cours {cours_info}".strip()
        return {
            "id": id,
            "title": f"Plan-cadre — {cours_info}".strip(" — "),
            "text": text,
            "url": f"/api/cours/{pc.cours_id}/plan_cadre",
            "metadata": pc.to_dict() if hasattr(pc, "to_dict") else {"id": pc.id, "cours_id": pc.cours_id},
        }
    if kind == "plan_de_cours":
        pdc = PlanDeCours.query.get(_id)
        if not pdc:
            logger.info("MCP: plan_de_cours introuvable", extra={"id": id})
            raise ValueError("plan_de_cours introuvable")
        cours_info = f"{pdc.cours.code} — {pdc.cours.nom}" if getattr(pdc, "cours", None) else ""
        summary_parts = []
        for attr in ("presentation_du_cours", "objectif_terminal_du_cours", "organisation_et_methodes"):
            val = getattr(pdc, attr, None)
            if val:
                summary_parts.append(f"{attr}: {val}")
        text = "\n\n".join(summary_parts) or f"Plan de cours {pdc.session} — {cours_info}".strip()
        return {
            "id": id,
            "title": f"Plan de cours {pdc.session} — {cours_info}".strip(" — "),
            "text": text,
            "url": f"/api/cours/{pdc.cours_id}/plans_de_cours",
            "metadata": pdc.to_dict() if hasattr(pdc, "to_dict") else {"id": pdc.id, "cours_id": pdc.cours_id},
        }
    if kind == "competence":
        comp = Competence.query.get(_id)
        if not comp:
            logger.info("MCP: competence introuvable", extra={"id": id})
            raise ValueError("compétence introuvable")
        # Réutilise la logique de l'endpoint competence_details pour la métadonnée
        details = competence_details(comp.id)
        title = f"Compétence {comp.code} — {comp.nom}"
        text = "\n".join(
            part for part in [
                f"Critères: {comp.criteria_de_performance}" if comp.criteria_de_performance else None,
                f"Contexte: {comp.contexte_de_realisation}" if comp.contexte_de_realisation else None,
            ]
            if part
        ) or title
        return {
            "id": id,
            "title": title,
            "text": text,
            "url": f"/api/programmes/{comp.programme_id}/competences",
            "metadata": details,
        }
    raise ValueError("type inconnu")


# Enregistrement des outils (si dispo)
if mcp:
    # Deep Research requires exactly two tools: search(query) and fetch(id)
    # Keep internal sync functions for app/tests, and expose async wrappers for MCP.
    try:
        async def _search_tool(query: str):
            """Search programmes and courses and return matching record IDs.

            - Input: a free-form `query` string (keywords, codes, names).
            - Behavior: matches across programme names, course names and codes.
            - Output: a dict with `ids`, e.g. {"ids": ["programme:1", "cours:2", ...]}.
            - Next step: ChatGPT should call `fetch(id)` for selected IDs to retrieve full content.
            """
            try:
                logger.info("MCP tool: search called", extra={"query": (query or "").strip()})
            except Exception:
                pass
            results = search(query)
            ids = [r["id"] for r in results]
            try:
                logger.info("MCP tool: search results", extra={"count": len(ids)})
            except Exception:
                pass
            return {"ids": ids}

        _search_tool.__name__ = "search"
        try:
            mcp.tool(_search_tool, name="search")
        except TypeError:
            # Fallback for older FastMCP signatures
            mcp.tool(_search_tool)
        TOOL_NAMES.append("search")

        async def _fetch_tool(id: str):
            """Fetch a record by ID and return its complete content.

            - Input: an `id` previously returned by `search`, like "programme:123" or "cours:456".
            - Behavior: resolves the ID, loads the corresponding record from the database.
            - Output: a dict with fields like {id, title, text, url, metadata} for citation and analysis.
            """
            try:
                logger.info("MCP tool: fetch called", extra={"id": id})
            except Exception:
                pass
            result = fetch(id)
            try:
                logger.info("MCP tool: fetch returned", extra={"id": id, "title": result.get("title")})
            except Exception:
                pass
            return result

        _fetch_tool.__name__ = "fetch"
        try:
            mcp.tool(_fetch_tool, name="fetch")
        except TypeError:
            mcp.tool(_fetch_tool)
        TOOL_NAMES.append("fetch")

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
    except Exception as _e:  # pragma: no cover - defensive
        try:
            logger.warning("MCP: failed to register tools: %s", _e)
        except Exception:
            pass

"""MCP server exposing programme and course resources with OAuth protection.

Mounts an SSE endpoint under ``/sse/`` for ChatGPT/Deep Research.
If ``fastmcp`` isn't available (e.g., during tests), this module degrades
gracefully: resources/tools are not registered, but imports still succeed.
"""

from functools import wraps
import logging

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
logger = logging.getLogger(__name__)


def init_app(app):
    """Bind Flask app, and mount the MCP SSE endpoint under ``/sse/``.

    - Keeps OAuth verification via DBTokenVerifier (Bearer token).
    - If FastMCP is unavailable, logs a warning and skips mounting.
    """
    global flask_app
    flask_app = app
    if not _FASTMCP_AVAILABLE:
        logger.warning("fastmcp is not installed; MCP SSE endpoint not mounted.")
        return

    # Try to expose SSE via a Flask blueprint or helper
    try:
        try:
            # Preferred: explicit blueprint factory
            from fastmcp.integrations.flask import create_blueprint  # type: ignore
            try:
                bp = create_blueprint(mcp, url_prefix="/sse")  # some versions accept this
                app.register_blueprint(bp)
            except TypeError:
                # Older/newer versions without url_prefix in factory
                bp = create_blueprint(mcp)
                app.register_blueprint(bp, url_prefix="/sse")
            logger.info("MCP SSE endpoint mounted at /sse/")
            return
        except Exception:
            # Fallback: direct mount helper on the MCP instance
            if hasattr(mcp, "mount_flask"):
                mcp.mount_flask(app, url_prefix="/sse")  # type: ignore[attr-defined]
                logger.info("MCP SSE endpoint mounted via mcp.mount_flask at /sse/")
                return
            raise
    except Exception as e:  # pragma: no cover - best effort
        logger.warning("Failed to mount MCP SSE endpoint: %s", e)


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
            oauth = OAuthToken.query.filter_by(token=token).first()
            if oauth and oauth.is_valid():
                stored_resource = TOKEN_RESOURCES.get(token)
                if stored_resource and presented_resource and stored_resource != presented_resource:
                    return None
                if AccessToken is None:  # fastmcp not available (tests)
                    return {
                        "token": token,
                        "client_id": oauth.client_id,
                        "scopes": [],
                        "expires_at": int(oauth.expires_at.timestamp()),
                    }
                return AccessToken(
                    token=token,
                    client_id=oauth.client_id,
                    scopes=[],
                    expires_at=int(oauth.expires_at.timestamp()),
                )
            return None


mcp = FastMCP(name="EDxoMCP", auth=DBTokenVerifier()) if _FASTMCP_AVAILABLE else _DummyMCP(auth=DBTokenVerifier())


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
    """Recherche des programmes et cours par nom."""
    # Normaliser la requête et offrir quelques comportements utiles:
    # - Supporter recherche par code de cours (ex: "243-2J5")
    # - Si la requête est vide ou '*', retourner un échantillon utile
    q = (query or "").strip()
    results = []

    # Programmes: recherche sur le nom
    prog_q = Programme.query
    if q and q != "*":
        prog_q = prog_q.filter(Programme.nom.ilike(f"%{q}%"))
    else:
        prog_q = prog_q.limit(50)
    for p in prog_q.all():
        results.append({
            "id": f"programme:{p.id}",
            "title": p.nom,
            "text": p.nom,
            "url": f"/api/programmes/{p.id}",
        })

    # Cours: recherche sur le nom OU le code
    cours_q = Cours.query
    if q and q != "*":
        cours_q = cours_q.filter((Cours.nom.ilike(f"%{q}%")) | (Cours.code.ilike(f"%{q}%")))
    else:
        cours_q = cours_q.limit(100)
    for c in cours_q.all():
        results.append({
            "id": f"cours:{c.id}",
            "title": c.nom,
            "text": f"{c.code} — {c.nom}",
            "url": f"/api/cours/{c.id}",
        })
    return results


@with_app_context
def fetch(item_id: str):
    """Récupère le contenu complet d'un résultat de recherche."""
    try:
        kind, _id = item_id.split(":", 1)
        _id = int(_id)
    except ValueError:
        raise ValueError("identifiant invalide")
    if kind == "programme":
        p = Programme.query.get(_id)
        if not p:
            raise ValueError("programme introuvable")
        return {
            "id": item_id,
            "title": p.nom,
            "text": p.nom,
            "url": f"/api/programmes/{p.id}",
        }
    if kind == "cours":
        c = Cours.query.get(_id)
        if not c:
            raise ValueError("cours introuvable")
        return {
            "id": item_id,
            "title": c.nom,
            "text": f"{c.code} — {c.nom}",
            "url": f"/api/cours/{c.id}",
            "metadata": {"code": c.code, "nom": c.nom}
        }
    raise ValueError("type inconnu")


# Enregistrement des outils (si dispo)
if mcp:
    mcp.tool(search)
    mcp.tool(fetch)

    # Fournir aussi des outils explicites pour le listing et les détails,
    # car certains clients MCP n'explorent pas les resources.
    mcp.tool(programmes)  # -> liste des programmes
    mcp.tool(cours)  # -> liste de tous les cours
    mcp.tool(programme_courses)  # -> cours d'un programme donné
    mcp.tool(competence_details)
    mcp.tool(cours_details)
    mcp.tool(cours_plan_cadre)
    mcp.tool(cours_plans_de_cours)
    mcp.tool(plan_cadre_section)

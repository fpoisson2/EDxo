"""MCP server exposing two Deep Research tools with Bearer auth.

- Exactly two tools are registered: ``search(query: str)`` and ``fetch(id: str)``.
- Bearer Authorization accepts either OAuth tokens or user API tokens.
- SSE/ASGI mounting kept minimal; degrades gracefully without fastmcp.
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
    ListeProgrammeMinisteriel,
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
    """Bind Flask app, and mount the MCP SSE endpoint under ``/sse/`` if possible."""
    global flask_app
    flask_app = app
    if str(os.getenv("EDXO_MCP_SSE_DISABLE", "")).lower() in {"1", "true", "yes", "on"}:
        logger.info("MCP SSE mounting disabled by EDXO_MCP_SSE_DISABLE")
        return
    if not _FASTMCP_AVAILABLE:
        logger.warning("fastmcp is not installed; MCP SSE endpoint not mounted.")
        return
    # Minimal mounting via FastMCP's Flask integration if available
    try:
        try:
            from fastmcp.integrations.flask import create_blueprint  # type: ignore
        except Exception:
            from fastmcp.flask import create_blueprint  # type: ignore
        try:
            bp = create_blueprint(mcp, url_prefix="/sse")  # type: ignore[misc]
            app.register_blueprint(bp)
        except TypeError:
            bp = create_blueprint(mcp)
            app.register_blueprint(bp, url_prefix="/sse")
        logger.info("MCP SSE endpoint mounted at /sse/", extra={"tools": TOOL_NAMES})
        return
    except Exception:
        pass
    # Fallback to instance method if provided
    try:
        if hasattr(mcp, "mount_flask"):
            mcp.mount_flask(app, url_prefix="/sse")  # type: ignore[attr-defined]
            logger.info("MCP SSE endpoint mounted via mcp.mount_flask at /sse/", extra={"tools": TOOL_NAMES})
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

        app = Starlette(routes=[Route("/", not_enabled), Route("/debug", debug)])
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


# Intentionally not registering resources on MCP; Deep Research only needs tools.

@with_app_context
def search(query: str):
    """Recherche multi-ressources et renvoie des identifiants.

    - Entrée: chaîne libre (mots-clés, codes, noms, session, etc.).
    - Couvre: Programmes, Cours, Compétences, Plans Cadre, Plans de Cours.
    - Sortie: liste d'objets {"id": "<type>:<id>"}.
    - Les clients MCP utilisent ensuite fetch(id) pour le contenu complet.
    """
    from sqlalchemy import or_, func
    import re

    q = (query or "").strip()
    ids: list[str] = []

    # Prétraitement du code éventuel (ex: "243-2J5", "243 2J5", "cours-243-2J5-LI")
    # On extrait des segments alphanumériques et on détecte les motifs cours.
    toks = [t for t in re.split(r"[^0-9A-Za-z]+", q.lower()) if t]
    # Exemple: ["cours", "243", "2j5", "li"]
    norm_candidates = set()
    if toks:
        # Combine premiers segments type "243" + "2j5" → "2432j5"
        for i, t in enumerate(toks):
            if i + 1 < len(toks) and toks[i].isdigit():
                norm_candidates.add(toks[i] + toks[i + 1])
        # Ajouter chaque token seul également
        norm_candidates.update(toks)

    # Programmes: par nom, par code ministériel ou nom ministériel
    prog_q = Programme.query.outerjoin(
        ListeProgrammeMinisteriel,
        Programme.liste_programme_ministeriel,
    )
    if q and q != "*":
        like = f"%{q}%"
        prog_filters = [Programme.nom.ilike(like)]
        try:
            prog_filters += [
                ListeProgrammeMinisteriel.code.ilike(like),
                ListeProgrammeMinisteriel.nom.ilike(like),
            ]
        except Exception:
            pass
        prog_q = prog_q.filter(or_(*prog_filters))
    else:
        prog_q = prog_q.limit(50)
    ids.extend([f"programme:{p.id}" for p in prog_q.all()])

    # Cours: par nom OU code
    cours_q = Cours.query
    if q and q != "*":
        like = f"%{q}%"
        filters = [Cours.nom.ilike(like), Cours.code.ilike(like)]
        # Tentatives de normalisation: comparer code sans '-' ni espaces
        if norm_candidates:
            for norm in norm_candidates:
                filters.append(
                    func.lower(
                        func.replace(
                            func.replace(Cours.code, "-", ""),
                            " ",
                            "",
                        )
                    ).like(f"%{norm}%")
                )
                # startswith pour capturer 243-2J5-LI lorsqu'on cherche 243-2J5
                filters.append(Cours.code.ilike(f"{norm}%"))
        cours_q = cours_q.filter(or_(*filters))
    else:
        cours_q = cours_q.limit(100)
    ids.extend([f"cours:{c.id}" for c in cours_q.all()])

    # Compétences: par code ou nom
    comp_q = Competence.query
    if q and q != "*":
        comp_q = comp_q.filter(or_(Competence.code.ilike(f"%{q}%"), Competence.nom.ilike(f"%{q}%")))
    else:
        comp_q = comp_q.limit(100)
    ids.extend([f"competence:{c.id}" for c in comp_q.all()])

    # Plans Cadre: recherche dans quelques champs textuels clés
    pc_q = PlanCadre.query
    if q and q != "*":
        like = f"%{q}%"
        pc_q = pc_q.filter(
            or_(
                PlanCadre.objectif_terminal.ilike(like),
                PlanCadre.structure_intro.ilike(like),
                PlanCadre.structure_activites_theoriques.ilike(like),
                PlanCadre.structure_activites_pratiques.ilike(like),
                PlanCadre.structure_activites_prevues.ilike(like),
                PlanCadre.eval_evaluation_sommative.ilike(like),
                PlanCadre.eval_nature_evaluations_sommatives.ilike(like),
                PlanCadre.eval_evaluation_de_la_langue.ilike(like),
                PlanCadre.eval_evaluation_sommatives_apprentissages.ilike(like),
                PlanCadre.place_intro.ilike(like),
            )
        )
    else:
        pc_q = pc_q.limit(50)
    ids.extend([f"plan_cadre:{p.id}" for p in pc_q.all()])

    # Plans de Cours: session, présentation, objectif terminal, organisation
    pdc_q = PlanDeCours.query
    if q and q != "*":
        like = f"%{q}%"
        pdc_q = pdc_q.filter(
            or_(
                PlanDeCours.session.ilike(like),
                PlanDeCours.presentation_du_cours.ilike(like),
                PlanDeCours.objectif_terminal_du_cours.ilike(like),
                PlanDeCours.organisation_et_methodes.ilike(like),
                PlanDeCours.place_et_role_du_cours.ilike(like),
                PlanDeCours.materiel.ilike(like),
                PlanDeCours.campus.ilike(like),
            )
        )
    else:
        pdc_q = pdc_q.limit(50)
    ids.extend([f"plan_de_cours:{p.id}" for p in pdc_q.all()])

    return [{"id": _id} for _id in ids]


@with_app_context
def fetch(id: str):
    """Récupère le contenu complet d'un résultat de recherche.

    Accepte des identifiants de la forme:
    - programme:<id>
    - cours:<id>
    - competence:<id>
    - plan_cadre:<id>
    - plan_de_cours:<id>
    """
    try:
        kind, _id = id.split(":", 1)
        _id = int(_id)
    except ValueError:
        raise ValueError("identifiant invalide")
    if kind == "programme":
        p = Programme.query.get(_id)
        if not p:
            raise ValueError("programme introuvable")
        # Cours rattachés
        cours_list = [{"id": c.id, "code": c.code, "nom": c.nom} for c in p.cours]
        # Compétences associées (si relation via competence_programme existe)
        try:
            comps = [{"id": c.id, "code": c.code, "nom": c.nom} for c in p.competences]  # type: ignore[attr-defined]
        except Exception:
            comps = []
        return {
            "id": id,
            "title": p.nom,
            "text": p.nom,
            "url": f"/api/programmes/{p.id}",
            "metadata": {
                "type": "programme",
                "programme_id": p.id,
                "cours": cours_list,
                "competences": comps,
            },
        }
    if kind == "cours":
        c = Cours.query.get(_id)
        if not c:
            raise ValueError("cours introuvable")
        # Plan cadre et plans de cours
        plan_cadre = PlanCadre.query.filter_by(cours_id=c.id).first()
        plans = PlanDeCours.query.filter_by(cours_id=c.id).all()
        # Programmes associés avec codes ministériels (si dispo)
        try:
            progs = c.programmes.all()  # type: ignore[attr-defined]
        except Exception:
            progs = list(getattr(c, "programmes", []) or [])
        programmes_meta = []
        for p in progs:
            try:
                lpm = getattr(p, "liste_programme_ministeriel", None)
                programmes_meta.append({
                    "id": p.id,
                    "nom": p.nom,
                    "ministeriel": {
                        "code": getattr(lpm, "code", None),
                        "nom": getattr(lpm, "nom", None),
                    } if lpm else None,
                })
            except Exception:
                programmes_meta.append({"id": p.id, "nom": getattr(p, "nom", None)})
        return {
            "id": id,
            "title": c.nom,
            "text": f"{c.code} — {c.nom}",
            "url": f"/api/cours/{c.id}",
            "metadata": {
                "type": "cours",
                "code": c.code,
                "nom": c.nom,
                "plan_cadre_id": plan_cadre.id if plan_cadre else None,
                "plans_de_cours_ids": [p.id for p in plans],
                "heures": {
                    "theorie": c.heures_theorie,
                    "laboratoire": c.heures_laboratoire,
                    "travail_maison": c.heures_travail_maison,
                },
                "unites": c.nombre_unites,
                "programmes": programmes_meta,
                "sessions": getattr(c, "sessions_map", {}),
            },
        }
    if kind == "competence":
        comp = Competence.query.get(_id)
        if not comp:
            raise ValueError("compétence introuvable")
        elements = [
            {"id": e.id, "nom": e.nom, "criteres": [c.criteria for c in e.criteria]}
            for e in comp.elements
        ]
        return {
            "id": id,
            "title": f"{comp.code} — {comp.nom}",
            "text": (comp.criteria_de_performance or "") or comp.nom,
            "url": f"/api/competences/{comp.id}",
            "metadata": {
                "type": "competence",
                "programme_id": comp.programme_id,
                "code": comp.code,
                "nom": comp.nom,
                "contexte_de_realisation": comp.contexte_de_realisation,
                "elements": elements,
            },
        }
    if kind == "plan_cadre":
        pc = PlanCadre.query.get(_id)
        if not pc:
            raise ValueError("plan cadre introuvable")
        data = pc.to_dict()
        return {
            "id": id,
            "title": f"Plan cadre du cours {data.get('cours_info', {}).get('code')}",
            "text": (data.get("objectif_terminal") or data.get("structure_intro") or "Plan cadre"),
            "url": f"/api/cours/{pc.cours_id}/plan_cadre",
            "metadata": {"type": "plan_cadre", **data},
        }
    if kind == "plan_de_cours":
        pdc = PlanDeCours.query.get(_id)
        if not pdc:
            raise ValueError("plan de cours introuvable")
        data = pdc.to_dict()
        return {
            "id": id,
            "title": f"Plan de cours {data.get('session')} — {data.get('cours_info', {}).get('code')}",
            "text": (data.get("presentation_du_cours") or data.get("objectif_terminal_du_cours") or "Plan de cours"),
            "url": f"/api/cours/{pdc.cours_id}",
            "metadata": {"type": "plan_de_cours", **data},
        }
    raise ValueError("type inconnu")


"""MCP tool registration: exactly 'search' and 'fetch'."""
if mcp:
    try:
        @mcp.tool()
        async def search_tool(query: str):
            """Semantic search across the academic database; returns IDs only.

            - Input: free-form query (keywords, course codes, programme names, sessions, etc.).
            - Scope: Programmes, Cours, Compétences, Plan Cadre, Plans de Cours.
            - Output: {"ids": ["programme:<id>", "cours:<id>", "competence:<id>", "plan_cadre:<id>", "plan_de_cours:<id>"]}
            - Follow-up: Call `fetch(id)` on selected IDs for complete records (title/text/metadata/url).
            """
            results = search(query)
            return {"ids": [r["id"] for r in results]}

        # Ensure tool is named 'search' for Deep Research
        try:
            search_tool.__name__ = "search"  # type: ignore[attr-defined]
        except Exception:
            pass
        TOOL_NAMES.append("search")

        @mcp.tool()
        async def fetch_tool(id: str):
            """Fetch a record by ID for full content and citation.

            - Accepts IDs returned by `search` (programme, cours, competence, plan_cadre, plan_de_cours).
            - Returns a dict with keys: {id, title, text, url, metadata}.
            - `metadata` includes rich structured fields to support detailed analysis.
            """
            return fetch(id)

        try:
            fetch_tool.__name__ = "fetch"  # type: ignore[attr-defined]
        except Exception:
            pass
        TOOL_NAMES.append("fetch")

        try:
            logger.info("MCP: tools registered", extra={"tools": TOOL_NAMES})
        except Exception:
            pass
    except Exception as e:  # pragma: no cover
        try:
            logger.warning("MCP tool registration failed: %s", e)
        except Exception:
            pass

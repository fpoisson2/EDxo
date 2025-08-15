from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents import function_tool

from .context import get_current_context


def _require_session():
    ctx = get_current_context()
    sess = ctx.ensure_session()
    if not sess.user_id and (not ctx.username or not ctx.password):
        raise RuntimeError("No logged-in session; set credentials with use_account tool.")
    return sess


@function_tool
def use_account(username: str, password: str) -> str:
    """Authenticate with a DB username/password for protected routes."""
    ctx = get_current_context()
    ctx.username = username
    ctx.password = password
    sess = ctx.ensure_session()
    ok = sess.login_with_password(username, password)
    if not ok:
        return "Login failed: invalid credentials"
    return f"Logged in as {username} (user_id={sess.user_id})"


@function_tool
def complete_profile() -> str:
    """Mark current user profile as completed to bypass welcome redirect."""
    sess = _require_session()
    ok = sess.complete_profile()
    return "Profile completed" if ok else "Profile not updated"


@function_tool
def health() -> Dict[str, Any]:
    """Return application health JSON."""
    sess = _require_session()
    return sess.health()


@function_tool
def version() -> str:
    """Return the application version string."""
    sess = _require_session()
    return sess.version()


@function_tool
def list_programmes() -> List[Dict[str, Any]]:
    """List programmes (id, nom) via API."""
    sess = _require_session()
    r = sess.get("/api/programmes")
    return r.get_json() or []


@function_tool
def list_cours(programme_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """List cours (id, code, nom) via API, optionally filtered by programme_id."""
    sess = _require_session()
    path = "/api/cours"
    if programme_id:
        path += f"?programme_id={int(programme_id)}"
    r = sess.get(path)
    return r.get_json() or []


@function_tool
def find_cours_by_code(code: str) -> Optional[Dict[str, Any]]:
    """Find a course by code via API (case-insensitive, allows partial)."""
    sess = _require_session()
    r = sess.get(f"/api/cours/by_code?code={code}")
    data = r.get_json()
    return data if data else None


@function_tool
def get_cours_title(code: str) -> Optional[str]:
    """Return the course title (nom) via API for a given code."""
    res = find_cours_by_code(code)
    return res.get("nom") if res else None


@function_tool
def get_plan_cadre_id_for_cours(cours_id: int) -> Optional[int]:
    """Return the plan-cadre id for a given cours id via API."""
    sess = _require_session()
    r = sess.get(f"/api/cours/{cours_id}/plan_cadre")
    data = r.get_json() or {}
    return data.get("plan_cadre_id")


@function_tool
def get_plan_cadre_capacites(plan_cadre_id: int) -> List[Dict[str, Any]]:
    """List capacities of a plan-cadre via API."""
    sess = _require_session()
    r = sess.get(f"/api/plan_cadre/{plan_cadre_id}/capacites")
    return r.get_json() or []


@function_tool
def add_plan_cadre_capacite(plan_cadre_id: int, capacite: str, description_capacite: str, ponderation_min: int = 0, ponderation_max: int = 0) -> Dict[str, Any]:
    """Append a new capacity to a plan-cadre via API."""
    sess = _require_session()
    payload = {
        "capacite": capacite.strip(),
        "description_capacite": description_capacite.strip(),
        "ponderation_min": int(ponderation_min or 0),
        "ponderation_max": int(ponderation_max or 0),
    }
    r = sess.post_json(f"/api/plan_cadre/{plan_cadre_id}/capacites", payload)
    return r.get_json() or {"success": False}


@function_tool
def pdc_generate_all(cours_id: int, session: str, additional_info: Optional[str] = None, ai_model: Optional[str] = None) -> Dict[str, Any]:
    """Start Celery task for plan de cours generation via API."""
    sess = _require_session()
    payload = {
        "cours_id": int(cours_id),
        "session": session,
        "additional_info": additional_info,
        "ai_model": ai_model,
    }
    r = sess.post_json("/api/plan_de_cours/generate_all_start", payload)
    return r.get_json() or {"success": False}


@function_tool
def task_status(task_id: str) -> Dict[str, Any]:
    """Get task status from /task_status/<id>."""
    sess = _require_session()
    r = sess.get(f"/task_status/{task_id}")
    return r.get_json() or {"error": f"HTTP {r.status_code}"}


@function_tool
def pc_generate(plan_id: int, mode: str = "wand", target_columns: Optional[List[str]] = None, wand_instruction: Optional[str] = None) -> Dict[str, Any]:
    """Trigger plan-cadre content generation via API; returns a task id."""
    sess = _require_session()
    payload: Dict[str, Any] = {"mode": mode}
    if target_columns:
        payload["target_columns"] = target_columns
    if wand_instruction:
        payload["wand_instruction"] = wand_instruction
    r = sess.post_json(f"/api/plan_cadre/{plan_id}/generate", payload)
    return r.get_json() or {"success": False}


@function_tool
def pc_apply_replace_all(plan_id: int, task_id: str) -> Dict[str, Any]:
    """Apply proposed plan-cadre changes via API (replace all)."""
    sess = _require_session()
    r = sess.post_json(f"/api/plan_cadre/{plan_id}/apply_improvement", {"task_id": task_id})
    return r.get_json() or {"success": False}

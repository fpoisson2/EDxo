"""Plan-de-cours specific agent tools (read-only).

These complement `agent_tools_common` with operations that revolve around the
plan-de-cours currently being generated (snapshot of the active instance,
capacities of the associated plan-cadre, teacher context).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from agents import function_tool

from src.app.models import (
    Cours,
    PlanCadre,
    PlanCadreCapacites,
    PlanDeCours,
)
from src.extensions import db
from src.app.tasks.agent_tools_common import _serialize_plan_de_cours

logger = logging.getLogger(__name__)


@function_tool
def get_plan_de_cours_snapshot(plan_id: int) -> dict:
    """Return the plan-de-cours currently being edited/generated (by id)."""
    plan = db.session.get(PlanDeCours, int(plan_id))
    if not plan:
        return {"error": f"Aucun plan de cours id={plan_id}"}
    return _serialize_plan_de_cours(plan)


@function_tool
def list_previous_plans_de_cours(cours_id: int, limit: int = 3) -> List[dict]:
    """Return up to `limit` previous plan-de-cours iterations for the same course.

    Useful to detect patterns and keep the new iteration consistent with
    recent teacher practice.
    """
    limit = max(1, min(int(limit or 3), 10))
    rows = (
        db.session.query(PlanDeCours)
        .filter(PlanDeCours.cours_id == int(cours_id))
        .order_by(PlanDeCours.id.desc())
        .limit(limit)
        .all()
    )
    return [_serialize_plan_de_cours(p) for p in rows]


@function_tool
def get_teacher_context(plan_id: int) -> dict:
    """Return session + teacher information for a plan de cours."""
    plan = db.session.get(PlanDeCours, int(plan_id))
    if not plan:
        return {"error": f"Aucun plan de cours id={plan_id}"}
    return {
        "plan_id": plan.id,
        "session": plan.session,
        "campus": plan.campus,
        "nom_enseignant": plan.nom_enseignant,
        "telephone_enseignant": plan.telephone_enseignant,
        "courriel_enseignant": plan.courriel_enseignant,
        "bureau_enseignant": plan.bureau_enseignant,
    }


@function_tool
def list_plan_cadre_capacites(cours_id: int) -> List[dict]:
    """Return capacites + pondérations from the plan-cadre of a given course.

    Essential for aligning the plan-de-cours calendar and evaluations with the
    plan-cadre (same labels so the evaluation grid can be wired).
    """
    plan: Optional[PlanCadre] = (
        db.session.query(PlanCadre).filter_by(cours_id=int(cours_id)).first()
    )
    if not plan:
        return []
    out: List[dict] = []
    for cap in plan.capacites:
        out.append({
            "id": cap.id,
            "capacite": cap.capacite,
            "description_capacite": cap.description_capacite,
            "ponderation_min": cap.ponderation_min,
            "ponderation_max": cap.ponderation_max,
        })
    return out


PLAN_DE_COURS_TOOLS = [
    get_plan_de_cours_snapshot,
    list_previous_plans_de_cours,
    get_teacher_context,
    list_plan_cadre_capacites,
]

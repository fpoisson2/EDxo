"""Agent-based plan-de-cours generation (bulk / field / calendar / evaluations).

Every legacy direct call to the OpenAI Responses API has been replaced with
an OpenAI Agents SDK run. The agent receives a minimal seed mandate and uses
read-only tools to fetch context (current plan-de-cours, plan-cadre, sibling
courses, previous iterations, etc.). It can also invoke `request_user_review`
to obtain partial feedback from the operator mid-run.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

from celery import shared_task
from celery.exceptions import Ignore
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sa_text

from src.config.env import CELERY_BROKER_URL
from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.app.models import (
    Cours,
    PlanCadre,
    PlanCadreCapacites,
    PlanDeCours,
    PlanDeCoursCalendrier,
    PlanDeCoursEvaluations,
    PlanDeCoursEvaluationsCapacites,
    SectionAISettings,
    User,
)

from .agent_factory import (
    AgentCeleryBridge,
    aggregate_usage,
    build_agent,
    build_partial_response_type,
    run_agent_streaming,
)
from .agent_tools_common import COMMON_TOOLS
from .agent_tools_plan_de_cours import PLAN_DE_COURS_TOOLS
from .agent_tools_review import REVIEW_TOOLS

logger = logging.getLogger(__name__)


def _cancel_requested(task_id: str) -> bool:
    try:
        import redis

        r = redis.Redis.from_url(CELERY_BROKER_URL)
        return bool(r.get(f"edxo:cancel:{task_id}"))
    except Exception:
        return False


###############################################################################
# Pydantic response schemas
###############################################################################
class CalendarEntry(BaseModel):
    semaine: Optional[int] = None
    sujet: Optional[str] = None
    activites: Optional[str] = None
    travaux_hors_classe: Optional[str] = None
    evaluations: Optional[str] = None


class _EvalCap(BaseModel):
    capacite: Optional[str] = None
    ponderation: Optional[str] = None


class _EvalItem(BaseModel):
    titre_evaluation: Optional[str] = None
    description: Optional[str] = None
    semaine: Optional[int] = None
    capacites: List[_EvalCap] = Field(default_factory=list)


class BulkPlanDeCoursResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presentation_du_cours: Optional[str] = None
    objectif_terminal_du_cours: Optional[str] = None
    organisation_et_methodes: Optional[str] = None
    accomodement: Optional[str] = None
    evaluation_formative_apprentissages: Optional[str] = None
    evaluation_expression_francais: Optional[str] = None
    seuil_reussite: Optional[str] = None
    materiel: Optional[str] = None
    calendriers: List[CalendarEntry] = Field(default_factory=list)
    evaluations: List[_EvalItem] = Field(default_factory=list)


class SingleFieldResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    champ_description: Optional[str] = None


class CalendarOnlyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calendriers: List[CalendarEntry] = Field(default_factory=list)


class EvaluationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluations: List[_EvalItem] = Field(default_factory=list)


###############################################################################
# Utilities
###############################################################################
def _serialize_evaluations(plan: PlanDeCours) -> List[dict]:
    evaluations: List[dict] = []
    for e in getattr(plan, "evaluations", []) or []:
        evaluations.append({
            "id": e.id,
            "titre": e.titre_evaluation,
            "description": e.description,
            "semaine": e.semaine,
            "capacites": [
                {
                    "capacite_id": c.capacite_id,
                    "capacite": (
                        db.session.get(PlanCadreCapacites, c.capacite_id).capacite
                        if c.capacite_id else None
                    ),
                    "ponderation": c.ponderation,
                }
                for c in getattr(e, "capacites", [])
            ],
        })
    return evaluations


def _snapshot_fields(plan: PlanDeCours) -> dict:
    return {
        "presentation_du_cours": plan.presentation_du_cours,
        "objectif_terminal_du_cours": plan.objectif_terminal_du_cours,
        "organisation_et_methodes": plan.organisation_et_methodes,
        "accomodement": plan.accomodement,
        "evaluation_formative_apprentissages": plan.evaluation_formative_apprentissages,
        "evaluation_expression_francais": plan.evaluation_expression_francais,
        "seuil_reussite": plan.seuil_reussite,
        "materiel": plan.materiel,
    }


def _snapshot_calendriers(plan: PlanDeCours) -> list:
    return [
        {
            "semaine": c.semaine,
            "sujet": c.sujet,
            "activites": c.activites,
            "travaux_hors_classe": c.travaux_hors_classe,
            "evaluations": c.evaluations,
        }
        for c in plan.calendriers
    ]


def _resolve_settings(mode_key: str):
    """Return (sa, ai_model, reasoning_effort, verbosity) for a given SectionAISettings key."""
    sa = SectionAISettings.get_for(mode_key)
    ai_model = (getattr(sa, "ai_model", None) or "").strip() or "gpt-5"
    reasoning_effort = getattr(sa, "reasoning_effort", None)
    verbosity = getattr(sa, "verbosity", None)
    return sa, ai_model, reasoning_effort, verbosity


def _ensure_user(user_id: int):
    user = db.session.query(User).with_for_update().get(user_id)
    if not user:
        return None, {"status": "error", "message": "Utilisateur introuvable."}
    if not user.openai_key:
        return user, {"status": "error", "message": "Clé OpenAI non configurée."}
    if user.credits is None:
        user.credits = 0.0
        db.session.commit()
    if user.credits <= 0:
        return user, {"status": "error", "message": "Crédits insuffisants."}
    return user, None


def _run_agent(self_task, *, user, ai_model, reasoning_effort, verbosity, system_prompt,
               output_type, tools, seed_message):
    """Wrap the async agent run for sync Celery workers."""
    os.environ["OPENAI_API_KEY"] = user.openai_key
    agent = build_agent(
        name="PlanDeCoursAgent",
        instructions=system_prompt,
        model=ai_model,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
        output_type=output_type,
        tools=list(tools),
    )
    bridge = AgentCeleryBridge(self_task)
    result = asyncio.run(run_agent_streaming(agent, seed_message, bridge=bridge))
    usage_in, usage_out = aggregate_usage(getattr(result, "raw_responses", None) or [])
    try:
        cost = calculate_call_cost(usage_in, usage_out, ai_model)
    except Exception:
        cost = 0.0
    return result, bridge, cost


def _base_payload(plan: PlanDeCours, cours: Cours) -> dict:
    return {
        "plan_id": plan.id,
        "cours_id": plan.cours_id,
        "session": plan.session,
        "cours": {
            "code": getattr(cours, "code", None),
            "nom": getattr(cours, "nom", None),
        },
        "programme_id": cours.programme.id if getattr(cours, "programme", None) else None,
    }


def _seed_text(payload: dict, instructions: List[str]) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False) + "\n\n" + "\n".join(instructions)


BASE_TOOLS = list(COMMON_TOOLS) + list(PLAN_DE_COURS_TOOLS) + list(REVIEW_TOOLS)

BASE_AGENT_GUIDE = [
    "PHASE 1 — OBLIGATOIRE — découverte du contexte via outils :",
    "  1. `get_plan_de_cours_snapshot(plan_id)` — état actuel du plan de cours (toutes sections + calendrier + évaluations).",
    "  2. `get_plan_cadre_snapshot(cours_id)` — plan-cadre du cours (objectifs, capacités).",
    "  3. `list_plan_cadre_capacites(cours_id)` — capacités officielles + pondérations, utilisées pour aligner les évaluations.",
    "  4. `list_previous_plans_de_cours(cours_id, limit=3)` — itérations passées pour inspirer la cohérence du calendrier et des évaluations.",
    "  5. `list_related_courses(cours_id, relation=\"prealable\")` + `get_course_details(prealable_id)` + `get_plan_cadre_snapshot(prealable_id)` — pour connaître ce que les étudiantes apportent du trimestre précédent.",
    "  6. `list_same_programme_courses(cours_id, session)` + `get_plan_de_cours_snapshot_by_cours(other_id, session)` — pour rester cohérent avec les autres cours du même programme / même session.",
    "  7. `list_competencies_for_course(cours_id)` et `get_competence_details(id)` quand tu as besoin des critères/contextes d'une compétence.",
    "  8. `get_teacher_context(plan_id)` pour session + enseignant.",
    "",
    "Ignore les champs textuels du snapshot si un doute subsiste : la source de vérité vient des outils ci-dessus.",
    "",
    "PHASE 2 — Rédaction :",
    "  - `get_section_guidance(section_name, cours_id)` si une consigne spécifique est stockée pour la section.",
    "  - `request_user_review(section, proposed_content_json, question)` pour valider partiellement une section (calendrier, grille d'évaluations, etc.).",
    "",
    "PHASE 3 — Sortie : respecte strictement le schéma JSON imposé par `output_type`. Ne JAMAIS inventer de code de cours, de capacité ou de critère non retourné par un outil.",
]


###############################################################################
# Celery tasks
###############################################################################
@shared_task(bind=True, name="src.app.tasks.generation_plan_de_cours.generate_plan_de_cours_all_task")
def generate_plan_de_cours_all_task(
    self,
    plan_de_cours_id: int,
    prompt: Optional[str] = None,  # legacy signature; ignored by the agent path
    ai_model: Optional[str] = None,
    user_id: Optional[int] = None,
    improve_only: bool = False,
):
    """Generate every field of a plan-de-cours via an agent run."""
    try:
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
        if not plan:
            return {"status": "error", "message": "Plan de cours non trouvé."}
        user, err = _ensure_user(int(user_id))
        if err:
            return err

        cours: Cours = plan.cours
        plan_cadre: Optional[PlanCadre] = cours.plan_cadre if cours else None
        if not cours or not plan_cadre:
            return {"status": "error", "message": "Contexte cours/plan-cadre indisponible."}

        mode_key = "plan_de_cours_improve" if improve_only else "plan_de_cours"
        sa, default_model, reasoning_effort, verbosity = _resolve_settings(mode_key)
        final_model = (ai_model or "").strip() or default_model

        self.update_state(state="PROGRESS", meta={"message": "Appel au modèle IA (agent) en cours..."})
        if _cancel_requested(self.request.id):
            self.update_state(state="REVOKED", meta={"message": "Tâche annulée par l'utilisateur."})
            raise Ignore()

        # Extract additional info from the legacy prompt string if provided
        additional_info = None
        if isinstance(prompt, str) and prompt:
            marker = "Informations complémentaires:"
            if marker in prompt:
                additional_info = prompt.split(marker, 1)[1].strip()

        payload = _base_payload(plan, cours)
        payload.update({
            "mode": "improve_only" if improve_only else "generate_all",
            "additional_info": additional_info or "",
        })
        instructions = list(BASE_AGENT_GUIDE) + [
            "Produis les 8 champs texte + le calendrier hebdomadaire + la grille d'évaluations.",
        ]
        if improve_only:
            instructions.append("Mode amélioration : conserve la structure, reformule et complète sans tout réécrire.")

        try:
            result, bridge, cost = _run_agent(
                self,
                user=user,
                ai_model=final_model,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                system_prompt=(getattr(sa, "system_prompt", None) or "").strip(),
                output_type=BulkPlanDeCoursResponse,
                tools=BASE_TOOLS,
                seed_message=_seed_text(payload, instructions),
            )
        except Ignore:
            raise
        except Exception as e:
            logger.exception("Agent run failed (plan de cours all)")
            return {"status": "error", "message": f"Erreur agent: {e}"}

        parsed = getattr(result, "final_output", None)
        if parsed is None:
            return {"status": "error", "message": "Aucune donnée renvoyée par le modèle."}

        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        old_fields = _snapshot_fields(plan)
        old_calendriers = _snapshot_calendriers(plan)
        old_evaluations = _serialize_evaluations(plan)

        plan.presentation_du_cours = parsed.presentation_du_cours or plan.presentation_du_cours
        plan.objectif_terminal_du_cours = parsed.objectif_terminal_du_cours or plan.objectif_terminal_du_cours
        plan.organisation_et_methodes = parsed.organisation_et_methodes or plan.organisation_et_methodes
        plan.accomodement = parsed.accomodement or plan.accomodement
        plan.evaluation_formative_apprentissages = parsed.evaluation_formative_apprentissages or plan.evaluation_formative_apprentissages
        plan.evaluation_expression_francais = parsed.evaluation_expression_francais or plan.evaluation_expression_francais
        plan.seuil_reussite = parsed.seuil_reussite or plan.seuil_reussite
        plan.materiel = parsed.materiel or plan.materiel

        if parsed.calendriers:
            for cal in plan.calendriers:
                db.session.delete(cal)
            for entry in parsed.calendriers:
                db.session.add(PlanDeCoursCalendrier(
                    plan_de_cours_id=plan.id,
                    semaine=entry.semaine,
                    sujet=entry.sujet,
                    activites=entry.activites,
                    travaux_hors_classe=entry.travaux_hors_classe,
                    evaluations=entry.evaluations,
                ))
        db.session.commit()

        # Evaluations grid
        if parsed.evaluations:
            for e in plan.evaluations:
                db.session.delete(e)
            cap_by_name: dict = {}
            try:
                for c in getattr(plan_cadre, "capacites", []) or []:
                    if c.capacite:
                        cap_by_name[c.capacite.strip()] = c.id
            except Exception:
                pass
            for ev in parsed.evaluations:
                row = PlanDeCoursEvaluations(
                    plan_de_cours_id=plan.id,
                    titre_evaluation=ev.titre_evaluation,
                    description=ev.description,
                    semaine=ev.semaine,
                )
                db.session.add(row)
                db.session.flush()
                for ce in (ev.capacites or []):
                    cap_id = cap_by_name.get((ce.capacite or "").strip()) if ce.capacite else None
                    db.session.add(PlanDeCoursEvaluationsCapacites(
                        evaluation_id=row.id,
                        capacite_id=cap_id,
                        ponderation=ce.ponderation,
                    ))
            db.session.commit()

        evaluations = _serialize_evaluations(plan)
        return {
            "status": "success",
            "fields": _snapshot_fields(plan),
            "calendriers": _snapshot_calendriers(plan),
            "evaluations": evaluations,
            "old_fields": old_fields,
            "old_calendriers": old_calendriers,
            "old_evaluations": old_evaluations,
            "cours_id": plan.cours_id,
            "plan_id": plan.id,
            "session": plan.session,
            "tool_calls": bridge.tool_calls,
            "tool_results": bridge.tool_results,
            "validation_url": f"/plan_de_cours/review/{plan.id}?task_id={self.request.id}",
            "reasoning_summary": bridge.reasoning_summary,
        }
    except Ignore:
        raise
    except Exception as e:
        logger.exception("Erreur dans la tâche generate_plan_de_cours_all_task")
        return {"status": "error", "message": str(e)}


@shared_task(bind=True, name="src.app.tasks.generation_plan_de_cours.generate_plan_de_cours_field_task")
def generate_plan_de_cours_field_task(
    self,
    plan_de_cours_id: int,
    field_name: str,
    additional_info: Optional[str],
    user_id: int,
):
    """Generate or improve a single plan-de-cours field via an agent run."""
    try:
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
        if not plan:
            return {"status": "error", "message": "Plan de cours non trouvé."}

        allowed = {
            "presentation_du_cours",
            "objectif_terminal_du_cours",
            "organisation_et_methodes",
            "accomodement",
            "evaluation_formative_apprentissages",
            "evaluation_expression_francais",
            "seuil_reussite",
            "materiel",
        }
        if field_name not in allowed:
            return {"status": "error", "message": f"Champ non supporté: {field_name}"}

        user, err = _ensure_user(int(user_id))
        if err:
            return err

        cours: Cours = plan.cours
        if not cours:
            return {"status": "error", "message": "Contexte cours indisponible."}

        sa_impv = SectionAISettings.get_for("plan_de_cours_improve")
        if sa_impv and (sa_impv.system_prompt or sa_impv.ai_model or sa_impv.reasoning_effort or sa_impv.verbosity):
            sa = sa_impv
        else:
            sa = SectionAISettings.get_for("plan_de_cours")
        ai_model = (sa.ai_model or "gpt-5")
        reasoning_effort = getattr(sa, "reasoning_effort", None)
        verbosity = getattr(sa, "verbosity", None)

        payload = _base_payload(plan, cours)
        payload.update({
            "mode": "improve_field",
            "target_field": field_name,
            "additional_info": additional_info or "",
        })
        instructions = list(BASE_AGENT_GUIDE) + [
            f"N'améliore que le champ `{field_name}`. Retourne le champ `champ_description` avec le texte final.",
        ]

        self.update_state(state="PROGRESS", meta={"message": f"Génération de '{field_name}' en cours..."})
        if _cancel_requested(self.request.id):
            self.update_state(state="REVOKED", meta={"message": "Tâche annulée par l'utilisateur."})
            raise Ignore()

        try:
            result, bridge, cost = _run_agent(
                self,
                user=user,
                ai_model=ai_model,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                system_prompt=(sa.system_prompt or "").strip(),
                output_type=SingleFieldResponse,
                tools=BASE_TOOLS,
                seed_message=_seed_text(payload, instructions),
            )
        except Ignore:
            raise
        except Exception as e:
            logger.exception("Agent run failed (plan de cours field)")
            return {"status": "error", "message": f"Erreur agent: {e}"}

        parsed = getattr(result, "final_output", None)
        value = getattr(parsed, "champ_description", None) if parsed else None
        if not value:
            return {"status": "error", "message": "Aucune description générée."}

        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        old_fields = _snapshot_fields(plan)
        old_calendriers = _snapshot_calendriers(plan)
        old_evaluations = _serialize_evaluations(plan)

        setattr(plan, field_name, value)
        db.session.commit()

        evaluations = _serialize_evaluations(plan)
        return {
            "status": "success",
            "field_name": field_name,
            "value": value,
            "plan_id": plan.id,
            "cours_id": plan.cours_id,
            "session": plan.session,
            "plan_de_cours_url": f"/cours/{plan.cours_id}/plan_de_cours/{plan.session}/",
            "old_fields": old_fields,
            "old_calendriers": old_calendriers,
            "old_evaluations": old_evaluations,
            "evaluations": evaluations,
            "validation_url": f"/plan_de_cours/review/{plan.id}?task_id={self.request.id}",
            "tool_calls": bridge.tool_calls,
            "tool_results": bridge.tool_results,
            "reasoning_summary": bridge.reasoning_summary,
        }
    except Ignore:
        raise
    except Exception as e:
        logger.exception("Erreur dans la tâche generate_plan_de_cours_field_task")
        return {"status": "error", "message": str(e)}


@shared_task(bind=True, name="src.app.tasks.generation_plan_de_cours.generate_plan_de_cours_calendar_task")
def generate_plan_de_cours_calendar_task(
    self,
    plan_de_cours_id: int,
    additional_info: Optional[str],
    user_id: int,
    current_calendrier: Optional[List[dict]] = None,
):
    """Generate only the weekly calendar for a plan-de-cours."""
    try:
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
        if not plan:
            return {"status": "error", "message": "Plan de cours non trouvé."}
        user, err = _ensure_user(int(user_id))
        if err:
            return err
        cours: Cours = plan.cours
        if not cours:
            return {"status": "error", "message": "Contexte cours indisponible."}

        sa, ai_model, reasoning_effort, verbosity = _resolve_settings("plan_de_cours_improve")

        payload = _base_payload(plan, cours)
        payload.update({
            "mode": "improve_calendar",
            "additional_info": additional_info or "",
            "expected_output": {"only": "calendriers", "strict": True},
        })
        instructions = list(BASE_AGENT_GUIDE) + [
            "Ne génère que la liste `calendriers` (hebdomadaire). Pas de champs texte.",
        ]

        self.update_state(state="PROGRESS", meta={"message": "Génération du calendrier…"})
        if _cancel_requested(self.request.id):
            self.update_state(state="REVOKED", meta={"message": "Tâche annulée par l'utilisateur."})
            raise Ignore()

        try:
            result, bridge, cost = _run_agent(
                self,
                user=user,
                ai_model=ai_model,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                system_prompt=(sa.system_prompt or "").strip(),
                output_type=CalendarOnlyResponse,
                tools=BASE_TOOLS,
                seed_message=_seed_text(payload, instructions),
            )
        except Ignore:
            raise
        except Exception as e:
            logger.exception("Agent run failed (plan de cours calendar)")
            return {"status": "error", "message": f"Erreur agent: {e}"}

        parsed = getattr(result, "final_output", None)
        entries: List[CalendarEntry] = (parsed.calendriers if parsed else []) or []
        if not entries:
            return {"status": "error", "message": "Aucune entrée générée pour le calendrier."}

        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        old_calendriers = _snapshot_calendriers(plan)
        old_evaluations = _serialize_evaluations(plan)

        for cal in plan.calendriers:
            db.session.delete(cal)
        for entry in entries:
            db.session.add(PlanDeCoursCalendrier(
                plan_de_cours_id=plan.id,
                semaine=entry.semaine,
                sujet=entry.sujet,
                activites=entry.activites,
                travaux_hors_classe=entry.travaux_hors_classe,
                evaluations=entry.evaluations,
            ))
        db.session.commit()

        return {
            "status": "success",
            "plan_id": plan.id,
            "cours_id": plan.cours_id,
            "session": plan.session,
            "calendriers": _snapshot_calendriers(plan),
            "evaluations": _serialize_evaluations(plan),
            "plan_de_cours_url": f"/cours/{plan.cours_id}/plan_de_cours/{plan.session}/",
            "old_fields": _snapshot_fields(plan),
            "old_calendriers": old_calendriers,
            "old_evaluations": old_evaluations,
            "validation_url": f"/plan_de_cours/review/{plan.id}?task_id={self.request.id}",
            "tool_calls": bridge.tool_calls,
            "tool_results": bridge.tool_results,
            "reasoning_summary": bridge.reasoning_summary,
        }
    except Ignore:
        raise
    except Exception as e:
        logger.exception("Erreur dans la tâche generate_plan_de_cours_calendar_task")
        return {"status": "error", "message": str(e)}


@shared_task(bind=True, name="src.app.tasks.generation_plan_de_cours.generate_plan_de_cours_evaluations_task")
def generate_plan_de_cours_evaluations_task(
    self,
    plan_de_cours_id: int,
    additional_info: Optional[str],
    user_id: int,
    current_evaluations: Optional[List[dict]] = None,
):
    """Generate only the evaluation grid for a plan-de-cours."""
    try:
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
        if not plan:
            return {"status": "error", "message": "Plan de cours non trouvé."}
        user, err = _ensure_user(int(user_id))
        if err:
            return err
        cours: Cours = plan.cours
        plan_cadre: Optional[PlanCadre] = cours.plan_cadre if cours else None
        if not cours:
            return {"status": "error", "message": "Contexte cours indisponible."}

        sa, ai_model, reasoning_effort, verbosity = _resolve_settings("plan_de_cours_improve")

        payload = _base_payload(plan, cours)
        payload.update({
            "mode": "improve_evaluations",
            "additional_info": additional_info or "",
            "expected_output": {"only": "evaluations", "strict": True},
        })
        instructions = list(BASE_AGENT_GUIDE) + [
            "Ne génère que la liste `evaluations` alignée sur les capacités du plan-cadre.",
        ]

        self.update_state(state="PROGRESS", meta={"message": "Génération des évaluations…"})
        if _cancel_requested(self.request.id):
            self.update_state(state="REVOKED", meta={"message": "Tâche annulée par l'utilisateur."})
            raise Ignore()

        try:
            result, bridge, cost = _run_agent(
                self,
                user=user,
                ai_model=ai_model,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                system_prompt=(sa.system_prompt or "").strip(),
                output_type=EvaluationsResponse,
                tools=BASE_TOOLS,
                seed_message=_seed_text(payload, instructions),
            )
        except Ignore:
            raise
        except Exception as e:
            logger.exception("Agent run failed (plan de cours evaluations)")
            return {"status": "error", "message": f"Erreur agent: {e}"}

        parsed = getattr(result, "final_output", None)
        evals = (parsed.evaluations if parsed else []) or []
        if not evals:
            return {"status": "error", "message": "Aucune évaluation générée."}

        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        old_fields = _snapshot_fields(plan)
        old_calendriers = _snapshot_calendriers(plan)
        old_evaluations = _serialize_evaluations(plan)

        for e in plan.evaluations:
            db.session.delete(e)

        cap_by_name: dict = {}
        try:
            for c in getattr(plan_cadre, "capacites", []) or []:
                if c.capacite:
                    cap_by_name[c.capacite.strip()] = c.id
        except Exception:
            pass

        for ev in evals:
            row = PlanDeCoursEvaluations(
                plan_de_cours_id=plan.id,
                titre_evaluation=ev.titre_evaluation,
                description=ev.description,
                semaine=ev.semaine,
            )
            db.session.add(row)
            db.session.flush()
            for ce in (ev.capacites or []):
                cap_id = cap_by_name.get((ce.capacite or "").strip()) if ce.capacite else None
                db.session.add(PlanDeCoursEvaluationsCapacites(
                    evaluation_id=row.id,
                    capacite_id=cap_id,
                    ponderation=ce.ponderation,
                ))
        db.session.commit()

        return {
            "status": "success",
            "plan_id": plan.id,
            "cours_id": plan.cours_id,
            "session": plan.session,
            "fields": _snapshot_fields(plan),
            "calendriers": _snapshot_calendriers(plan),
            "evaluations": _serialize_evaluations(plan),
            "old_fields": old_fields,
            "old_calendriers": old_calendriers,
            "old_evaluations": old_evaluations,
            "plan_de_cours_url": f"/cours/{plan.cours_id}/plan_de_cours/{plan.session}/",
            "validation_url": f"/plan_de_cours/review/{plan.id}?task_id={self.request.id}",
            "tool_calls": bridge.tool_calls,
            "tool_results": bridge.tool_results,
            "reasoning_summary": bridge.reasoning_summary,
        }
    except Ignore:
        raise
    except Exception as e:
        logger.exception("Erreur dans la tâche generate_plan_de_cours_evaluations_task")
        return {"status": "error", "message": str(e)}

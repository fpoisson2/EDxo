# app/tasks.py
"""Agent-based plan-cadre generation.

The legacy direct call to the OpenAI Responses API has been fully replaced
by the OpenAI Agents SDK. The agent receives a minimal seed mandate and
uses read-only tools (see `agent_tools_common`) to fetch context lazily
(course details, competencies, plans of sibling courses, etc.). It can
also solicit partial user feedback via `request_user_review` when a
section is uncertain.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from ..models import (
    ChatModelConfig,
    Competence,
    Cours,
    CoursCorequis,
    CoursPrealable,
    ElementCompetence,
    ElementCompetenceParCours,
    GlobalGenerationSettings,
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreCapaciteMoyensEvaluation,
    PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteSavoirsNecessaires,
    PlanCadreSavoirEtre,
    Programme,
    SectionAISettings,
    User,
)

from celery.exceptions import Ignore
from src.celery_app import celery
from src.config.env import CELERY_BROKER_URL
from src.extensions import db
from src.utils import replace_tags_jinja2, get_plan_cadre_data
from src.utils.openai_pricing import calculate_call_cost

from .agent_factory import (
    AgentCeleryBridge,
    aggregate_usage,
    build_agent,
    build_partial_response_type,
    run_agent_streaming,
)
from .agent_tools_common import COMMON_TOOLS
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
# Schemas Pydantic pour IA
###############################################################################
def _postprocess_openai_schema(schema: dict) -> None:
    """Recursively tailor a Pydantic schema for OpenAI JSON responses."""
    schema.pop("default", None)

    if "$ref" in schema:
        return

    if schema.get("type") == "object" or "properties" in schema:
        schema["additionalProperties"] = False

    props = schema.get("properties")
    if props:
        schema["required"] = schema.get("required", [])
        for prop_schema in props.values():
            _postprocess_openai_schema(prop_schema)

    if "items" in schema:
        items = schema["items"]
        if isinstance(items, dict):
            _postprocess_openai_schema(items)
        elif isinstance(items, list):
            for item in items:
                _postprocess_openai_schema(item)

    if "$defs" in schema:
        for def_schema in schema["$defs"].values():
            _postprocess_openai_schema(def_schema)


class OpenAIFunctionModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra=lambda schema, _: _postprocess_openai_schema(schema),
    )


class AIContentDetail(OpenAIFunctionModel):
    texte: str
    description: str


class AISavoirFaire(OpenAIFunctionModel):
    texte: str
    seuil_performance: str
    critere_reussite: str


class AICapacite(OpenAIFunctionModel):
    capacite: str
    description_capacite: str
    ponderation_min: int
    ponderation_max: int
    savoirs_necessaires: List[str]
    savoirs_faire: List[AISavoirFaire]
    moyens_evaluation: List[str]


class PlanCadreAIResponse(OpenAIFunctionModel):
    place_intro: str
    objectif_terminal: str
    structure_intro: str
    structure_activites_theoriques: str
    structure_activites_pratiques: str
    structure_activites_prevues: str
    eval_evaluation_sommative: str
    eval_nature_evaluations_sommatives: str
    eval_evaluation_de_la_langue: str
    eval_evaluation_sommatives_apprentissages: str
    competences_developpees: List[AIContentDetail]
    competences_certifiees: List[AIContentDetail]
    cours_corequis: List[AIContentDetail]
    objets_cibles: List[AIContentDetail]
    cours_relies: List[AIContentDetail]
    cours_prealables: List[AIContentDetail]
    savoir_etre: List[str]
    capacites: List[AICapacite]


###############################################################################
# Mapping helpers (affichage ↔ colonnes / tables)
###############################################################################
FIELD_TO_PLAN_CADRE_COLUMN = {
    "Intro et place du cours": "place_intro",
    "Objectif terminal": "objectif_terminal",
    "Introduction Structure du Cours": "structure_intro",
    "Activités Théoriques": "structure_activites_theoriques",
    "Activités Pratiques": "structure_activites_pratiques",
    "Activités Prévues": "structure_activites_prevues",
    "Évaluation Sommative des Apprentissages": "eval_evaluation_sommative",
    "Nature des Évaluations Sommatives": "eval_nature_evaluations_sommatives",
    "Évaluation de la Langue": "eval_evaluation_de_la_langue",
    "Évaluation formative des apprentissages": "eval_evaluation_sommatives_apprentissages",
}

FIELD_TO_TABLE_INSERT = {
    "Description des compétences développées": "PlanCadreCompetencesDeveloppees",
    "Description des Compétences certifiées": "PlanCadreCompetencesCertifiees",
    "Description des cours corequis": "PlanCadreCoursCorequis",
    "Objets cibles": "PlanCadreObjetsCibles",
    "Description des cours reliés": "PlanCadreCoursRelies",
    "Description des cours préalables": "PlanCadreCoursPrealables",
}

TABLE_MAPPING_ATTR = {
    "competences_developpees": ("PlanCadreCompetencesDeveloppees", "Description des compétences développées"),
    "competences_certifiees": ("PlanCadreCompetencesCertifiees", "Description des Compétences certifiées"),
    "cours_corequis": ("PlanCadreCoursCorequis", "Description des cours corequis"),
    "cours_prealables": ("PlanCadreCoursPrealables", "Description des cours préalables"),
    "objets_cibles": ("PlanCadreObjetsCibles", "Objets cibles"),
    "cours_relies": ("PlanCadreCoursRelies", "Description des cours reliés"),
}


def _include_section(section_name: str, target_columns: List[str], col_name: Optional[str] = None) -> bool:
    if not target_columns:
        return True
    if col_name and col_name in target_columns:
        return True
    logical_key_map = {
        "Description des compétences développées": "competences_developpees",
        "Description des Compétences certifiées": "competences_certifiees",
        "Description des cours corequis": "cours_corequis",
        "Objets cibles": "objets_cibles",
        "Description des cours reliés": "cours_relies",
        "Description des cours préalables": "cours_prealables",
        "Savoir-être": "savoirs_etre",
        "Capacité et pondération": "capacites",
        "Savoirs nécessaires d'une capacité": "capacites",
        "Savoirs faire d'une capacité": "capacites",
        "Moyen d'évaluation d'une capacité": "capacites",
    }
    key = logical_key_map.get(section_name)
    return bool(key and key in target_columns)


def _apply_non_ai_updates(plan: PlanCadre, target_columns: List[str], plan_cadre_data: dict,
                          improve_only: bool, preview: bool) -> tuple[list, list]:
    """Apply non-AI rows of GlobalGenerationSettings directly, or collect them for preview."""
    parametres = db.session.query(
        GlobalGenerationSettings.section,
        GlobalGenerationSettings.use_ai,
        GlobalGenerationSettings.text_content,
    ).all()
    non_ai_updates: list = []
    non_ai_inserts: list = []
    savoir_etre_non_ai: Optional[str] = None
    for row in parametres:
        section_name = (row.section or "").strip()
        raw_text = str(row.text_content or "")
        try:
            replaced = replace_tags_jinja2(raw_text, plan_cadre_data)
        except Exception:
            replaced = raw_text
        raw_flag = row.use_ai
        is_ai = raw_flag if isinstance(raw_flag, bool) else str(raw_flag or "").strip().lower() in {"1", "true", "t", "yes", "on"}
        if is_ai or not replaced.strip():
            continue
        if section_name in FIELD_TO_PLAN_CADRE_COLUMN:
            col_name = FIELD_TO_PLAN_CADRE_COLUMN[section_name]
            if not _include_section(section_name, target_columns, col_name):
                continue
            non_ai_updates.append((col_name, replaced))
        elif section_name in FIELD_TO_TABLE_INSERT:
            if not _include_section(section_name, target_columns):
                continue
            non_ai_inserts.append((FIELD_TO_TABLE_INSERT[section_name], replaced))
        elif section_name == "Savoir-être":
            if _include_section(section_name, target_columns):
                savoir_etre_non_ai = replaced
    if not (improve_only or preview):
        for col_name, val in non_ai_updates:
            setattr(plan, col_name, val)
        for table_name, val in non_ai_inserts:
            db.session.execute(
                text(f"INSERT INTO {table_name} (plan_cadre_id, texte) VALUES (:pcid, :val)"),
                {"pcid": plan.id, "val": val},
            )
        if savoir_etre_non_ai:
            for line in (l.strip() for l in savoir_etre_non_ai.split("\n") if l.strip()):
                db.session.add(PlanCadreSavoirEtre(plan_cadre_id=plan.id, texte=line))
        db.session.commit()
    return non_ai_updates, non_ai_inserts


def _build_seed_message(
    *,
    plan: PlanCadre,
    mode: str,
    improve_only: bool,
    target_columns: List[str],
    additional_info: str,
    wand_instruction: str,
    preview: bool,
) -> str:
    cours = plan.cours
    primary_prog = cours.programme if cours else None
    payload = {
        "mode": "wand" if mode == "wand" else ("improve_only" if improve_only else "standard"),
        "plan_cadre_id": plan.id,
        "cours_id": plan.cours_id,
        "cours": {
            "id": cours.id if cours else None,
            "code": cours.code if cours else None,
            "nom": cours.nom if cours else None,
        },
        "programme": {
            "id": primary_prog.id if primary_prog else None,
            "nom": primary_prog.nom if primary_prog else None,
        },
        "target_columns": target_columns,
        "additional_info": additional_info or "",
        "preview": bool(preview),
    }
    if mode == "wand" and wand_instruction:
        payload["wand_instruction"] = wand_instruction
    instructions = [
        "Tu es chargé de produire (ou d'améliorer) le plan-cadre du cours identifié ci-dessus.",
        "",
        "PHASE 1 — OBLIGATOIRE — Découverte systématique du contexte :",
        "  1. `get_course_details(cours_id)` — données brutes du cours (compétences, heures, programme).",
        "  2. `list_related_courses(cours_id, relation=\"prealable\")` puis, pour chaque résultat, `get_course_details(prealable_id)` ET `get_plan_cadre_snapshot(prealable_id)` — pour rédiger les descriptions de cours préalables à partir des VRAIS cours préalables du programme, pas à partir du texte déjà stocké.",
        "  3. `list_related_courses(cours_id, relation=\"corequis\")` + mêmes sous-appels pour les corequis.",
        "  4. `list_related_courses(cours_id, relation=\"developpe_meme_competence\")` — cours partageant au moins une compétence, utiles pour la section « cours reliés ».",
        "  5. `list_same_programme_courses(cours_id)` — pour situer le cours dans son fil pédagogique; au besoin récupérer leur plan-cadre via `get_plan_cadre_snapshot`.",
        "  6. `list_competencies_for_course(cours_id)` et `get_competence_details(id)` pour chaque compétence développée OU certifiée (critères, contexte, éléments) — NE PAS deviner les critères, les récupérer.",
        "",
        "IMPORTANT : les champs `cours_prealables`/`cours_corequis`/`cours_relies` du `get_plan_cadre_snapshot` contiennent d'ANCIENS textes descriptifs. Ignore-les comme source de vérité ; la vraie liste vient de `list_related_courses`.",
        "",
        "PHASE 2 — Consignes de rédaction :",
        "  - `get_section_guidance(section_name, cours_id)` avant de rédiger chaque section si une consigne spécifique est stockée.",
        "  - `request_user_review(section, proposed_content_json, question)` quand une section mérite validation partielle (ex. capacités, pondérations).",
        "",
        "PHASE 3 — Sortie : retourne obligatoirement la structure JSON `PlanCadreAIResponse` imposée par le schéma. Ne JAMAIS inventer un code de cours, un nom de compétence ou un critère qui n'apparaît pas dans les résultats d'outils.",
    ]
    if target_columns:
        instructions.append(
            "Concentre-toi uniquement sur les colonnes ciblées : " + ", ".join(target_columns) + "."
        )
    if improve_only:
        instructions.append(
            "Mode amélioration : privilégie les reformulations ciblées, conserve la structure existante."
        )
    return json.dumps(payload, ensure_ascii=False) + "\n\n" + "\n".join(instructions)


def _clean(val) -> str:
    if val is None:
        return ""
    try:
        return str(val).strip().strip('"').strip("'")
    except Exception:
        return ""


def _parsed_get(parsed, key, default=None):
    if isinstance(parsed, dict):
        return parsed.get(key, default)
    return getattr(parsed, key, default)


def _item_get(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _apply_parsed(plan: PlanCadre, parsed, *, improve_only: bool, preview: bool) -> dict:
    """Apply the agent's structured response either to the DB or to a preview dict."""
    proposed: dict = {"fields": {}, "fields_with_description": {}, "capacites": []}
    simple_columns = list(FIELD_TO_PLAN_CADRE_COLUMN.values())
    for col in simple_columns:
        val = _clean(_parsed_get(parsed, col))
        if not val:
            continue
        if improve_only or preview:
            proposed["fields"][col] = val
        else:
            setattr(plan, col, val)

    for attr, (table_name, display_name) in TABLE_MAPPING_ATTR.items():
        items = _parsed_get(parsed, attr) or []
        if not items:
            continue
        elements = []
        for item in items:
            texte_comp = _clean(_item_get(item, "texte"))
            desc_comp = _clean(_item_get(item, "description"))
            if texte_comp or desc_comp:
                elements.append({"texte": texte_comp, "description": desc_comp})
        if improve_only or preview:
            proposed["fields_with_description"][display_name] = elements
        else:
            for el in elements:
                db.session.execute(
                    text(
                        f"INSERT OR REPLACE INTO {table_name} (plan_cadre_id, texte, description) "
                        f"VALUES (:pid, :txt, :desc)"
                    ),
                    {"pid": plan.id, "txt": el["texte"], "desc": el["description"]},
                )

    savoir_etre = _parsed_get(parsed, "savoir_etre")
    if savoir_etre:
        if improve_only or preview:
            proposed["savoir_etre"] = [_clean(se) for se in savoir_etre]
        else:
            for se in savoir_etre:
                db.session.add(PlanCadreSavoirEtre(plan_cadre_id=plan.id, texte=_clean(se)))

    capacites = _parsed_get(parsed, "capacites")
    if capacites:
        if improve_only or preview:
            for cap in capacites:
                proposed["capacites"].append({
                    "capacite": _clean(_item_get(cap, "capacite")),
                    "description_capacite": _clean(_item_get(cap, "description_capacite")),
                    "ponderation_min": int(_item_get(cap, "ponderation_min") or 0),
                    "ponderation_max": int(_item_get(cap, "ponderation_max") or 0),
                    "savoirs_necessaires": [_clean(sn) for sn in (_item_get(cap, "savoirs_necessaires") or [])],
                    "savoirs_faire": [
                        {
                            "texte": _clean(_item_get(sf, "texte")),
                            "seuil_performance": _clean(_item_get(sf, "seuil_performance")),
                            "critere_reussite": _clean(_item_get(sf, "critere_reussite")),
                        }
                        for sf in (_item_get(cap, "savoirs_faire") or [])
                    ],
                    "moyens_evaluation": [_clean(me) for me in (_item_get(cap, "moyens_evaluation") or [])],
                })
        else:
            for cap in capacites:
                new_cap = PlanCadreCapacites(
                    plan_cadre_id=plan.id,
                    capacite=_clean(_item_get(cap, "capacite")),
                    description_capacite=_clean(_item_get(cap, "description_capacite")),
                    ponderation_min=int(_item_get(cap, "ponderation_min") or 0),
                    ponderation_max=int(_item_get(cap, "ponderation_max") or 0),
                )
                db.session.add(new_cap)
                db.session.flush()
                for sn in (_item_get(cap, "savoirs_necessaires") or []):
                    db.session.add(PlanCadreCapaciteSavoirsNecessaires(capacite_id=new_cap.id, texte=_clean(sn)))
                for sf in (_item_get(cap, "savoirs_faire") or []):
                    db.session.add(PlanCadreCapaciteSavoirsFaire(
                        capacite_id=new_cap.id,
                        texte=_clean(_item_get(sf, "texte")),
                        cible=_clean(_item_get(sf, "seuil_performance")),
                        seuil_reussite=_clean(_item_get(sf, "critere_reussite")),
                    ))
                for me in (_item_get(cap, "moyens_evaluation") or []):
                    db.session.add(PlanCadreCapaciteMoyensEvaluation(capacite_id=new_cap.id, texte=_clean(me)))

    if improve_only or preview:
        if not proposed["fields"]:
            proposed.pop("fields")
        if not proposed.get("fields_with_description"):
            proposed.pop("fields_with_description", None)
        if not proposed.get("savoir_etre"):
            proposed.pop("savoir_etre", None)
        if not proposed["capacites"]:
            proposed.pop("capacites")
    return proposed


@celery.task(bind=True, name="src.app.tasks.generation_plan_cadre.generate_plan_cadre_content_task")
def generate_plan_cadre_content_task(self, plan_id, form_data, user_id):
    """Celery task that drives the OpenAI Agents SDK run for a plan-cadre."""
    try:
        logger.info("Starting plan-cadre agent task plan_id=%s user_id=%s", plan_id, user_id)
        plan: Optional[PlanCadre] = db.session.get(PlanCadre, plan_id)
        if not plan:
            return {"status": "error", "message": "Plan Cadre non trouvé."}

        user = db.session.query(User.openai_key, User.credits).filter_by(id=user_id).first()
        if not user:
            return {"status": "error", "message": "Utilisateur introuvable."}
        openai_key = user.openai_key
        user_credits = user.credits
        if not openai_key:
            return {"status": "error", "message": "Aucune clé OpenAI configurée dans votre profil."}
        if user_credits is not None and user_credits <= 0:
            return {"status": "error", "message": "Vous n’avez plus de crédits pour effectuer un appel OpenAI."}

        mode = (form_data.get("mode") or "").strip().lower()
        additional_info = form_data.get("additional_info") or ""
        ai_model = (form_data.get("ai_model") or "").strip()
        improve_only = bool(form_data.get("improve_only", False))
        preview = bool(form_data.get("preview", False))
        target_columns = form_data.get("target_columns") or []
        if isinstance(target_columns, str):
            target_columns = [c.strip() for c in target_columns.split(",") if c.strip()]
        reasoning_effort = form_data.get("reasoning_effort") or None
        verbosity = form_data.get("verbosity") or None
        wand_instruction = form_data.get("wand_instruction") or ""

        if mode == "wand":
            improve_only = True
            if wand_instruction:
                additional_info = wand_instruction

        try:
            cfg = ChatModelConfig.get_current()
        except Exception:
            cfg = None
        try:
            sa = SectionAISettings.get_for("plan_cadre_improve" if improve_only else "plan_cadre")
        except Exception:
            sa = None
        if not ai_model:
            ai_model = (
                sa.ai_model if sa and getattr(sa, "ai_model", None)
                else (cfg.chat_model if cfg and getattr(cfg, "chat_model", None) else "gpt-5-mini")
            )
        if not reasoning_effort:
            reasoning_effort = (
                sa.reasoning_effort if sa and getattr(sa, "reasoning_effort", None)
                else (cfg.reasoning_effort if cfg and getattr(cfg, "reasoning_effort", None) else None)
            )
        if not verbosity:
            verbosity = (
                sa.verbosity if sa and getattr(sa, "verbosity", None)
                else (cfg.verbosity if cfg and getattr(cfg, "verbosity", None) else None)
            )

        if mode != "wand":
            plan.additional_info = additional_info
            plan.ai_model = ai_model
            db.session.commit()

        cours_nom = plan.cours.nom if plan.cours else "Non défini"
        self.update_state(state="PROGRESS", meta={"message": f"Génération du plan-cadre du cours {cours_nom} en cours"})

        if _cancel_requested(self.request.id):
            self.update_state(state="REVOKED", meta={"message": "Tâche annulée par l'utilisateur."})
            raise Ignore()

        plan_cadre_data = get_plan_cadre_data(plan.cours_id) or {}
        _apply_non_ai_updates(plan, target_columns, plan_cadre_data, improve_only, preview)

        # Configure OpenAI credentials for the agent run
        import os
        os.environ["OPENAI_API_KEY"] = openai_key

        # Build agent
        output_type = PlanCadreAIResponse
        if improve_only and target_columns:
            output_type = build_partial_response_type(PlanCadreAIResponse, target_columns)

        system_prompt = (getattr(sa, "system_prompt", None) or "").strip()
        agent = build_agent(
            name="PlanCadreAgent",
            instructions=system_prompt,
            model=ai_model,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
            output_type=output_type,
            tools=list(COMMON_TOOLS) + list(REVIEW_TOOLS),
        )

        seed = _build_seed_message(
            plan=plan,
            mode=mode,
            improve_only=improve_only,
            target_columns=target_columns,
            additional_info=additional_info,
            wand_instruction=wand_instruction,
            preview=preview,
        )

        bridge = AgentCeleryBridge(self)
        self.update_state(state="PROGRESS", meta={"message": "Appel au modèle IA (mode agent) en cours..."})

        try:
            result = asyncio.run(run_agent_streaming(agent, seed, bridge=bridge))
        except Ignore:
            raise
        except Exception as e:
            logger.exception("Agents SDK run failed")
            return {"status": "error", "message": f"Erreur agent: {e}"}

        parsed = getattr(result, "final_output", None)
        if parsed is None:
            return {"status": "error", "message": "Aucune sortie structurée produite par l'agent."}

        usage_in, usage_out = aggregate_usage(getattr(result, "raw_responses", None) or [])
        try:
            total_cost = calculate_call_cost(usage_in, usage_out, ai_model)
        except Exception:
            total_cost = 0.0
        logger.info(
            "Plan-cadre agent run: %s (%d in / %d out tokens, cost=%.6f)",
            ai_model, usage_in, usage_out, total_cost,
        )
        if user_credits is not None:
            new_credits = user_credits - total_cost
            if new_credits < 0:
                raise ValueError("Crédits insuffisants pour effectuer l'opération")
            db.session.execute(
                text("UPDATE User SET credits = :credits WHERE id = :uid"),
                {"credits": new_credits, "uid": user_id},
            )
            db.session.commit()

        if _cancel_requested(self.request.id):
            self.update_state(state="REVOKED", meta={"message": "Tâche annulée par l'utilisateur."})
            raise Ignore()

        proposed = _apply_parsed(plan, parsed, improve_only=improve_only, preview=preview)
        reasoning_summary_text = bridge.reasoning_summary

        if improve_only or preview:
            result_payload = {
                "status": "success",
                "message": f"Proposition d'amélioration générée. Coût: {round(total_cost, 4)} crédits.",
                "plan_id": plan.id,
                "cours_id": plan.cours_id,
                "preview": True,
                "proposed": proposed,
                "validation_url": f"/plan_cadre/{plan.id}/review?task_id={self.request.id}",
                "tool_calls": bridge.tool_calls,
                "tool_results": bridge.tool_results,
            }
            if bridge.buffer:
                result_payload["stream_buffer"] = bridge.buffer
            if reasoning_summary_text:
                result_payload["reasoning_summary"] = reasoning_summary_text
            self.update_state(state="SUCCESS", meta=result_payload)
            return result_payload

        db.session.commit()
        result_payload = {
            "status": "success",
            "message": f"Contenu généré automatiquement avec succès! Coût total: {round(total_cost, 4)} crédits.",
            "plan_id": plan.id,
            "cours_id": plan.cours_id,
            "tool_calls": bridge.tool_calls,
            "tool_results": bridge.tool_results,
        }
        if bridge.buffer:
            result_payload["stream_buffer"] = bridge.buffer
        if reasoning_summary_text:
            result_payload["reasoning_summary"] = reasoning_summary_text
        self.update_state(state="SUCCESS", meta=result_payload)
        return result_payload

    except Ignore:
        raise
    except Exception as e:
        db.session.rollback()
        logger.exception("Unexpected error in plan-cadre agent task")
        result_meta = {"status": "error", "message": f"Erreur lors de la génération du contenu: {e}"}
        if _cancel_requested(self.request.id):
            self.update_state(state="REVOKED", meta={"message": "Tâche annulée par l'utilisateur."})
            raise Ignore()
        self.update_state(state="SUCCESS", meta=result_meta)
        return result_meta

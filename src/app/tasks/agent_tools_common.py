"""Read-only tools exposed to the plan-cadre / plan-de-cours agents.

Each function is registered as an agent `function_tool` (OpenAI Agents SDK).
They wrap existing SQLAlchemy queries so no new business logic lives here.

The tools rely on the Flask app context that is set up by the Celery
`ContextTask` (see `src/celery_app.py`). They therefore work transparently
when called inside an agent run executed within a Celery task.
"""
from __future__ import annotations

import logging
from typing import List, Literal, Optional

from agents import function_tool

from src.app.models import (
    Competence,
    Cours,
    CoursCorequis,
    CoursPrealable,
    ElementCompetence,
    ElementCompetenceCriteria,
    ElementCompetenceParCours,
    GlobalGenerationSettings,
    PlanCadre,
    PlanCadreCapacites,
    PlanDeCours,
    PlanDeCoursCalendrier,
    PlanDeCoursEvaluations,
    Programme,
)
from src.extensions import db
from src.utils import get_plan_cadre_data, replace_tags_jinja2

logger = logging.getLogger(__name__)


def _clip(val: Optional[str], n: int = 800) -> Optional[str]:
    if not val:
        return val
    return (val[:n] + "…") if len(val) > n else val


@function_tool
def get_course_details(cours_id: int) -> dict:
    """Return a compact view of a course and its plan-cadre context.

    Wraps `get_plan_cadre_data` and trims long text fields. Use this as the
    primary entry point to learn about the seed course or any related course
    discovered via other tools.
    """
    data = get_plan_cadre_data(cours_id)
    if not data:
        return {"error": f"Aucun cours avec id={cours_id}"}
    trimmed = dict(data)
    cours = trimmed.get("cours") or {}
    trimmed["cours"] = cours
    for k in ("competences_developpees", "competences_atteintes"):
        for comp in trimmed.get(k, []) or []:
            comp["critere_performance"] = _clip(comp.get("critere_performance"), 400)
            comp["contexte_realisation"] = _clip(comp.get("contexte_realisation"), 400)
    return trimmed


@function_tool
def search_courses(query: str, programme_id: Optional[int] = None, limit: int = 20) -> List[dict]:
    """Find courses whose code or name matches `query` (case-insensitive).

    Optionally restrict to a single programme. Returns up to `limit` rows.
    """
    limit = max(1, min(int(limit or 20), 100))
    like = f"%{query.strip()}%" if query else "%"
    q = db.session.query(Cours).filter(
        db.or_(Cours.code.ilike(like), Cours.nom.ilike(like))
    )
    if programme_id:
        q = q.filter(Cours.programmes.any(Programme.id == int(programme_id)))
    rows = q.limit(limit).all()
    return [
        {
            "id": c.id,
            "code": c.code,
            "nom": c.nom,
            "heures_theorie": c.heures_theorie,
            "heures_laboratoire": c.heures_laboratoire,
            "heures_travail_maison": c.heures_travail_maison,
        }
        for c in rows
    ]


@function_tool
def list_programme_courses(programme_id: int, session: Optional[int] = None, limit: int = 200) -> List[dict]:
    """List courses belonging to a programme, optionally filtered by session."""
    prog = db.session.get(Programme, int(programme_id))
    if not prog:
        return []
    results: List[dict] = []
    for assoc in getattr(prog, "cours_assocs", []) or []:
        if session is not None and assoc.session != session:
            continue
        c = assoc.cours
        if not c:
            continue
        results.append({
            "id": c.id,
            "code": c.code,
            "nom": c.nom,
            "session": assoc.session,
        })
        if len(results) >= max(1, min(int(limit or 200), 500)):
            break
    return results


@function_tool
def list_related_courses(
    cours_id: int,
    relation: Literal["prealable", "corequis", "developpe_meme_competence"],
) -> List[dict]:
    """Return courses related to `cours_id` by the given relation.

    - prealable: courses that are prerequisites of `cours_id`
    - corequis: courses that are corequisites of `cours_id`
    - developpe_meme_competence: other courses developing at least one of
      the same competency elements as `cours_id`
    """
    if relation == "prealable":
        rows = (
            db.session.query(CoursPrealable.cours_prealable_id, Cours.code, Cours.nom)
            .join(Cours, CoursPrealable.cours_prealable_id == Cours.id)
            .filter(CoursPrealable.cours_id == int(cours_id))
            .all()
        )
        return [{"id": r.cours_prealable_id, "code": r.code, "nom": r.nom} for r in rows]

    if relation == "corequis":
        rows = (
            db.session.query(CoursCorequis.cours_corequis_id, Cours.code, Cours.nom)
            .join(Cours, CoursCorequis.cours_corequis_id == Cours.id)
            .filter(CoursCorequis.cours_id == int(cours_id))
            .all()
        )
        return [{"id": r.cours_corequis_id, "code": r.code, "nom": r.nom} for r in rows]

    # developpe_meme_competence
    sub = db.session.query(ElementCompetenceParCours.element_competence_id).filter_by(
        cours_id=int(cours_id)
    ).subquery()
    rows = (
        db.session.query(Cours.id, Cours.code, Cours.nom)
        .join(ElementCompetenceParCours, Cours.id == ElementCompetenceParCours.cours_id)
        .filter(ElementCompetenceParCours.element_competence_id.in_(db.select(sub.c.element_competence_id)))
        .filter(Cours.id != int(cours_id))
        .distinct()
        .all()
    )
    return [{"id": r.id, "code": r.code, "nom": r.nom} for r in rows]


@function_tool
def list_competencies_for_course(
    cours_id: int,
    status: Literal["developpe", "atteint", "tous"] = "tous",
) -> List[dict]:
    """List competencies linked to `cours_id` with optional status filter."""
    q = (
        db.session.query(
            Competence.id,
            Competence.code,
            Competence.nom,
            ElementCompetenceParCours.status,
        )
        .join(ElementCompetence, ElementCompetence.competence_id == Competence.id)
        .join(
            ElementCompetenceParCours,
            ElementCompetenceParCours.element_competence_id == ElementCompetence.id,
        )
        .filter(ElementCompetenceParCours.cours_id == int(cours_id))
    )
    if status == "developpe":
        q = q.filter(ElementCompetenceParCours.status == "Développé significativement")
    elif status == "atteint":
        q = q.filter(ElementCompetenceParCours.status == "Atteint")
    rows = q.distinct().all()
    return [
        {"id": r.id, "code": r.code, "nom": r.nom, "status": r.status}
        for r in rows
    ]


@function_tool
def get_competence_details(competence_id: int) -> dict:
    """Return full details for a single competency (elements + criteria)."""
    c = db.session.get(Competence, int(competence_id))
    if not c:
        return {"error": f"Aucune compétence id={competence_id}"}
    elements = []
    for el in c.elements:
        criteria = [cr.criteria for cr in el.criteria]
        elements.append({"id": el.id, "nom": el.nom, "criteres": criteria})
    return {
        "id": c.id,
        "code": c.code,
        "nom": c.nom,
        "criteria_de_performance": c.criteria_de_performance,
        "contexte_de_realisation": c.contexte_de_realisation,
        "elements": elements,
    }


@function_tool
def get_plan_cadre_snapshot(cours_id: int) -> dict:
    """Return the current stored plan-cadre (all sections) for a given course.

    Use this to ground improvements on existing content. Returns `None`-like
    dict entries when fields are empty.
    """
    plan: Optional[PlanCadre] = (
        db.session.query(PlanCadre).filter_by(cours_id=int(cours_id)).first()
    )
    if not plan:
        return {"error": f"Aucun plan-cadre pour cours_id={cours_id}"}
    return {
        "plan_cadre_id": plan.id,
        "cours_id": plan.cours_id,
        "fields": {
            "place_intro": plan.place_intro,
            "objectif_terminal": plan.objectif_terminal,
            "structure_intro": plan.structure_intro,
            "structure_activites_theoriques": plan.structure_activites_theoriques,
            "structure_activites_pratiques": plan.structure_activites_pratiques,
            "structure_activites_prevues": plan.structure_activites_prevues,
            "eval_evaluation_sommative": plan.eval_evaluation_sommative,
            "eval_nature_evaluations_sommatives": plan.eval_nature_evaluations_sommatives,
            "eval_evaluation_de_la_langue": plan.eval_evaluation_de_la_langue,
            "eval_evaluation_sommatives_apprentissages": plan.eval_evaluation_sommatives_apprentissages,
        },
        "capacites": [
            {
                "capacite": cap.capacite,
                "description_capacite": cap.description_capacite,
                "ponderation_min": cap.ponderation_min,
                "ponderation_max": cap.ponderation_max,
                "savoirs_necessaires": [sn.texte for sn in cap.savoirs_necessaires],
                "savoirs_faire": [
                    {
                        "texte": sf.texte,
                        "cible": sf.cible,
                        "seuil_reussite": sf.seuil_reussite,
                    }
                    for sf in cap.savoirs_faire
                ],
                "moyens_evaluation": [me.texte for me in cap.moyens_evaluation],
            }
            for cap in plan.capacites
        ],
        "savoirs_etre": [se.texte for se in plan.savoirs_etre],
        "objets_cibles": [
            {"texte": x.texte, "description": x.description} for x in plan.objets_cibles
        ],
        "cours_relies": [
            {"texte": x.texte, "description": x.description} for x in plan.cours_relies
        ],
        "cours_prealables": [
            {"texte": x.texte, "description": x.description} for x in plan.cours_prealables
        ],
        "cours_corequis": [
            {"texte": x.texte, "description": x.description} for x in plan.cours_corequis
        ],
        "competences_developpees": [
            {"texte": x.texte, "description": x.description}
            for x in plan.competences_developpees
        ],
        "competences_certifiees": [
            {"texte": x.texte, "description": x.description}
            for x in plan.competences_certifiees
        ],
    }


@function_tool
def get_section_guidance(section_name: str, cours_id: Optional[int] = None) -> str:
    """Return the stored generation guidance for a section name.

    The text is taken from `GlobalGenerationSettings.text_content` and rendered
    through the Jinja variables of the given course (if provided). Useful so
    the agent can lazily fetch per-section instructions instead of receiving
    them all at once.
    """
    row = (
        db.session.query(GlobalGenerationSettings)
        .filter(GlobalGenerationSettings.section == section_name)
        .first()
    )
    if not row or not (row.text_content or "").strip():
        return ""
    if cours_id:
        data = get_plan_cadre_data(int(cours_id))
        if data:
            try:
                return replace_tags_jinja2(row.text_content, data)
            except Exception:
                logger.exception("replace_tags_jinja2 failed for section %s", section_name)
    return row.text_content or ""


@function_tool
def list_same_programme_courses(cours_id: int, session: Optional[int] = None) -> List[dict]:
    """Return other courses that share at least one programme with `cours_id`.

    Useful to discover sibling courses whose plan-cadre or plan-de-cours can
    then be fetched for alignment/consistency. Optionally filter by session.
    """
    cours = db.session.get(Cours, int(cours_id))
    if not cours:
        return []
    programme_ids = [p.id for p in cours.programmes]
    if not programme_ids:
        return []
    results: dict = {}
    for pid in programme_ids:
        prog = db.session.get(Programme, pid)
        if not prog:
            continue
        for assoc in getattr(prog, "cours_assocs", []) or []:
            if assoc.cours_id == int(cours_id):
                continue
            if session is not None and assoc.session != session:
                continue
            c = assoc.cours
            if not c:
                continue
            if c.id in results:
                continue
            results[c.id] = {
                "id": c.id,
                "code": c.code,
                "nom": c.nom,
                "session": assoc.session,
                "programme_id": prog.id,
                "programme_nom": prog.nom,
                "has_plan_cadre": bool(getattr(c, "plan_cadre", None)),
                "plan_de_cours_count": len(getattr(c, "plans_de_cours", []) or []),
            }
    return list(results.values())


@function_tool
def list_plans_de_cours_for_course(cours_id: int) -> List[dict]:
    """List every plan de cours iteration stored for a given course.

    Use this to discover which sessions have been published and then fetch
    a specific one with `get_plan_de_cours_snapshot_by_id`.
    """
    rows = (
        db.session.query(PlanDeCours)
        .filter(PlanDeCours.cours_id == int(cours_id))
        .order_by(PlanDeCours.id.desc())
        .all()
    )
    return [
        {
            "plan_id": p.id,
            "cours_id": p.cours_id,
            "session": p.session,
            "campus": p.campus,
            "nom_enseignant": p.nom_enseignant,
        }
        for p in rows
    ]


def _serialize_plan_de_cours(plan: PlanDeCours) -> dict:
    def _cap_name(cap_id):
        if not cap_id:
            return None
        obj = db.session.get(PlanCadreCapacites, cap_id)
        return obj.capacite if obj else None

    return {
        "plan_id": plan.id,
        "cours_id": plan.cours_id,
        "session": plan.session,
        "campus": plan.campus,
        "nom_enseignant": plan.nom_enseignant,
        "fields": {
            "presentation_du_cours": plan.presentation_du_cours,
            "objectif_terminal_du_cours": plan.objectif_terminal_du_cours,
            "organisation_et_methodes": plan.organisation_et_methodes,
            "accomodement": plan.accomodement,
            "evaluation_formative_apprentissages": plan.evaluation_formative_apprentissages,
            "evaluation_expression_francais": plan.evaluation_expression_francais,
            "seuil_reussite": plan.seuil_reussite,
            "materiel": plan.materiel,
        },
        "calendriers": [
            {
                "semaine": c.semaine,
                "sujet": c.sujet,
                "activites": c.activites,
                "travaux_hors_classe": c.travaux_hors_classe,
                "evaluations": c.evaluations,
            }
            for c in plan.calendriers
        ],
        "evaluations": [
            {
                "titre_evaluation": e.titre_evaluation,
                "description": e.description,
                "semaine": e.semaine,
                "capacites": [
                    {"capacite": _cap_name(ce.capacite_id), "ponderation": ce.ponderation}
                    for ce in e.capacites
                ],
            }
            for e in plan.evaluations
        ],
    }


@function_tool
def get_plan_de_cours_snapshot_by_id(plan_id: int) -> dict:
    """Return the full plan-de-cours (all fields + calendar + evaluations) by id."""
    plan = db.session.get(PlanDeCours, int(plan_id))
    if not plan:
        return {"error": f"Aucun plan de cours id={plan_id}"}
    return _serialize_plan_de_cours(plan)


@function_tool
def get_plan_de_cours_snapshot_by_cours(cours_id: int, session: Optional[str] = None) -> dict:
    """Return the plan-de-cours for a given course, optionally for a given session.

    If `session` is omitted, returns the most recent iteration available.
    """
    q = db.session.query(PlanDeCours).filter(PlanDeCours.cours_id == int(cours_id))
    if session:
        q = q.filter(PlanDeCours.session == str(session))
    plan = q.order_by(PlanDeCours.id.desc()).first()
    if not plan:
        return {"error": f"Aucun plan de cours pour cours_id={cours_id} session={session}"}
    return _serialize_plan_de_cours(plan)


COMMON_TOOLS = [
    get_course_details,
    search_courses,
    list_programme_courses,
    list_same_programme_courses,
    list_related_courses,
    list_competencies_for_course,
    get_competence_details,
    get_plan_cadre_snapshot,
    list_plans_de_cours_for_course,
    get_plan_de_cours_snapshot_by_id,
    get_plan_de_cours_snapshot_by_cours,
    get_section_guidance,
]

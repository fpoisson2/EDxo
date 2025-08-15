"""MCP server exposing programme and course resources."""

from fastmcp import FastMCP

from src.app.models import (
    Programme,
    Cours,
    Competence,
    PlanCadre,
    PlanDeCours,
)

mcp = FastMCP(name="EDxoMCP")


def programmes():
    """Retourne la liste des programmes."""
    return [{"id": p.id, "nom": p.nom} for p in Programme.query.all()]


def programme_courses(programme_id: int):
    """Cours associés à un programme."""
    programme = Programme.query.get(programme_id)
    if not programme:
        raise ValueError("Programme introuvable")
    return [{"id": c.id, "code": c.code, "nom": c.nom} for c in programme.cours]


def programme_competences(programme_id: int):
    """Compétences ministérielles d'un programme."""
    comps = Competence.query.filter_by(programme_id=programme_id).order_by(Competence.code).all()
    return [{"id": c.id, "code": c.code, "nom": c.nom} for c in comps]


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


def cours():
    """Liste de tous les cours."""
    return [{"id": c.id, "code": c.code, "nom": c.nom} for c in Cours.query.all()]


def cours_details(cours_id: int):
    """Informations sur un cours."""
    cours_obj = Cours.query.get(cours_id)
    if not cours_obj:
        raise ValueError("Cours introuvable")
    return {"id": cours_obj.id, "code": cours_obj.code, "nom": cours_obj.nom}


def cours_plan_cadre(cours_id: int):
    """Plan cadre lié à un cours."""
    plan = PlanCadre.query.filter_by(cours_id=cours_id).first()
    return plan.to_dict() if plan else {}


def cours_plans_de_cours(cours_id: int):
    """Plans de cours associés à un cours."""
    plans = PlanDeCours.query.filter_by(cours_id=cours_id).all()
    return [p.to_dict() for p in plans]


def plan_cadre_section(plan_id: int, section: str):
    """Récupère une section spécifique d'un plan cadre."""
    plan = PlanCadre.query.get(plan_id)
    if not plan or not hasattr(plan, section):
        raise ValueError("Section inconnue")
    return {section: getattr(plan, section)}


# Enregistrement des ressources auprès du serveur MCP
mcp.resource("api://programmes")(programmes)
mcp.resource("api://programmes/{programme_id}/cours")(programme_courses)
mcp.resource("api://programmes/{programme_id}/competences")(programme_competences)
mcp.resource("api://competences/{competence_id}")(competence_details)
mcp.resource("api://cours")(cours)
mcp.resource("api://cours/{cours_id}")(cours_details)
mcp.resource("api://cours/{cours_id}/plan_cadre")(cours_plan_cadre)
mcp.resource("api://cours/{cours_id}/plans_de_cours")(cours_plans_de_cours)
mcp.resource("api://plan_cadre/{plan_id}/section/{section}")(plan_cadre_section)

"""Définition des outils et de leurs gestionnaires."""
from typing import Any, Dict, List

def get_plan_de_cours_function() -> Dict[str, Any]:
    return {"type": "function", "name": "get_plan_de_cours", "description": "Récupère un plan de cours."}

def get_plan_cadre_function() -> Dict[str, Any]:
    return {"type": "function", "name": "get_plan_cadre", "description": "Récupère un plan-cadre."}

def get_multiple_plan_cadre_function() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "get_multiple_plan_cadre",
        "description": "Récupère plusieurs plans-cadres.",
    }

def list_all_plan_cadre_function() -> Dict[str, Any]:
    return {"type": "function", "name": "list_all_plan_cadre", "description": "Liste tous les plans-cadres."}

def list_all_plan_de_cours_function() -> Dict[str, Any]:
    return {"type": "function", "name": "list_all_plan_de_cours", "description": "Liste tous les plans de cours."}

def handle_get_plan_de_cours(params: Dict[str, Any]) -> Dict[str, Any]:
    return {"code": params.get("code")}

def handle_get_plan_cadre(params: Dict[str, Any]) -> Dict[str, Any]:
    return {"nom": params.get("nom"), "code": params.get("code")}

def handle_get_multiple_plan_cadre(params: Dict[str, Any]) -> List[str]:
    return params.get("codes", [])

def handle_list_all_plan_de_cours() -> List[Any]:
    return []

def handle_list_all_plan_cadre() -> List[Any]:
    return []

TOOL_HANDLERS = {
    "get_plan_de_cours": handle_get_plan_de_cours,
    "get_plan_cadre": handle_get_plan_cadre,
    "get_multiple_plan_cadre": handle_get_multiple_plan_cadre,
    "list_all_plan_de_cours": handle_list_all_plan_de_cours,
    "list_all_plan_cadre": handle_list_all_plan_cadre,
}

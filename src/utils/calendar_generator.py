from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CalendarEntry(BaseModel):
    """Représente une ligne du calendrier généré."""

    semaine: Optional[int] = None
    sujet: Optional[str] = None
    activites: Optional[str] = None
    travaux_hors_classe: Optional[str] = None
    evaluations: Optional[str] = None


class CalendarResponse(BaseModel):
    """Structure attendue de la réponse de l'API."""

    calendriers: List[CalendarEntry] = Field(default_factory=list)


def build_calendar_prompt(plan_cadre, session: str) -> str:
    """Construit le prompt d'appel à l'API OpenAI pour générer un calendrier.

    Le prompt s'appuie sur diverses sections du plan cadre ainsi que sur la
    session ciblée afin d'obtenir un calendrier hebdomadaire détaillé.
    """

    sections = [
        f"Objectif terminal: {plan_cadre.objectif_terminal or ''}",
        f"Structure des activités théoriques: {plan_cadre.structure_activites_theoriques or ''}",
        f"Structure des activités pratiques: {plan_cadre.structure_activites_pratiques or ''}",
        f"Activités prévues: {plan_cadre.structure_activites_prevues or ''}",
        f"Évaluations sommatives: {plan_cadre.eval_evaluation_sommative or ''}",
    ]

    prompt = (
        "Tu es un assistant pédagogique. Génère un calendrier hebdomadaire "
        "des activités pour la session {session}.\n"
        "Base-toi sur les informations du plan-cadre ci-dessous pour proposer "
        "un déroulement cohérent du cours.\n"
        "Plan-cadre:\n{sections}\n\n"
        "Le résultat doit être un JSON avec une liste 'calendriers'. Chaque "
        "élément comporte les champs: semaine (int), sujet, activites, "
        "travaux_hors_classe et evaluations."
    ).format(session=session, sections="\n".join(sections))

    return prompt

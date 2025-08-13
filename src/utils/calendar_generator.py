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
    session ciblée afin d'obtenir un calendrier hebdomadaire détaillé. Les
    informations incluent les données du cours et les capacités avec leurs
    composantes, jugées essentielles pour un découpage pertinent du calendrier.
    """

    sections = []

    # Informations générales sur le cours
    if getattr(plan_cadre, "cours", None):
        sections.append(
            f"Cours: {plan_cadre.cours.code or ''} - {plan_cadre.cours.nom or ''}"
        )

    # Champs principaux du plan cadre
    sections.extend(
        [
            f"Objectif terminal: {plan_cadre.objectif_terminal or ''}",
            f"Structure des activités théoriques: {plan_cadre.structure_activites_theoriques or ''}",
            f"Structure des activités pratiques: {plan_cadre.structure_activites_pratiques or ''}",
            f"Activités prévues: {plan_cadre.structure_activites_prevues or ''}",
            f"Évaluations sommatives: {plan_cadre.eval_evaluation_sommative or ''}",
        ]
    )

    # Capacités détaillées
    cap_lines: List[str] = []
    for capacite in getattr(plan_cadre, "capacites", []) or []:
        savoirs_necessaires = ", ".join(
            sn.texte for sn in getattr(capacite, "savoirs_necessaires", []) if sn.texte
        )
        savoirs_faire = ", ".join(
            sf.texte for sf in getattr(capacite, "savoirs_faire", []) if sf.texte
        )
        moyens_eval = ", ".join(
            me.texte for me in getattr(capacite, "moyens_evaluation", []) if me.texte
        )

        cap_lines.append(
            (
                f"Capacité: {capacite.capacite or ''}. {capacite.description_capacite or ''}. "
                f"Pondération: {capacite.ponderation_min or ''}-{capacite.ponderation_max or ''}. "
                f"Savoirs nécessaires: {savoirs_necessaires}. "
                f"Savoirs faire: {savoirs_faire}. "
                f"Moyens d'évaluation: {moyens_eval}."
            )
        )

    if cap_lines:
        sections.append("Capacités:\n" + "\n".join(cap_lines))

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

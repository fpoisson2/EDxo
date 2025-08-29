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


DEFAULT_CALENDAR_TEMPLATE = (
    "Session: {session}\n"
    "Plan-cadre:\n{sections}\n"
)


def build_calendar_prompt(
    plan_cadre, session: str, prompt_template: Optional[str] = None
) -> str:
    """Construit le prompt d'appel à l'API OpenAI pour générer un calendrier.

    Le prompt assemble les informations pertinentes du plan cadre ainsi que la
    session visée. Un modèle de prompt peut être fourni; sinon, un modèle par
    défaut est utilisé.
    """

    sections: List[str] = []

    # Informations générales sur le cours
    if getattr(plan_cadre, "cours", None):
        sections.append(
            f"Cours: {plan_cadre.cours.code or ''} - {plan_cadre.cours.nom or ''}"
        )

    # Champs principaux du plan cadre
    sections.extend(
        [
            f"Place du cours: {plan_cadre.place_intro or ''}",
            f"Objectif terminal: {plan_cadre.objectif_terminal or ''}",
            f"Structure du cours: {plan_cadre.structure_intro or ''}",
            f"Activités théoriques: {plan_cadre.structure_activites_theoriques or ''}",
            f"Activités pratiques: {plan_cadre.structure_activites_pratiques or ''}",
            f"Activités prévues: {plan_cadre.structure_activites_prevues or ''}",
            f"Évaluation sommative: {plan_cadre.eval_evaluation_sommative or ''}",
            f"Nature des évaluations sommatives: {plan_cadre.eval_nature_evaluations_sommatives or ''}",
            f"Évaluation de la langue: {plan_cadre.eval_evaluation_de_la_langue or ''}",
            f"Évaluation sommative des apprentissages: {plan_cadre.eval_evaluation_sommatives_apprentissages or ''}",
            f"Informations additionnelles: {plan_cadre.additional_info or ''}",
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
            f"Capacité: {capacite.capacite or ''}. {capacite.description_capacite or ''}. "
            f"Pondération: {capacite.ponderation_min or ''}-{capacite.ponderation_max or ''}. "
            f"Savoirs nécessaires: {savoirs_necessaires}. "
            f"Savoirs faire: {savoirs_faire}. "
            f"Moyens d'évaluation: {moyens_eval}."
        )

    if cap_lines:
        sections.append("Capacités:\n" + "\n".join(cap_lines))

    template = prompt_template or DEFAULT_CALENDAR_TEMPLATE
    sections_str = "\n".join(sections)
    return template.format(session=session, sections=sections_str)

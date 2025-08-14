import logging
from typing import List, Optional

from celery import shared_task
from openai import OpenAI
from pydantic import BaseModel, Field

from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.app.models import (
    PlanDeCours, PlanDeCoursCalendrier, User
)

logger = logging.getLogger(__name__)


class CalendarEntry(BaseModel):
    semaine: Optional[int] = None
    sujet: Optional[str] = None
    activites: Optional[str] = None
    travaux_hors_classe: Optional[str] = None
    evaluations: Optional[str] = None


class BulkPlanDeCoursResponse(BaseModel):
    presentation_du_cours: Optional[str] = None
    objectif_terminal_du_cours: Optional[str] = None
    organisation_et_methodes: Optional[str] = None
    accomodement: Optional[str] = None
    evaluation_formative_apprentissages: Optional[str] = None
    evaluation_expression_francais: Optional[str] = None
    materiel: Optional[str] = None
    calendriers: List[CalendarEntry] = Field(default_factory=list)


def _extract_first_parsed(response):
    try:
        outputs = getattr(response, 'output', None) or []
        for item in outputs:
            contents = getattr(item, 'content', None) or []
            for c in contents:
                parsed = getattr(c, 'parsed', None)
                if parsed is not None:
                    return parsed
    except Exception:
        pass
    return None


@shared_task(bind=True, name='src.app.tasks.generation_plan_de_cours.generate_plan_de_cours_all_task')
def generate_plan_de_cours_all_task(self, plan_de_cours_id: int, prompt: str, ai_model: str, user_id: int):
    """Celery task qui génère toutes les sections du plan de cours et met à jour la BD."""
    try:
        plan = PlanDeCours.query.get(plan_de_cours_id)
        if not plan:
            return {"status": "error", "message": "Plan de cours non trouvé."}

        user = db.session.query(User).with_for_update().get(user_id)
        if not user:
            return {"status": "error", "message": "Utilisateur introuvable."}
        if not user.openai_key:
            return {"status": "error", "message": "Clé OpenAI non configurée."}
        if user.credits is None:
            user.credits = 0.0
            db.session.commit()
        if user.credits <= 0:
            return {"status": "error", "message": "Crédits insuffisants."}

        self.update_state(state='PROGRESS', meta={'message': 'Appel au modèle IA en cours...'})

        client = OpenAI(api_key=user.openai_key)
        response = client.responses.parse(
            model=ai_model,
            input=prompt,
            text_format=BulkPlanDeCoursResponse,
        )

        usage_prompt = response.usage.input_tokens if hasattr(response, 'usage') else 0
        usage_completion = response.usage.output_tokens if hasattr(response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)

        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}

        user.credits -= cost

        parsed = _extract_first_parsed(response)
        if parsed is None:
            return {"status": "error", "message": "Aucune donnée renvoyée par le modèle."}

        # Mettre à jour les champs
        plan.presentation_du_cours = parsed.presentation_du_cours or plan.presentation_du_cours
        plan.objectif_terminal_du_cours = parsed.objectif_terminal_du_cours or plan.objectif_terminal_du_cours
        plan.organisation_et_methodes = parsed.organisation_et_methodes or plan.organisation_et_methodes
        plan.accomodement = parsed.accomodement or plan.accomodement
        plan.evaluation_formative_apprentissages = parsed.evaluation_formative_apprentissages or plan.evaluation_formative_apprentissages
        plan.evaluation_expression_francais = parsed.evaluation_expression_francais or plan.evaluation_expression_francais
        plan.materiel = parsed.materiel or plan.materiel

        # Calendrier
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

        return {
            "status": "success",
            "fields": {
                'presentation_du_cours': plan.presentation_du_cours,
                'objectif_terminal_du_cours': plan.objectif_terminal_du_cours,
                'organisation_et_methodes': plan.organisation_et_methodes,
                'accomodement': plan.accomodement,
                'evaluation_formative_apprentissages': plan.evaluation_formative_apprentissages,
                'evaluation_expression_francais': plan.evaluation_expression_francais,
                'materiel': plan.materiel,
            },
            "calendriers": [
                {
                    'semaine': c.semaine,
                    'sujet': c.sujet,
                    'activites': c.activites,
                    'travaux_hors_classe': c.travaux_hors_classe,
                    'evaluations': c.evaluations,
                } for c in plan.calendriers
            ]
        }

    except Exception as e:
        logger.exception("Erreur dans la tâche generate_plan_de_cours_all_task")
        return {"status": "error", "message": str(e)}


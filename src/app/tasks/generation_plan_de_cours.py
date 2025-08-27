import logging
from typing import List, Optional

from celery import shared_task
from openai import OpenAI
from pydantic import BaseModel, Field

from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.app.models import (
    PlanDeCours, PlanDeCoursCalendrier, User, PlanDeCoursPromptSettings, Cours, PlanCadre,
    PlanDeCoursEvaluations, PlanDeCoursEvaluationsCapacites, PlanCadreCapacites
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
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
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
        request_kwargs = dict(
            model=ai_model,
            input=prompt,
            text_format=BulkPlanDeCoursResponse,
            reasoning={"summary": "auto"},
        )
        streamed_text = ""
        reasoning_summary_text = ""
        final_response = None
        try:
            with client.responses.stream(**request_kwargs) as stream:
                for event in stream:
                    etype = getattr(event, 'type', '') or ''
                    if etype.endswith('response.output_text.delta') or etype == 'response.output_text.delta':
                        delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                        if delta:
                            streamed_text += delta
                            try:
                                self.update_state(state='PROGRESS', meta={'stream_chunk': delta, 'stream_buffer': streamed_text})
                            except Exception:
                                pass
                    elif etype.endswith('response.reasoning_summary_text.delta') or etype == 'response.reasoning_summary_text.delta':
                        rs_delta = getattr(event, 'delta', '') or ''
                        if rs_delta:
                            reasoning_summary_text += rs_delta
                            try:
                                self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary_text})
                            except Exception:
                                pass
                final_response = stream.get_final_response()
        except Exception:
            final_response = client.responses.parse(**request_kwargs)

        usage_prompt = final_response.usage.input_tokens if hasattr(final_response, 'usage') else 0
        usage_completion = final_response.usage.output_tokens if hasattr(final_response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)

        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}

        user.credits -= cost

        parsed = _extract_first_parsed(final_response)
        if parsed is None:
            return {"status": "error", "message": "Aucune donnée renvoyée par le modèle."}

        # Snapshot avant modification pour comparaison
        old_fields = {
            'presentation_du_cours': plan.presentation_du_cours,
            'objectif_terminal_du_cours': plan.objectif_terminal_du_cours,
            'organisation_et_methodes': plan.organisation_et_methodes,
            'accomodement': plan.accomodement,
            'evaluation_formative_apprentissages': plan.evaluation_formative_apprentissages,
            'evaluation_expression_francais': plan.evaluation_expression_francais,
            'materiel': plan.materiel,
        }
        old_calendriers = [
            {
                'semaine': c.semaine,
                'sujet': c.sujet,
                'activites': c.activites,
                'travaux_hors_classe': c.travaux_hors_classe,
                'evaluations': c.evaluations,
            } for c in plan.calendriers
        ]

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
            ],
            "old_fields": old_fields,
            "old_calendriers": old_calendriers,
            "cours_id": plan.cours_id,
            "plan_id": plan.id,
            "session": plan.session,
            "validation_url": f"/plan_de_cours/review/{plan.id}?task_id={self.request.id}",
            "reasoning_summary": reasoning_summary_text,
        }

    except Exception as e:
        logger.exception("Erreur dans la tâche generate_plan_de_cours_all_task")
        return {"status": "error", "message": str(e)}


class SingleFieldResponse(BaseModel):
    champ_description: Optional[str] = None


@shared_task(bind=True, name='src.app.tasks.generation_plan_de_cours.generate_plan_de_cours_field_task')
def generate_plan_de_cours_field_task(self, plan_de_cours_id: int, field_name: str, additional_info: Optional[str], user_id: int):
    """Génère (ou améliore) un champ individuel du plan de cours via Celery.

    Utilise les PlanDeCoursPromptSettings pour construire le prompt.
    Met à jour la base et retourne un payload compact pour l'UI unifiée.
    """
    try:
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
        if not plan:
            return {"status": "error", "message": "Plan de cours non trouvé."}

        # Validation champ supporté
        allowed_fields = {
            'presentation_du_cours',
            'objectif_terminal_du_cours',
            'organisation_et_methodes',
            'accomodement',
            'evaluation_formative_apprentissages',
            'evaluation_expression_francais',
            'materiel',
        }
        if field_name not in allowed_fields:
            return {"status": "error", "message": f"Champ non supporté: {field_name}"}

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

        # Prompt settings pour le champ
        prompt_settings = PlanDeCoursPromptSettings.query.filter_by(field_name=field_name).first()
        if not prompt_settings:
            return {"status": "error", "message": "Configuration de prompt introuvable pour ce champ."}
        ai_model = prompt_settings.ai_model or 'gpt-5'

        # Contexte issu du plan-cadre/cours (similaire à route sync generate_content)
        cours: Cours = plan.cours
        plan_cadre: PlanCadre = cours.plan_cadre if cours else None
        if not cours or not plan_cadre:
            return {"status": "error", "message": "Contexte cours/plan-cadre indisponible."}

        ctx = {
            'additional_info': additional_info or '',
            'cours_id': cours.id,
            'session': plan.session,
            'cours_nom': cours.nom,
            'cours_code': cours.code,
            'place_intro': plan_cadre.place_intro,
            'objectif_terminal': plan_cadre.objectif_terminal,
            'structure_intro': plan_cadre.structure_intro,
            'structure_activites_theoriques': plan_cadre.structure_activites_theoriques,
            'structure_activites_pratiques': plan_cadre.structure_activites_pratiques,
            'structure_activites_prevues': plan_cadre.structure_activites_prevues,
            'eval_evaluation_sommative': plan_cadre.eval_evaluation_sommative,
            'eval_nature_evaluations_sommatives': plan_cadre.eval_nature_evaluations_sommatives,
            'eval_evaluation_de_la_langue': plan_cadre.eval_evaluation_de_la_langue,
            'eval_evaluation_sommatives_apprentissages': plan_cadre.eval_evaluation_sommatives_apprentissages,
            'capacites': [c.capacite for c in getattr(plan_cadre, 'capacites', [])],
            'savoirs_etre': [x.texte for x in getattr(plan_cadre, 'savoirs_etre', [])],
            'objets_cibles': [x.texte for x in getattr(plan_cadre, 'objets_cibles', [])],
            'cours_relies': [x.texte for x in getattr(plan_cadre, 'cours_relies', [])],
            'cours_prealables': [x.texte for x in getattr(plan_cadre, 'cours_prealables', [])],
            'cours_corequis': [x.texte for x in getattr(plan_cadre, 'cours_corequis', [])],
            'competences_certifiees': [x.texte for x in getattr(plan_cadre, 'competences_certifiees', [])],
            'competences_developpees': [x.texte for x in getattr(plan_cadre, 'competences_developpees', [])],
        }

        try:
            prompt = (prompt_settings.prompt_template or '').format(**ctx)
        except Exception as e:
            return {"status": "error", "message": f"Erreur dans le template du prompt: {e}"}

        self.update_state(state='PROGRESS', meta={'message': f"Génération de '{field_name}' en cours..."})

        client = OpenAI(api_key=user.openai_key)
        request_kwargs = dict(
            model=ai_model,
            input=prompt,
            text_format=SingleFieldResponse,
            reasoning={"summary": "auto"},
        )
        streamed_text = ""
        reasoning_summary_text = ""
        final_response = None
        try:
            with client.responses.stream(**request_kwargs) as stream:
                for event in stream:
                    etype = getattr(event, 'type', '') or ''
                    if etype.endswith('response.output_text.delta') or etype == 'response.output_text.delta':
                        delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                        if delta:
                            streamed_text += delta
                            try:
                                self.update_state(state='PROGRESS', meta={'stream_chunk': delta, 'stream_buffer': streamed_text})
                            except Exception:
                                pass
                    elif etype.endswith('response.reasoning_summary_text.delta') or etype == 'response.reasoning_summary_text.delta':
                        rs_delta = getattr(event, 'delta', '') or ''
                        if rs_delta:
                            reasoning_summary_text += rs_delta
                            try:
                                self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary_text})
                            except Exception:
                                pass
                final_response = stream.get_final_response()
        except Exception:
            final_response = client.responses.parse(**request_kwargs)

        usage_prompt = final_response.usage.input_tokens if hasattr(final_response, 'usage') else 0
        usage_completion = final_response.usage.output_tokens if hasattr(final_response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)
        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        # Récupération du champ généré
        parsed = _extract_first_parsed(final_response)
        value = None
        try:
            value = parsed and getattr(parsed, 'champ_description', None)
        except Exception:
            value = None
        if not value:
            return {"status": "error", "message": "Aucune description générée."}

        # Mise à jour du plan
        setattr(plan, field_name, value)
        db.session.commit()

        return {
            'status': 'success',
            'field_name': field_name,
            'value': value,
            'plan_id': plan.id,
            'cours_id': plan.cours_id,
            'session': plan.session,
            'plan_de_cours_url': f"/cours/{plan.cours_id}/plan_de_cours/{plan.session}/",
            'reasoning_summary': reasoning_summary_text,
        }

    except Exception as e:
        logger.exception("Erreur dans la tâche generate_plan_de_cours_field_task")
        return {"status": "error", "message": str(e)}


class CalendarOnlyResponse(BaseModel):
    calendriers: List[CalendarEntry] = Field(default_factory=list)


@shared_task(bind=True, name='src.app.tasks.generation_plan_de_cours.generate_plan_de_cours_calendar_task')
def generate_plan_de_cours_calendar_task(self, plan_de_cours_id: int, additional_info: Optional[str], user_id: int):
    """Génère uniquement le calendrier des activités du plan de cours."""
    try:
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
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

        # Contexte / prompt
        cours: Cours = plan.cours
        plan_cadre: PlanCadre = cours.plan_cadre if cours else None
        if not cours or not plan_cadre:
            return {"status": "error", "message": "Contexte cours/plan-cadre indisponible."}
        from src.utils.calendar_generator import build_calendar_prompt
        prompt = build_calendar_prompt(plan_cadre, session=plan.session)
        if additional_info:
            prompt = prompt + "\n\nPrécisions: " + str(additional_info)

        # Choix du modèle (reuse 'all' if set)
        ps = PlanDeCoursPromptSettings.query.filter_by(field_name='all').first()
        ai_model = (ps.ai_model if ps and ps.ai_model else None) or 'gpt-5'

        self.update_state(state='PROGRESS', meta={'message': 'Génération du calendrier…'})

        client = OpenAI(api_key=user.openai_key)
        request_kwargs = dict(
            model=ai_model,
            input=prompt,
            text_format=CalendarOnlyResponse,
            reasoning={"summary": "auto"},
        )
        streamed_text = ""
        reasoning_summary_text = ""
        final_response = None
        try:
            with client.responses.stream(**request_kwargs) as stream:
                for event in stream:
                    etype = getattr(event, 'type', '') or ''
                    if etype.endswith('response.output_text.delta') or etype == 'response.output_text.delta':
                        delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                        if delta:
                            streamed_text += delta
                            try:
                                self.update_state(state='PROGRESS', meta={'stream_chunk': delta, 'stream_buffer': streamed_text})
                            except Exception:
                                pass
                    elif etype.endswith('response.reasoning_summary_text.delta') or etype == 'response.reasoning_summary_text.delta':
                        rs_delta = getattr(event, 'delta', '') or ''
                        if rs_delta:
                            reasoning_summary_text += rs_delta
                            try:
                                self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary_text})
                            except Exception:
                                pass
                final_response = stream.get_final_response()
        except Exception:
            final_response = client.responses.parse(**request_kwargs)

        usage_prompt = final_response.usage.input_tokens if hasattr(final_response, 'usage') else 0
        usage_completion = final_response.usage.output_tokens if hasattr(final_response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)
        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        parsed = _extract_first_parsed(final_response)
        entries: List[CalendarEntry] = (parsed.calendriers if parsed else []) or []
        if not entries:
            return {"status": "error", "message": "Aucune entrée générée pour le calendrier."}

        # Mise à jour DB (remplace le calendrier courant)
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
            'status': 'success',
            'plan_id': plan.id,
            'cours_id': plan.cours_id,
            'session': plan.session,
            'calendriers': [
                {
                    'semaine': c.semaine,
                    'sujet': c.sujet,
                    'activites': c.activites,
                    'travaux_hors_classe': c.travaux_hors_classe,
                    'evaluations': c.evaluations,
                } for c in plan.calendriers
            ],
            'plan_de_cours_url': f"/cours/{plan.cours_id}/plan_de_cours/{plan.session}/",
            'reasoning_summary': reasoning_summary_text,
        }
    except Exception as e:
        logger.exception("Erreur dans la tâche generate_plan_de_cours_calendar_task")
        return {"status": "error", "message": str(e)}


class EvaluationCapaciteEntry(BaseModel):
    capacite: Optional[str] = None
    ponderation: Optional[str] = None


class EvaluationEntry(BaseModel):
    titre: Optional[str] = None
    description: Optional[str] = None
    semaine: Optional[int] = None
    capacites: List[EvaluationCapaciteEntry] = Field(default_factory=list)


class EvaluationsResponse(BaseModel):
    evaluations: List[EvaluationEntry] = Field(default_factory=list)


@shared_task(bind=True, name='src.app.tasks.generation_plan_de_cours.generate_plan_de_cours_evaluations_task')
def generate_plan_de_cours_evaluations_task(self, plan_de_cours_id: int, additional_info: Optional[str], user_id: int):
    """Génère la liste d'évaluations (titre, semaine, description, capacités + pondérations)."""
    try:
        plan = db.session.get(PlanDeCours, plan_de_cours_id)
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

        cours: Cours = plan.cours
        plan_cadre: PlanCadre = cours.plan_cadre if cours else None
        if not cours or not plan_cadre:
            return {"status": "error", "message": "Contexte cours/plan-cadre indisponible."}

        # Construire prompt pour évaluations
        cap_lines = ", ".join([c.capacite for c in getattr(plan_cadre, 'capacites', []) or []])
        sections = [
            f"Cours: {cours.code or ''} - {cours.nom or ''}",
            f"Objectif terminal: {plan_cadre.objectif_terminal or ''}",
            f"Capacités: {cap_lines}",
        ]
        prompt = (
            "Tu es un assistant pédagogique. Propose une liste d'évaluations pour le plan de cours "
            f"de la session {plan.session}. Retourne un JSON sous la forme:\n"
            "{ 'evaluations': [ { 'titre': str, 'semaine': int, 'description': str, 'capacites': [ { 'capacite': str, 'ponderation': str } ] } ] }\n"
            "Le champ 'capacite' doit correspondre au libellé exact d'une capacité du plan-cadre.\n\n"
            "Contexte:\n" + "\n".join(sections)
        )
        if additional_info:
            prompt += "\n\nContraintes/Précisions: " + str(additional_info)

        ps = PlanDeCoursPromptSettings.query.filter_by(field_name='all').first()
        ai_model = (ps.ai_model if ps and ps.ai_model else None) or 'gpt-5'

        self.update_state(state='PROGRESS', meta={'message': 'Génération des évaluations…'})
        client = OpenAI(api_key=user.openai_key)
        request_kwargs = dict(
            model=ai_model,
            input=prompt,
            text_format=EvaluationsResponse,
            reasoning={"summary": "auto"},
        )
        streamed_text = ""
        reasoning_summary_text = ""
        final_response = None
        try:
            with client.responses.stream(**request_kwargs) as stream:
                for event in stream:
                    etype = getattr(event, 'type', '') or ''
                    if etype.endswith('response.output_text.delta') or etype == 'response.output_text.delta':
                        delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                        if delta:
                            streamed_text += delta
                            try:
                                self.update_state(state='PROGRESS', meta={'stream_chunk': delta, 'stream_buffer': streamed_text})
                            except Exception:
                                pass
                    elif etype.endswith('response.reasoning_summary_text.delta') or etype == 'response.reasoning_summary_text.delta':
                        rs_delta = getattr(event, 'delta', '') or ''
                        if rs_delta:
                            reasoning_summary_text += rs_delta
                            try:
                                self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary_text})
                            except Exception:
                                pass
                final_response = stream.get_final_response()
        except Exception:
            final_response = client.responses.parse(**request_kwargs)

        usage_prompt = final_response.usage.input_tokens if hasattr(final_response, 'usage') else 0
        usage_completion = final_response.usage.output_tokens if hasattr(final_response, 'usage') else 0
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)
        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        parsed = _extract_first_parsed(final_response)
        evals: List[EvaluationEntry] = (parsed.evaluations if parsed else []) or []
        if not evals:
            return {"status": "error", "message": "Aucune évaluation générée."}

        # Remplacer la liste d'évaluations existantes
        for e in plan.evaluations:
            # Capacités supprimées via cascade
            db.session.delete(e)

        # Map libellé capacité -> id
        cap_by_name = {}
        try:
            for c in getattr(plan_cadre, 'capacites', []) or []:
                if c.capacite:
                    cap_by_name[c.capacite.strip()] = c.id
        except Exception:
            pass

        created = []
        for ev in evals:
            row = PlanDeCoursEvaluations(
                plan_de_cours_id=plan.id,
                titre_evaluation=ev.titre,
                description=ev.description,
                semaine=ev.semaine,
            )
            db.session.add(row)
            db.session.flush()
            # Capacités évaluées
            for ce in (ev.capacites or []):
                cap_id = None
                if ce.capacite:
                    cap_id = cap_by_name.get(ce.capacite.strip())
                db.session.add(PlanDeCoursEvaluationsCapacites(
                    evaluation_id=row.id,
                    capacite_id=cap_id,
                    ponderation=ce.ponderation,
                ))
            created.append(row)

        db.session.commit()

        # Serialize back
        result_evals = []
        for e in plan.evaluations:
            result_evals.append({
                'id': e.id,
                'titre': e.titre_evaluation,
                'description': e.description,
                'semaine': e.semaine,
                'capacites': [
                    {
                        'capacite_id': c.capacite_id,
                        'capacite': (db.session.get(PlanCadreCapacites, c.capacite_id).capacite if c.capacite_id else None),
                        'ponderation': c.ponderation,
                    } for c in e.capacites
                ]
            })

        return {
            'status': 'success',
            'plan_id': plan.id,
            'cours_id': plan.cours_id,
            'session': plan.session,
            'evaluations': result_evals,
            'plan_de_cours_url': f"/cours/{plan.cours_id}/plan_de_cours/{plan.session}/",
            'reasoning_summary': reasoning_summary_text,
        }
    except Exception as e:
        logger.exception("Erreur dans la tâche generate_plan_de_cours_evaluations_task")
        return {"status": "error", "message": str(e)}

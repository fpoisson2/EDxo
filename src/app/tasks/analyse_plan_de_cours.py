import json
from typing import Optional

from celery import shared_task
from openai import OpenAI
from pydantic import BaseModel, ValidationError, ConfigDict

from ..models import db, PlanDeCours, User, AnalysePlanCoursPrompt, SectionAISettings
from ...utils.logging_config import get_logger
from ...utils.openai_pricing import calculate_call_cost

logger = get_logger(__name__)


def _postprocess_openai_schema(schema: dict) -> None:
    schema.pop('default', None)
    if '$ref' in schema:
        return
    if schema.get('type') == 'object' or 'properties' in schema:
        schema['additionalProperties'] = False
    props = schema.get('properties')
    if props:
        schema['required'] = list(props.keys())
        for prop_schema in props.values():
            _postprocess_openai_schema(prop_schema)
    if 'items' in schema:
        items = schema['items']
        if isinstance(items, dict):
            _postprocess_openai_schema(items)
        elif isinstance(items, list):
            for item in items:
                _postprocess_openai_schema(item)
    if '$defs' in schema:
        for def_schema in schema['$defs'].values():
            _postprocess_openai_schema(def_schema)


class PlanDeCoursAIResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        json_schema_extra=lambda schema, _: _postprocess_openai_schema(schema)
    )
    compatibility_percentage: Optional[float] = None
    recommendation_ameliore: Optional[str] = None
    recommendation_plan_cadre: Optional[str] = None


@shared_task(bind=True, name='src.app.tasks.analyse_plan_de_cours.analyse_plan_de_cours_task')
def analyse_plan_de_cours_task(self, plan_id: int, user_id: int) -> dict:
    """Analyse un plan de cours via OpenAI (Responses API) et met à jour la BD.

    Publie le streaming (stream_chunk/stream_buffer) et reasoning_summary
    via self.update_state(meta=...). Retourne un payload unifié.
    """
    try:
        plan = db.session.get(PlanDeCours, plan_id)
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

        prompt_template = AnalysePlanCoursPrompt.query.first()
        if not prompt_template:
            return {"status": "error", "message": "Le template d'analyse n'est pas configuré."}

        plan_cadre = plan.cours.plan_cadre if plan.cours else None
        if not plan_cadre:
            return {"status": "error", "message": "Plan-cadre indisponible pour le cours."}

        schema = PlanDeCoursAIResponse.model_json_schema()
        structured_request = {
            "plan_cours_id": plan.id,
            "plan_cours": plan.to_dict(),
            "plan_cadre_id": plan_cadre.id,
            "plan_cadre": plan_cadre.to_dict(),
            "schema_json": schema,
        }

        sa = SectionAISettings.get_for('analyse_plan_cours')
        ai_model = sa.ai_model or 'gpt-5'
        sys_text = (sa.system_prompt or '')
        instruction = prompt_template.prompt_template or ''
        if instruction:
            sys_text = (sys_text + "\n\n" + instruction).strip()

        client = OpenAI(api_key=user.openai_key)

        input_data = []
        if sys_text:
            input_data.append({"role": "system", "content": [{"type": "input_text", "text": sys_text}]})
        input_data.append({"role": "user", "content": [{"type": "input_text", "text": json.dumps(structured_request, ensure_ascii=False)}]})

        reasoning_params = {"summary": "auto"}
        if sa.reasoning_effort in {"minimal", "low", "medium", "high"}:
            reasoning_params["effort"] = sa.reasoning_effort

        text_kwargs = {
            "format": {"type": "json_schema", "name": "PlanDeCoursAIResponse", "schema": schema, "strict": True}
        }
        if sa.verbosity in {"low", "medium", "high"}:
            text_kwargs["verbosity"] = sa.verbosity

        total_prompt_tokens = 0
        total_completion_tokens = 0

        streamed_text = ""
        reasoning_summary = ""

        # Streaming quand possible
        try:
            self.update_state(state='PROGRESS', meta={'message': 'Appel du modèle (stream)…'})
            with client.responses.stream(
                model=ai_model,
                input=input_data,
                text=text_kwargs,
                reasoning=reasoning_params,
            ) as stream:
                for event in stream:
                    et = getattr(event, 'event', '') or ''
                    if et.endswith('response.output_text.delta') or et == 'response.output_text.delta':
                        delta = getattr(event, 'delta', '') or ''
                        if delta:
                            streamed_text += delta
                            self.update_state(state='PROGRESS', meta={'stream_chunk': delta, 'stream_buffer': streamed_text})
                    elif et.endswith('response.reasoning_summary_text.delta') or et == 'response.reasoning_summary_text.delta':
                        rs_delta = getattr(event, 'delta', '') or ''
                        if rs_delta:
                            reasoning_summary += rs_delta
                            self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary.strip()})
                completion = stream.get_final_response()
        except Exception:
            # Fallback non-stream
            self.update_state(state='PROGRESS', meta={'message': 'Appel du modèle…'})
            completion = client.responses.create(
                model=ai_model,
                input=input_data,
                text=text_kwargs,
                reasoning=reasoning_params,
            )

        # Usage et coût
        usage_prompt = getattr(getattr(completion, 'usage', None), 'input_tokens', 0) or 0
        usage_completion = getattr(getattr(completion, 'usage', None), 'output_tokens', 0) or 0
        total_prompt_tokens += usage_prompt
        total_completion_tokens += usage_completion
        cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)

        if user.credits < cost:
            return {"status": "error", "message": "Crédits insuffisants pour cette opération."}
        user.credits -= cost

        # Parsing robuste: parsed JSON ou texte JSON
        try:
            outputs = getattr(completion, 'output', []) or []
            payload = None
            for item in outputs:
                for c in getattr(item, 'content', []) or []:
                    c_parsed = getattr(c, 'parsed', None)
                    if c_parsed:
                        payload = c_parsed
                        break
                    c_text = getattr(c, 'text', None)
                    if c_text:
                        try:
                            j = json.loads(c_text)
                        except Exception:
                            j = None
                        if isinstance(j, dict):
                            payload = j
                            break
                if payload:
                    break
            if payload is None:
                ai = PlanDeCoursAIResponse()
            else:
                ai = PlanDeCoursAIResponse.model_validate(payload)
        except ValidationError as ve:
            logger.error(f"Validation Pydantic error: {ve}")
            return {"status": "error", "message": "Erreur de validation du résultat IA."}
        except Exception as e:
            logger.error(f"Erreur de parsing du résultat IA: {e}")
            return {"status": "error", "message": "Erreur de structuration des données par l'IA."}

        # Mise à jour BD
        plan.compatibility_percentage = getattr(ai, 'compatibility_percentage', None)
        plan.recommendation_ameliore = getattr(ai, 'recommendation_ameliore', None)
        plan.recommendation_plan_cadre = getattr(ai, 'recommendation_plan_cadre', None)
        db.session.commit()

        result = {
            'status': 'success',
            'plan_id': plan.id,
            'cours_id': plan.cours_id,
            'session': plan.session,
            'compatibility_percentage': plan.compatibility_percentage,
            'recommendation_ameliore': plan.recommendation_ameliore,
            'recommendation_plan_cadre': plan.recommendation_plan_cadre,
            'usage': {
                'input_tokens': total_prompt_tokens,
                'output_tokens': total_completion_tokens,
                'cost': cost,
                'model': ai_model,
            },
            # Retour vers la gestion avec réouverture du modal de vérification
            'validation_url': f"/gestion_programme/?open=verify&plan_id={plan.id}",
        }
        if reasoning_summary:
            result['reasoning_summary'] = reasoning_summary.strip()
        return result
    except Exception as e:
        logger.exception("Erreur dans analyse_plan_de_cours_task")
        return {"status": "error", "message": str(e)}

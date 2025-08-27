import json
import logging
import re
import unicodedata
from typing import List

from celery import shared_task
from celery.exceptions import Ignore
from openai import OpenAI

from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.utils.datetime_utils import now_utc

from src.app.models import Programme, User, ChatModelConfig

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='src.app.tasks.generation_logigramme.generate_programme_logigramme_task')
def generate_programme_logigramme_task(self, programme_id: int, user_id: int, form: dict):
    """Celery task to generate suggested cours→compétence links via OpenAI.

    Returns a result dict:
    {
      'status': 'success',
      'result': { 'links': [{cours_code, competence_code, type}], 'reasoning_summary': str },
      'usage': { 'prompt_tokens': int, 'completion_tokens': int, 'cost': float }
    }
    """
    try:
        programme = db.session.get(Programme, programme_id)
        if not programme:
            return { 'status': 'error', 'message': 'Programme introuvable' }
        user = db.session.get(User, user_id)
        if not user:
            return { 'status': 'error', 'message': 'Utilisateur introuvable' }
        if not user.openai_key:
            return { 'status': 'error', 'message': "Aucune clé OpenAI configurée dans votre profil." }

        # Modèle et paramètres IA: priorité au formulaire, sinon config centrale
        cfg = None
        try:
            cfg = ChatModelConfig.get_current()
        except Exception:
            cfg = None
        ai_model = (form or {}).get('ai_model') or (cfg.chat_model if cfg and cfg.chat_model else 'gpt-5')
        additional_info = (form or {}).get('additional_info') or ''
        reasoning_effort = (form or {}).get('reasoning_effort') or ((cfg.reasoning_effort or 'medium') if cfg else 'medium')
        verbosity = (form or {}).get('verbosity') or ((cfg.verbosity or 'medium') if cfg else 'medium')

        # Collect inputs
        course_items = []
        for assoc in programme.cours_assocs:
            c = assoc.cours
            if not c:
                continue
            course_items.append({
                'code': c.code, 'nom': c.nom,
                'session': assoc.session or 0,
                'heures_theorie': c.heures_theorie,
                'heures_laboratoire': c.heures_laboratoire,
                'heures_travail_maison': c.heures_travail_maison,
            })
        comp_list = []
        comps = programme.competences.order_by().all()
        for comp in comps:
            elements = []
            for e in comp.elements:
                criteres = [c.criteria for c in e.criteria]
                elements.append({ 'nom': e.nom, 'criteres': criteres })
            comp_list.append({
                'code': comp.code, 'nom': comp.nom,
                'criteria_de_performance': comp.criteria_de_performance,
                'contexte_de_realisation': comp.contexte_de_realisation,
                'elements': elements
            })

        system_prompt = (
            "Tu es un assistant pédagogique expert des programmes collégiaux. "
            "À partir du nom du programme, de la liste de cours et de la liste de compétences (avec leurs éléments et critères), "
            "propose un logigramme de liens cours→compétence."
        )
        user_prompt = (
            "Consignes:\n"
            "- Retourne exclusivement du JSON valide avec une clé 'links' contenant une liste d'objets.\n"
            "- Chaque lien contient: 'cours_code' (code du cours), 'competence_code' (code de la compétence), 'type'∈{\"developpe\",\"atteint\",\"reinvesti\"}.\n"
            "- Oriente les liens du cours vers la compétence. Évite les doublons stricts.\n"
            "- Utilise uniquement les codes fournis (pas d'invention).\n"
            "- Contraintes fortes: au maximum 3 compétences par cours; au plus 2 liens de type 'reinvesti' par cours; une même compétence ne doit pas apparaître dans plus de 3 cours du programme.\n"
            "- Répartition temporelle: privilégier 'developpe' dans les sessions initiales, puis 'atteint' lorsque la compétence est consolidée en fin de parcours; 'reinvesti' sert à réutiliser des compétences déjà atteintes ou développés.\n"
            "- Plusieurs cours devraient développés une même compétence (2 cours par compétence + 1 qui certifie), idéalement, pas à la même session. \n"
            "- Couverture des compétences: chaque compétence du programme doit être marquée au moins une fois 'atteint' et, ce, répartit à travers le programme (il y en aura plus vers la fin du parcours évidemment).\n"
            "- Cohérence temporelle: une compétence ne doit plus être marquée 'developpe' dans une session ultérieure après avoir été marquée 'atteint'.\n\n"
            f"Programme: {programme.nom}\n"
            f"Informations supplémentaires (optionnel): {additional_info}\n\n"
            "Cours (code, nom, session, heures):\n"
            f"{json.dumps(course_items, ensure_ascii=False)}\n\n"
            "Compétences (code, nom, contexte, critères, éléments):\n"
            f"{json.dumps(comp_list, ensure_ascii=False)}\n\n"
            "Exemple de sortie JSON minimal:\n"
            "{\n  \"links\": [\n    {\"cours_code\": \"420-ABC\", \"competence_code\": \"C1\", \"type\": \"developpe\"}\n  ]\n}"
        )

        self.update_state(state='PROGRESS', meta={'message': 'Préparation des données…'})
        client = OpenAI(api_key=user.openai_key)

        # Prepare request (do not include stream flag here; pass it only to .stream())
        request_kwargs = dict(
            model=ai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            metadata={'feature': 'generate_programme_logigramme', 'programme_id': str(programme.id)}
        )
        try:
            request_kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
        except Exception:
            pass
        try:
            request_kwargs["text"] = {"verbosity": verbosity}
        except Exception:
            pass

        output_text = ''
        streamed_text = ''
        reasoning_summary = ''
        usage_prompt = 0
        usage_completion = 0

        # Try streaming first (if SDK supports)
        try:
            self.update_state(state='PROGRESS', meta={'message': 'Appel du modèle (stream)…'})
            with client.responses.stream(**request_kwargs) as stream:
                for event in stream:
                    et = getattr(event, 'type', '') or ''
                    if et.endswith('response.output_text.delta') or et == 'response.output_text.delta':
                        delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                        if delta:
                            streamed_text += delta
                            try:
                                self.update_state(state='PROGRESS', meta={'stream_chunk': delta, 'stream_buffer': streamed_text})
                            except Exception:
                                pass
                    elif et.endswith('response.output_item.added') or et == 'response.output_item.added':
                        # Some models emit items with text rather than output_text deltas
                        try:
                            item = getattr(event, 'item', None)
                            tval = ''
                            if item:
                                if isinstance(item, dict):
                                    tval = item.get('text') or ''
                                else:
                                    tval = getattr(item, 'text', '') or ''
                            if tval:
                                streamed_text += tval
                        except Exception:
                            pass
                    elif et.endswith('response.reasoning_summary_text.delta') or et == 'response.reasoning_summary_text.delta':
                        rs_delta = getattr(event, 'delta', '') or ''
                        if rs_delta:
                            reasoning_summary += rs_delta
                            try:
                                self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary.strip()})
                            except Exception:
                                pass
                resp = stream.get_final_response()
        except Exception as se:
            logger.warning(f"Streaming non dispo, fallback non-stream: {se}")
            self.update_state(state='PROGRESS', meta={'message': 'Appel du modèle…'})
            resp = client.responses.create(**request_kwargs)
            try:
                # Try to extract reasoning summary similarly to grille task
                if hasattr(resp, "reasoning") and resp.reasoning:
                    for r in resp.reasoning:
                        for item in getattr(r, "summary", []) or []:
                            if getattr(item, "type", "") == "summary_text":
                                reasoning_summary += getattr(item, "text", "") or ""
            except Exception:
                pass
        output_text = streamed_text or getattr(resp, 'output_text', '') or ''
        usage_prompt = getattr(getattr(resp, 'usage', None), 'input_tokens', 0) or 0
        usage_completion = getattr(getattr(resp, 'usage', None), 'output_tokens', 0) or 0

        # Parse
        self.update_state(state='PROGRESS', meta={'message': 'Analyse de la réponse…'})

        def _extract_json(txt: str) -> dict:
            if not txt:
                return {}
            txt = txt.strip()
            # Remove potential Markdown fences ```json ... ```
            if txt.startswith("```"):
                txt = re.sub(r'^```(?:json)?\n?', '', txt)
                txt = re.sub(r'```$', '', txt).strip()
            try:
                return json.loads(txt)
            except Exception:
                match = re.search(r'\{.*\}', txt, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(0))
                    except Exception:
                        pass
            return {}

        data = _extract_json(output_text)
        links = data.get('links') or []
        allowed = {'developpe', 'atteint', 'reinvesti'}
        cleaned = []
        for l in links:
            try:
                cc = str(l.get('cours_code') or '').strip()
                kc = str(l.get('competence_code') or '').strip()
                tp = str(l.get('type') or '').strip().lower()
                tp = unicodedata.normalize('NFKD', tp).encode('ascii', 'ignore').decode('ascii')
            except Exception:
                continue
            if not cc or not kc or tp not in allowed:
                continue
            cleaned.append({'cours_code': cc, 'competence_code': kc, 'type': tp})

        # If the model returned nothing usable, fail the task explicitly to avoid SUCCESS with empty data
        if not cleaned:
            # Provide a helpful error depending on what we got
            if not (output_text or '').strip():
                raise RuntimeError("Aucune réponse utile du modèle (sortie vide).")
            raise RuntimeError("Réponse du modèle invalide ou sans liens exploitables.")

        # Credits calculation
        try:
            cost = calculate_call_cost(usage_prompt, usage_completion, ai_model)
        except Exception as e:
            logger.warning(f"Tarification indisponible pour {ai_model}: {e}; coût=0")
            cost = 0.0
        new_credits = (user.credits or 0) - cost
        if new_credits < 0:
            return { 'status': 'error', 'message': "Crédits insuffisants pour cet appel." }
        user.credits = new_credits
        db.session.commit()

        result = {
            'status': 'success',
            'result': { 'links': cleaned, 'reasoning_summary': reasoning_summary },
            'usage': { 'prompt_tokens': usage_prompt, 'completion_tokens': usage_completion, 'cost': cost }
        }
        try:
            # Rediriger vers la vue interactive du logigramme pour validation/ajustement
            result['validation_url'] = f"/programme/{programme.id}/competences/logigramme"
        except Exception:
            pass
        return result
    except Exception as e:
        logger.exception('Erreur génération logigramme')
        return { 'status': 'error', 'message': f'Erreur: {e}' }

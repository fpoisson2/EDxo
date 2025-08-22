import json
import logging
from typing import List

from celery import shared_task
from celery.exceptions import Ignore
from openai import OpenAI

from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.utils.datetime_utils import now_utc

from src.app.models import Programme, User

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

        ai_model = (form or {}).get('ai_model') or 'gpt-5'
        additional_info = (form or {}).get('additional_info') or ''
        reasoning_effort = (form or {}).get('reasoning_effort') or 'medium'
        verbosity = (form or {}).get('verbosity') or 'medium'

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
            "- Plusieurs cours peuvent développés une même compétence, idéalement, pas à la même session. \n"
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

        # Prepare request
        request_kwargs = dict(
            model=ai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            reasoning={'effort': reasoning_effort},
            metadata={'feature': 'generate_programme_logigramme', 'programme_id': str(programme.id)},
        )

        output_text = ''
        reasoning_summary = ''
        usage_prompt = 0
        usage_completion = 0

        # Try streaming first (if SDK supports)
        try:
            self.update_state(state='PROGRESS', meta={'message': 'Appel du modèle (stream)…'})
            with client.responses.stream(**request_kwargs) as stream:
                for event in stream:
                    et = getattr(event, 'type', '') or ''
                    if et.endswith('message.delta') or et.endswith('output_text.delta'):
                        # Optionally, we can append minimal progress here
                        pass
                    elif getattr(event, 'summary', None):
                        try:
                            for s in event.summary:
                                if getattr(s, 'type', '') == 'summary_text':
                                    reasoning_summary += getattr(s, 'text', '') or ''
                        except Exception:
                            pass
                    elif et.endswith('response.completed'):
                        break
                resp = stream.get_final_response()
                output_text = getattr(resp, 'output_text', '') or ''
                if hasattr(resp, 'usage'):
                    usage_prompt = resp.usage.input_tokens
                    usage_completion = resp.usage.output_tokens
        except Exception as se:
            logger.warning(f"Streaming non dispo, fallback non-stream: {se}")
            self.update_state(state='PROGRESS', meta={'message': 'Appel du modèle…'})
            resp = client.responses.create(**request_kwargs)
            output_text = getattr(resp, 'output_text', '') or ''
            if hasattr(resp, 'usage'):
                usage_prompt = resp.usage.input_tokens
                usage_completion = resp.usage.output_tokens

        # Parse
        self.update_state(state='PROGRESS', meta={'message': 'Analyse de la réponse…'})
        data = json.loads(output_text) if output_text else {}
        links = data.get('links') or []
        allowed = {'developpe', 'atteint', 'reinvesti'}
        cleaned = []
        for l in links:
            try:
                cc = str(l.get('cours_code') or '').strip()
                kc = str(l.get('competence_code') or '').strip()
                tp = str(l.get('type') or '').strip().lower()
            except Exception:
                continue
            if not cc or not kc or tp not in allowed:
                continue
            cleaned.append({'cours_code': cc, 'competence_code': kc, 'type': tp})

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
        return result
    except Exception as e:
        logger.exception('Erreur génération logigramme')
        return { 'status': 'error', 'message': f'Erreur: {e}' }

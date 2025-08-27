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

from src.app.models import Programme, User, ChatModelConfig, ElementCompetence, ElementCompetenceParCours, SectionAISettings

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
        sa = None
        try:
            sa = SectionAISettings.get_for('logigramme')
        except Exception:
            sa = None
        ai_model = (form or {}).get('ai_model') or (sa.ai_model if sa and sa.ai_model else (cfg.chat_model if cfg and cfg.chat_model else 'gpt-5'))
        additional_info = (form or {}).get('additional_info') or ''
        reasoning_effort = (form or {}).get('reasoning_effort') or (sa.reasoning_effort if sa and sa.reasoning_effort else ((cfg.reasoning_effort or 'medium') if cfg else 'medium'))
        verbosity = (form or {}).get('verbosity') or (sa.verbosity if sa and sa.verbosity else ((cfg.verbosity or 'medium') if cfg else 'medium'))

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

        # System prompt strictly from DB (no hard-coded fallback)
        system_prompt = (sa.system_prompt if (sa and sa.system_prompt) else '')
        # User message should only contain the data (courses/competences), no instructions
        user_payload = {
            'courses': course_items,
            'competences': comp_list
        }

        self.update_state(state='PROGRESS', meta={'message': 'Préparation des données…'})
        client = OpenAI(api_key=user.openai_key)

        # Prepare request (do not include stream flag here; pass it only to .stream())
        request_kwargs = dict(
            model=ai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
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

        # Persist directly in DB (overwrite existing links) — no validation step
        self.update_state(state='PROGRESS', meta={'message': 'Préparation des écritures BD…'})

        # Build lookups for cours and competences by code + set of course_ids in programme
        course_code_to_id = {}
        programme_course_ids = set()
        for assoc in programme.cours_assocs:
            c = assoc.cours
            if not c or not (c.code or '').strip():
                continue
            programme_course_ids.add(c.id)
            course_code_to_id[str(c.code).strip()] = c.id
        comp_code_to_id = {}
        try:
            comps = programme.competences.order_by().all()
        except Exception:
            comps = []
        for comp in comps:
            if not (comp.code or '').strip():
                continue
            comp_code_to_id[str(comp.code).strip()] = comp.id

        # Map generated links to IDs and filter invalids
        desired = []
        for l in cleaned:
            cc = l.get('cours_code'); kc = l.get('competence_code'); tp = l.get('type')
            cid = course_code_to_id.get(cc)
            kid = comp_code_to_id.get(kc)
            if not cid or not kid or cid not in programme_course_ids:
                continue
            desired.append({'cours_id': cid, 'competence_id': kid, 'type': tp})

        if not desired:
            raise RuntimeError("Génération valide mais aucune correspondance cours/compétence trouvée en BD.")

        # Overwrite ElementCompetenceParCours similar to /programme/<id>/links route
        allowed_types = {'developpe': 'Développé significativement', 'atteint': 'Atteint', 'reinvesti': 'Réinvesti'}

        # Build competence_id -> [element ids] and global set of element ids for the programme
        comp_to_elem_ids = {}
        all_elem_ids = []
        for comp in comps:
            eids = [e.id for e in ElementCompetence.query.filter_by(competence_id=comp.id).all()]
            comp_to_elem_ids[comp.id] = eids
            all_elem_ids.extend(eids)

        # Pairs present in generated result
        payload_pairs = set()
        updated_pairs = 0

        self.update_state(state='PROGRESS', meta={'message': 'Écriture BD — application des liens…'})
        for item in desired:
            cours_id = int(item.get('cours_id') or 0)
            competence_id = int(item.get('competence_id') or 0)
            ltype = str(item.get('type') or '')
            if ltype not in allowed_types:
                continue
            # Ensure competence is part of programme set
            if competence_id not in comp_to_elem_ids:
                continue
            payload_pairs.add((cours_id, competence_id))
            status_value = allowed_types[ltype]
            elem_ids = comp_to_elem_ids.get(competence_id) or []
            if not elem_ids:
                continue
            existing = { r.element_competence_id: r for r in ElementCompetenceParCours.query
                         .filter_by(cours_id=cours_id)
                         .filter(ElementCompetenceParCours.element_competence_id.in_(elem_ids))
                         .all() }
            for eid in elem_ids:
                row = existing.get(eid)
                if not row:
                    row = ElementCompetenceParCours(cours_id=cours_id, element_competence_id=eid, status=status_value)
                    db.session.add(row)
                else:
                    row.status = status_value
            updated_pairs += 1

        # Deletions: remove EPC rows for pairs that are no longer present
        if all_elem_ids and programme_course_ids:
            rows = (ElementCompetenceParCours.query
                    .filter(ElementCompetenceParCours.cours_id.in_(list(programme_course_ids)))
                    .filter(ElementCompetenceParCours.element_competence_id.in_(all_elem_ids))
                    .all())
            # Build reverse map element_id -> competence_id
            elem_to_comp = {}
            for cid, eids in comp_to_elem_ids.items():
                for eid in eids:
                    elem_to_comp[eid] = cid
            for r in rows:
                comp_id = elem_to_comp.get(r.element_competence_id)
                if comp_id is None:
                    continue
                if (r.cours_id, comp_id) not in payload_pairs:
                    db.session.delete(r)

        db.session.commit()

        result = {
            'status': 'success',
            'result': {
                'links': cleaned,
                'reasoning_summary': reasoning_summary,
                'applied_pairs': updated_pairs,
                'message': f"{updated_pairs} liens appliqués (écrasement effectué)",
                'logigramme_url': f"/programme/{programme.id}/competences/logigramme"
            },
            'usage': { 'prompt_tokens': usage_prompt, 'completion_tokens': usage_completion, 'cost': cost },
            # Convenience link: everything is already applied, so let the UI
            # show the navigation button toward the logigramme page.
            'validation_url': f"/programme/{programme.id}/competences/logigramme"
        }
        return result
    except Exception as e:
        logger.exception('Erreur génération logigramme')
        return { 'status': 'error', 'message': f'Erreur: {e}' }

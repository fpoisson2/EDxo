import json
import logging
from celery import shared_task
from openai import OpenAI

from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.app.models import Programme, User, Competence, ChatModelConfig, SectionAISettings

logger = logging.getLogger(__name__)


def _extract_reasoning_summary_from_response(response):
    """Extract reasoning summary text from a Responses API result."""
    summary = ""
    try:
        if hasattr(response, "reasoning") and response.reasoning:
            for r in response.reasoning:
                for item in getattr(r, "summary", []) or []:
                    if getattr(item, "type", "") == "summary_text":
                        summary += getattr(item, "text", "") or ""
    except Exception:
        pass
    if not summary:
        try:
            for out in getattr(response, "output", []) or []:
                if getattr(out, "type", "") == "reasoning":
                    for item in getattr(out, "summary", []) or []:
                        if getattr(item, "type", "") == "summary_text":
                            summary += getattr(item, "text", "") or ""
        except Exception:
            pass
    return summary.strip()


@shared_task(bind=True, name='src.app.tasks.generation_grille.generate_programme_grille_task')
def generate_programme_grille_task(self, programme_id: int, user_id: int, form: dict):
    """Génère une proposition de grille de cours par session via l'IA.

    Entrée (form):
      - ai_model (str)
      - total_hours (int)
      - total_units (float, optionnel)
      - nb_sessions (int)
      - additional_info (str, optionnel)

    Sortie:
      {
        'status': 'success',
        'result': {
           'sessions': [
             { 'session': 1, 'courses': [
                 { 'nom': '...', 'heures_theorie': 3, 'heures_laboratoire': 2, 'heures_travail_maison': 2, 'nombre_unites': 1.0 },
                 ...
             ]},
             ...
           ]
        },
        'usage': { 'prompt_tokens': int, 'completion_tokens': int, 'cost': float }
      }
    """
    try:
        programme = db.session.get(Programme, programme_id)
        user = db.session.get(User, user_id)
        if not programme:
            return { 'status': 'error', 'message': 'Programme introuvable' }
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
            sa = SectionAISettings.get_for('grille')
        except Exception:
            sa = None
        ai_model = (form or {}).get('ai_model') or (sa.ai_model if sa and sa.ai_model else (cfg.chat_model if cfg and cfg.chat_model else 'gpt-5'))
        total_hours = int((form or {}).get('total_hours') or 0)
        total_units = float((form or {}).get('total_units') or 0)
        nb_sessions = int((form or {}).get('nb_sessions') or 0)
        additional_info = (form or {}).get('additional_info') or ''
        reasoning_effort = (form or {}).get('reasoning_effort') or (sa.reasoning_effort if sa and sa.reasoning_effort else ((cfg.reasoning_effort or 'medium') if cfg else 'medium'))
        verbosity = (form or {}).get('verbosity') or (sa.verbosity if sa and sa.verbosity else ((cfg.verbosity or 'medium') if cfg else 'medium'))

        if total_hours <= 0 or nb_sessions <= 0:
            return { 'status': 'error', 'message': 'Paramètres invalides (heures/sessions).' }

        # Récupérer la liste des compétences du programme (contexte de génération)
        competences_list = [
            {
                'code': comp.code,
                'nom': comp.nom,
            }
            for comp in programme.competences.order_by(Competence.code).all()
        ]

        # System prompt: from settings only (no hard-coded defaults)
        system_prompt = (sa.system_prompt if sa and getattr(sa, 'system_prompt', None) else '')
        # User content: raw data only
        user_payload = {
            'programme': {'id': programme.id, 'nom': programme.nom},
            'total_hours': total_hours,
            'total_units': (total_units if total_units > 0 else None),
            'nb_sessions': nb_sessions,
            'additional_info': additional_info,
            'competences': competences_list,
        }

        self.update_state(state='PROGRESS', meta={'message': 'Appel du modèle…'})
        client = OpenAI(api_key=user.openai_key)
        request_kwargs = dict(
            model=ai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
            ],
            metadata={'feature': 'generate_programme_grille', 'programme_id': str(programme.id)}
        )
        # Paramètres de raisonnement/verbosité (alignés sur d'autres tâches)
        try:
            request_kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
        except Exception:
            pass
        # La verbosité influence l'abondance des explications; le contenu doit rester JSON strict.
        # On la signale tout de même pour cohérence avec les autres appels.
        try:
            request_kwargs["text"] = {"verbosity": verbosity}
        except Exception:
            pass

        streamed_text = ""
        reasoning_summary_text = ""
        usage_prompt = 0
        usage_completion = 0
        try:
            with client.responses.stream(**request_kwargs) as stream:
                for event in stream:
                    etype = getattr(event, 'type', '') or ''
                    if etype.endswith('response.output_text.delta') or etype == 'response.output_text.delta':
                        delta = getattr(event, 'delta', '') or getattr(event, 'text', '') or ''
                        if delta:
                            streamed_text += delta
                            try:
                                self.update_state(state='PROGRESS', meta={
                                    'stream_chunk': delta,
                                    'stream_buffer': streamed_text
                                })
                            except Exception:
                                pass
                    elif etype.endswith('response.output_item.added') or etype == 'response.output_item.added':
                        try:
                            item = getattr(event, 'item', None)
                            text_val = ''
                            if item:
                                if isinstance(item, dict):
                                    text_val = item.get('text') or ''
                                else:
                                    text_val = getattr(item, 'text', '') or ''
                            if text_val:
                                streamed_text += text_val
                        except Exception:
                            pass
                    elif etype.endswith('response.reasoning_summary_text.delta') or etype == 'response.reasoning_summary_text.delta':
                        try:
                            rs_delta = getattr(event, 'delta', '') or ''
                            if rs_delta:
                                reasoning_summary_text += rs_delta
                                try:
                                    self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary_text})
                                except Exception:
                                    pass
                        except Exception:
                            pass
                resp = stream.get_final_response()
        except Exception:
            resp = client.responses.create(**request_kwargs)
            streamed_text = getattr(resp, 'output_text', '') or ''
            try:
                reasoning_summary_text = _extract_reasoning_summary_from_response(resp)
                if reasoning_summary_text:
                    self.update_state(state='PROGRESS', meta={'reasoning_summary': reasoning_summary_text})
            except Exception:
                pass
        output_text = streamed_text or getattr(resp, 'output_text', '') or ''
        usage_prompt = getattr(getattr(resp, 'usage', None), 'input_tokens', 0) or 0
        usage_completion = getattr(getattr(resp, 'usage', None), 'output_tokens', 0) or 0

        self.update_state(state='PROGRESS', meta={'message': 'Analyse de la réponse…'})
        data = json.loads(output_text) if output_text else {}
        sessions = data.get('sessions') or []
        # Nettoyage minimal + extraction des préalables/corequis
        cleaned = []
        for s in sessions:
            try:
                sn = int(s.get('session'))
            except Exception:
                continue
            courses = []
            for cr in (s.get('courses') or []):
                try:
                    ht = int(cr.get('heures_theorie') or 0)
                    hl = int(cr.get('heures_laboratoire') or 0)
                    hm = int(cr.get('heures_travail_maison') or 0)
                    nu = cr.get('nombre_unites')
                    try:
                        nu = float(nu)
                    except Exception:
                        nu = None
                    if not nu or nu <= 0:
                        nu = float(ht + hl + hm)
                    # Préparer listes préalables/corequis (strings uniques)
                    raw_prealables = cr.get('prealables') or cr.get('prerequis') or []
                    if isinstance(raw_prealables, str):
                        raw_prealables = [raw_prealables]
                    prealables = []
                    seen_p = set()
                    for p in raw_prealables:
                        try:
                            name = str(p).strip()
                        except Exception:
                            continue
                        if not name:
                            continue
                        if name.lower() in seen_p:
                            continue
                        prealables.append(name)
                        seen_p.add(name.lower())
                        if len(prealables) >= 2:
                            break  # Ne jamais dépasser 2 préalables

                    raw_corequis = cr.get('corequis') or []
                    if isinstance(raw_corequis, str):
                        raw_corequis = [raw_corequis]
                    corequis = []
                    seen_c = set()
                    for c in raw_corequis:
                        try:
                            namec = str(c).strip()
                        except Exception:
                            continue
                        if not namec:
                            continue
                        if namec.lower() in seen_c:
                            continue
                        corequis.append(namec)
                        seen_c.add(namec.lower())
                    courses.append({
                        'nom': str(cr.get('nom') or 'Cours généré').strip()[:120],
                        'heures_theorie': ht,
                        'heures_laboratoire': hl,
                        'heures_travail_maison': hm,
                        'nombre_unites': round(nu, 2),
                        'prealables': prealables,
                        'corequis': corequis,
                    })
                except Exception:
                    continue
            cleaned.append({'session': sn, 'courses': courses})

        # Extraire/assainir les fils conducteurs (facultatif)
        raw_fils = data.get('fils_conducteurs') or []
        fils_conducteurs = []
        # Construire l'ensemble des noms de cours générés pour validation des associations
        generated_course_names = set()
        for s in cleaned:
            for c in s['courses']:
                generated_course_names.add(c['nom'])

        def _valid_hex(color: str) -> bool:
            if not isinstance(color, str) or len(color) != 7 or not color.startswith('#'):
                return False
            try:
                int(color[1:], 16)
                return True
            except Exception:
                return False

        used_colors = set()
        for f in (raw_fils if isinstance(raw_fils, list) else []):
            try:
                desc = str(f.get('description') or '').strip()
                col = str(f.get('couleur') or '').strip()
                cours_list = f.get('cours') or []
                if isinstance(cours_list, str):
                    cours_list = [cours_list]
                # Filtrer les cours inconnus
                assoc = []
                seen = set()
                for name in cours_list:
                    try:
                        n = str(name).strip()
                    except Exception:
                        continue
                    if not n or n in seen:
                        continue
                    if n in generated_course_names:
                        assoc.append(n)
                        seen.add(n)
                if not assoc or not desc:
                    continue
                # Assainir la couleur ou générer une couleur par défaut
                if not _valid_hex(col) or col.upper() in used_colors:
                    # Palette simple de secours
                    fallback = [
                        '#1F77B4', '#FF7F0E', '#2CA02C', '#D62728', '#9467BD',
                        '#8C564B', '#E377C2', '#7F7F7F', '#BCBD22', '#17BECF'
                    ]
                    for cand in fallback:
                        if cand not in used_colors:
                            col = cand
                            break
                used_colors.add(col.upper())
                fils_conducteurs.append({'description': desc[:200], 'couleur': col, 'cours': assoc})
            except Exception:
                continue

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

        result_payload = {
            'sessions': cleaned,
            'fils_conducteurs': fils_conducteurs
        }
        if reasoning_summary_text:
            result_payload['reasoning_summary'] = reasoning_summary_text
        return {
            'status': 'success',
            'result': result_payload,
            'usage': { 'prompt_tokens': usage_prompt, 'completion_tokens': usage_completion, 'cost': cost },
            # Lien standardisé vers la page de validation (comparaison/édition)
            # Utiliser la variante avec paramètre de chemin, alignée sur la route Flask
            'validation_url': f"/programme/{programme.id}/grille/review/{self.request.id}"
        }
    except Exception as e:
        logger.exception('Erreur génération grille')
        return { 'status': 'error', 'message': f'Erreur: {e}' }

import json
import logging
from celery import shared_task
from openai import OpenAI

from src.extensions import db
from src.utils.openai_pricing import calculate_call_cost
from src.app.models import Programme, User, Competence

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='src.app.tasks.generation_grille.generate_programme_grille_task')
def generate_programme_grille_task(self, programme_id: int, user_id: int, form: dict):
    """Génère une proposition de grille de cours par session via l'IA.

    Entrée (form):
      - ai_model (str)
      - total_hours (int)
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

        ai_model = (form or {}).get('ai_model') or 'gpt-5'
        total_hours = int((form or {}).get('total_hours') or 0)
        nb_sessions = int((form or {}).get('nb_sessions') or 0)
        additional_info = (form or {}).get('additional_info') or ''
        reasoning_effort = (form or {}).get('reasoning_effort') or 'medium'
        verbosity = (form or {}).get('verbosity') or 'medium'

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

        system_prompt = (
            "Tu es un conseiller pédagogique. À partir du nombre total d'heures et du nombre de sessions, "
            "propose une grille de cours répartie par session pour le programme ci-dessous."
        )
        user_prompt = (
            "Contraintes et format (respect strict):\n"
            "- Base-toi sur la liste des compétences du programme (ci-dessous).\n"
            "- Pour chaque cours, fournis un 'nom' (sans code), et une ventilation en 'heures_theorie', 'heures_laboratoire', 'heures_travail_maison'.\n"
            "- Définition des heures d'un cours: h_cours = (heures_theorie + heures_laboratoire + heures_travail_maison) * 15.\n"
            "- Somme stricte: la somme de tous les h_cours sur toutes les sessions DOIT être égale (pas proche) aux 'Heures totales à répartir'. Ajuste les 3 valeurs au besoin pour obtenir l'égalité exacte.\n"
            "- Répartis les heures sur les sessions de manière équilibrée et cohérente avec les compétences.\n"
            "- Retourne strictement du JSON valide de la forme: {\"sessions\":[{\"session\":1,\"courses\":[{\"nom\":\"...\",\"heures_theorie\":3,\"heures_laboratoire\":2,\"heures_travail_maison\":2}]}]}\n"
            f"Programme: {programme.nom}\n"
            f"Heures totales à répartir: {total_hours}\n"
            f"Nombre de sessions: {nb_sessions}\n"
            f"Contexte additionnel (facultatif): {additional_info}\n\n"
            f"Compétences du programme: {json.dumps(competences_list, ensure_ascii=False)}\n"
        )

        self.update_state(state='PROGRESS', meta={'message': 'Appel du modèle…'})
        client = OpenAI(api_key=user.openai_key)
        request_kwargs = dict(
            model=ai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
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

        resp = client.responses.create(**request_kwargs)

        output_text = getattr(resp, 'output_text', '') or ''
        usage_prompt = getattr(getattr(resp, 'usage', None), 'input_tokens', 0) or 0
        usage_completion = getattr(getattr(resp, 'usage', None), 'output_tokens', 0) or 0

        self.update_state(state='PROGRESS', meta={'message': 'Analyse de la réponse…'})
        data = json.loads(output_text) if output_text else {}
        sessions = data.get('sessions') or []
        # Nettoyage minimal
        cleaned = []
        for s in sessions:
            try:
                sn = int(s.get('session'))
            except Exception:
                continue
            courses = []
            for cr in (s.get('courses') or []):
                try:
                    courses.append({
                        'nom': str(cr.get('nom') or 'Cours généré').strip()[:120],
                        'heures_theorie': int(cr.get('heures_theorie') or 0),
                        'heures_laboratoire': int(cr.get('heures_laboratoire') or 0),
                        'heures_travail_maison': int(cr.get('heures_travail_maison') or 0),
                    })
                except Exception:
                    continue
            cleaned.append({'session': sn, 'courses': courses})

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

        # Validation stricte de la somme des heures totales retournées
        computed_total = 0
        try:
            for s in cleaned:
                for cr in s.get('courses', []):
                    computed_total += int(cr.get('heures_theorie') or 0)
                    computed_total += int(cr.get('heures_laboratoire') or 0)
                    computed_total += int(cr.get('heures_travail_maison') or 0)
            computed_total *= 15
        except Exception:
            computed_total = -1

        if computed_total != total_hours:
            return {
                'status': 'error',
                'message': (
                    f"Somme des heures générées ({computed_total}) différente du total requis ({total_hours}). "
                    "Veuillez régénérer: la somme DOIT être égale, pas approximative."
                ),
                'usage': { 'prompt_tokens': usage_prompt, 'completion_tokens': usage_completion, 'cost': cost }
            }

        return {
            'status': 'success',
            'result': { 'sessions': cleaned },
            'usage': { 'prompt_tokens': usage_prompt, 'completion_tokens': usage_completion, 'cost': cost }
        }
    except Exception as e:
        logger.exception('Erreur génération grille')
        return { 'status': 'error', 'message': f'Erreur: {e}' }

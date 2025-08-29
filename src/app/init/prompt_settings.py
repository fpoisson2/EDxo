# app/init/prompt_settings.py
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .. import db, logger
from ..models import PlanDeCoursPromptSettings


def init_plan_de_cours_prompts():
    """Initialise les configurations de prompts par défaut pour les plans de cours."""
    try:
        # Vérifier si la table existe
        result = db.session.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='plan_de_cours_prompt_settings';"
        )).fetchone()
        
        if not result:
            logger.warning("⚠️ Table 'plan_de_cours_prompt_settings' introuvable, création ignorée.")
            return

        default_prompts = {
            'presentation_du_cours': {
                'template': """Génère une présentation détaillée et professionnelle du cours en français en te basant sur les éléments suivants:
- Le contenu actuel : {current_value}
- La session : {session}

La présentation doit:
- Être claire et concise
- Expliquer la place du cours dans le programme
- Mettre en valeur les points forts et l'intérêt du cours
- Être adaptée au niveau collégial
- Utiliser un ton professionnel et engageant""",
                'context_variables': ['current_value', 'session']
            },
            'objectif_terminal_du_cours': {
                'template': """Formule un objectif terminal clair et mesurable pour ce cours en tenant compte de:
- Les objectifs actuels : {current_value}
- Le contexte du cours (ID: {cours_id})

L'objectif doit:
- Commencer par un verbe d'action
- Être mesurable et observable
- Être aligné avec les standards pédagogiques
- Être adapté au niveau collégial
- Être réaliste et atteignable
- Être formulé en français""",
                'context_variables': ['current_value', 'cours_id']
            },
            'organisation_et_methodes': {
                'template': """Décris l'organisation du cours et les méthodes pédagogiques en considérant:
- L'organisation actuelle : {current_value}
- Le contexte du cours : {cours_id}
- La session : {session}

La description doit inclure:
- Les méthodes d'enseignement utilisées
- L'organisation des séances
- Les activités d'apprentissage
- Les ressources pédagogiques
- L'approche pédagogique générale""",
                'context_variables': ['current_value', 'cours_id', 'session']
            },
            'accomodement': {
                'template': """Génère une section sur les accommodements pour ce cours en tenant compte de:
- Les accommodements actuels : {current_value}
- Le contexte spécifique du cours : {cours_id}

La section doit:
- Être inclusive et respectueuse
- Mentionner les types d'accommodements possibles
- Expliquer le processus pour obtenir des accommodements
- Être alignée avec les politiques institutionnelles
- Encourager les étudiants à communiquer leurs besoins""",
                'context_variables': ['current_value', 'cours_id']
            },
            'evaluation_formative_apprentissages': {
                'template': """Décris l'évaluation formative des apprentissages en considérant:
- L'évaluation actuelle : {current_value}
- Le contexte du cours : {cours_id}

La description doit inclure:
- Les méthodes d'évaluation formative
- La fréquence des évaluations
- Les critères d'évaluation
- Le feedback et le suivi
- L'alignement avec les objectifs d'apprentissage""",
                'context_variables': ['current_value', 'cours_id']
            },
            'evaluation_expression_francais': {
                'template': """Formule la politique d'évaluation de l'expression en français pour ce cours en tenant compte de:
- La politique actuelle : {current_value}
- Le contexte du cours : {cours_id}

La politique doit:
- Être claire et précise
- Spécifier les critères d'évaluation linguistique
- Indiquer la pondération
- Mentionner les ressources disponibles
- Encourager la qualité du français""",
                'context_variables': ['current_value', 'cours_id']
            },
            'seuil_reussite': {
                'template': """Définis le seuil de réussite du cours en considérant:
- Le seuil actuel : {current_value}
- Le contexte du cours : {cours_id}

La définition doit:
- Indiquer clairement la note de passage
- Expliquer les critères de réussite
- Mentionner les conditions particulières
- Être alignée avec les politiques institutionnelles
- Être formulée de manière claire et précise""",
                'context_variables': ['current_value', 'cours_id']
            },
            'calendrier': {
                'template': """Session: {session}\nPlan-cadre:\n{sections}""",
                'context_variables': ['session', 'sections']
            }
        }

        prompts_added = 0
        for field_name, settings in default_prompts.items():
            prompt = PlanDeCoursPromptSettings.query.filter_by(field_name=field_name).first()
            
            if not prompt:
                prompt = PlanDeCoursPromptSettings(
                    field_name=field_name,
                    prompt_template=settings['template'],
                    context_variables=settings['context_variables'],
                    ai_model='gpt-5'
                )
                db.session.add(prompt)
                prompts_added += 1
        
        if prompts_added > 0:
            db.session.commit()
            logger.info(f"✅ {prompts_added} prompts de plan de cours initialisés avec succès.")
        else:
            logger.info("ℹ️ Tous les prompts de plan de cours sont déjà initialisés.")

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"❌ Erreur SQL lors de l'initialisation des prompts : {e}")
        raise
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur inattendue lors de l'initialisation des prompts : {e}")
        raise

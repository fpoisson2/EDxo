# gestion_programme.py

import json
from typing import Optional

from flask import Blueprint, jsonify, render_template
from flask_login import login_required, current_user
from openai import OpenAI
from pydantic import BaseModel, ValidationError

# Import SQLAlchemy DB and models
from ..models import (
    db,
    PlanDeCours,
    Cours,
    AnalysePlanCoursPrompt
)
from ...utils.decorator import ensure_profile_completed
from ...utils.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Modèle Pydantic pour la réponse de PlanDeCours
# ---------------------------------------------------------------------------
class PlanDeCoursAIResponse(BaseModel):
    """
    Représente la structure retournée par l'IA pour la vérification
    d'un plan de cours (compatibility_percentage, recommendations, etc.).
    """
    compatibility_percentage: Optional[float] = None
    recommendation_ameliore: Optional[str] = None
    recommendation_plan_cadre: Optional[str] = None

# ---------------------------------------------------------------------------
# Import de la nouvelle fonction de tarification
# ---------------------------------------------------------------------------
from ...utils.openai_pricing import calculate_call_cost

# ---------------------------------------------------------------------------
# Blueprint et route de vérification
# ---------------------------------------------------------------------------
gestion_programme_bp = Blueprint('gestion_programme', __name__, url_prefix='/gestion_programme')

# Route existante pour afficher la gestion des plans de cours
@gestion_programme_bp.route('/', methods=['GET'])
@login_required
@ensure_profile_completed
def gestion_programme():
    user_program_ids = [programme.id for programme in current_user.programmes]
    plans = PlanDeCours.query.join(Cours).filter(
        Cours.programme_id.in_(user_program_ids)
    ).all()
    return render_template('gestion_programme/gestion_programme.html', plans=plans)

# Route GET pour récupérer les données de vérification existantes
@gestion_programme_bp.route('/get_verifier_plan_cours/<int:plan_id>', methods=['GET'])
@login_required
@ensure_profile_completed
def get_verifier_plan_cours(plan_id):
    plan = PlanDeCours.query.get_or_404(plan_id)

    # Vérifier les permissions de l'utilisateur
    if current_user.role not in ['admin', 'coordo']:
        return jsonify({'error': "Vous n'avez pas les droits nécessaires pour vérifier ce plan de cours."}), 403

    # Récupérer les données de vérification existantes
    compatibility_percentage = plan.compatibility_percentage if plan.compatibility_percentage is not None else 'N/A'
    recommendation_ameliore = plan.recommendation_ameliore if plan.recommendation_ameliore else 'N/A'
    recommendation_plan_cadre = plan.recommendation_plan_cadre if plan.recommendation_plan_cadre else 'N/A'

    return jsonify({
        'compatibility_percentage': compatibility_percentage,
        'recommendation_ameliore': recommendation_ameliore,
        'recommendation_plan_cadre': recommendation_plan_cadre
    })

@gestion_programme_bp.route('/update_verifier_plan_cours/<int:plan_id>', methods=['POST'])
@login_required
@ensure_profile_completed
def update_verifier_plan_cours(plan_id):
    """
    Vérifie un plan de cours en un seul appel gpt-5
    et met à jour les champs de vérification.
    """
    plan = PlanDeCours.query.get_or_404(plan_id)

    # Vérifier les permissions
    if current_user.role not in ['admin', 'coordo']:
        return jsonify({'error': "Vous n'avez pas les droits nécessaires pour vérifier ce plan de cours."}), 403

    # Récupérer l'openai_key et les crédits de l'utilisateur
    openai_key = current_user.openai_key
    user_credits = current_user.credits

    if not openai_key:
        return jsonify({'error': "Aucune clé OpenAI dans votre profil."}), 400

    # Données à envoyer dans le prompt
    schema_json = json.dumps(PlanDeCoursAIResponse.schema(), indent=4, ensure_ascii=False)

    plan_de_cours = PlanDeCours.query.get_or_404(plan_id)
    plan_cadre = plan_de_cours.cours.plan_cadre

    # Récupérer le template de prompt en BD
    prompt_template = AnalysePlanCoursPrompt.query.first()
    if not prompt_template:
        return jsonify({'error': "Le template de prompt n'est pas configuré."}), 500

    # Formater le prompt avec les variables
    instruction = prompt_template.prompt_template.format(
        plan_cours_id=plan_de_cours.id,
        plan_cours_json=json.dumps(plan_de_cours.to_dict(), indent=4, ensure_ascii=False),
        plan_cadre_id=plan_cadre.id,
        plan_cadre_json=json.dumps(plan_cadre.to_dict(), indent=4, ensure_ascii=False),
        schema_json=schema_json
    )

    structured_request = {
        "instruction": instruction
    }

    # Construction du client identique au plan-cadre
    client = OpenAI(api_key=openai_key)

    total_prompt_tokens = 0
    total_completion_tokens = 0

    # Appel unique: gpt-5
    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-5",
            messages=[{"role": "user", "content": json.dumps(structured_request)}],
            response_format=PlanDeCoursAIResponse,
        )
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return jsonify({'error': f"Erreur API OpenAI: {str(e)}"}), 500

    # Tokens et coût
    usage_prompt = completion.usage.prompt_tokens if hasattr(completion, 'usage') else 0
    usage_completion = completion.usage.completion_tokens if hasattr(completion, 'usage') else 0
    total_prompt_tokens += usage_prompt
    total_completion_tokens += usage_completion
    total_cost = calculate_call_cost(usage_prompt, usage_completion, "gpt-5")
    print(f"Appel gpt-5: {total_cost:.6f}$ (prompt {usage_prompt}, completion {usage_completion})")

    # Vérifier si l'utilisateur a suffisamment de crédits
    new_credits = user_credits - total_cost
    if new_credits < 0:
        return jsonify({"error": "Crédits insuffisants pour cet appel."}), 400

    # Mettre à jour les crédits
    current_user.credits = new_credits
    db.session.commit()

    # ----------------------------------------------------------
    # 3) Parser et mettre à jour le plan de cours avec la réponse finale
    # ----------------------------------------------------------
    if hasattr(completion.choices[0].message, 'parsed'):
        ai_response = completion.choices[0].message.parsed
    else:
        content = completion.choices[0].message.content if completion.choices else ""
        try:
            ai_response = PlanDeCoursAIResponse.parse_raw(content)
        except ValidationError as e:
            logger.error(f"Validation Pydantic error: {e}")
            return jsonify({'error': "Erreur de structuration des données par l'IA."}), 500

    # Mise à jour du plan avec les données de l'IA
    plan.compatibility_percentage = ai_response.compatibility_percentage
    plan.recommendation_ameliore = ai_response.recommendation_ameliore
    plan.recommendation_plan_cadre = ai_response.recommendation_plan_cadre

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la mise à jour du plan après IA: {e}")
        return jsonify({'error': "Erreur lors de la mise à jour du plan après IA."}), 500

    return jsonify({
        'compatibility_percentage': plan.compatibility_percentage,
        'recommendation_ameliore': plan.recommendation_ameliore,
        'recommendation_plan_cadre': plan.recommendation_plan_cadre
    })

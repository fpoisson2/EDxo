# gestion_programme.py

import time
import json
import logging
from typing import Optional
from datetime import datetime
import time 

from flask import Flask, Blueprint, jsonify, redirect, url_for, flash, request, render_template
from flask_login import login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from utils.decorator import role_required, roles_required, ensure_profile_completed
from sqlalchemy import text
from pydantic import BaseModel, ValidationError

# Import SQLAlchemy DB and models
from app.models import (
    db,
    User,
    PlanCadre,
    PlanCadreCapacites,
    PlanCadreCapaciteSavoirsNecessaires,
    PlanCadreCapaciteSavoirsFaire,
    PlanCadreCapaciteMoyensEvaluation,
    PlanCadreSavoirEtre,
    PlanCadreObjetsCibles,
    PlanCadreCoursRelies,
    PlanCadreCoursPrealables,
    PlanCadreCoursCorequis,
    PlanCadreCompetencesCertifiees,
    PlanCadreCompetencesDeveloppees,
    Cours,
    CoursPrealable,
    CoursCorequis,
    GlobalGenerationSettings,
    Competence,
    ElementCompetence,
    ElementCompetenceParCours,
    PlanDeCours,
    Cours,
    AnalysePlanCoursPrompt
)

from openai import OpenAI
from openai import OpenAIError

# ---------------------------------------------------------------------------
# Configuration Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.ERROR,
    filename='app_errors.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
from utils.openai_pricing import calculate_call_cost

# ---------------------------------------------------------------------------
# Blueprint et route de vérification
# ---------------------------------------------------------------------------
gestion_programme_bp = Blueprint('gestion_programme', __name__, url_prefix='/gestion_programme')

# Route existante pour afficher la gestion des plans de cours
@gestion_programme_bp.route('/', methods=['GET'])
@login_required
@ensure_profile_completed
def gestion_programme():
    plans = PlanDeCours.query.join(Cours).all()
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
    Route qui illustre l'approche en deux appels :
      - Premier appel (o1-preview ou tout autre modèle O1)
      - Deuxième appel (gpt-4o)
    en suivant exactement la structure de plan-cadre.
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

    # ----------------------------------------------------------
    # 1) Premier appel : model = "o3-mini" (ou autre modèle O1)
    # ----------------------------------------------------------
    ai_model = "o3-mini"  # Correction : chaîne de caractères

    try:
        o1_response = client.beta.chat.completions.parse(
            model=ai_model,
            messages=[{"role": "user", "content": json.dumps(structured_request)}]
        )
    except Exception as e:
        logging.error(f"OpenAI error (premier appel): {e}")
        return jsonify({'error': f"Erreur API OpenAI premier appel: {str(e)}"}), 500

    # Récupérer les tokens du premier appel
    if hasattr(o1_response, 'usage'):
        total_prompt_tokens += o1_response.usage.prompt_tokens
        total_completion_tokens += o1_response.usage.completion_tokens

    o1_response_content = (
        o1_response.choices[0].message.content if o1_response.choices else ""
    )

    print(o1_response_content)
    # ----------------------------------------------------------
    # 2) Deuxième appel : model = "gpt-4o"
    # ----------------------------------------------------------
    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Formatte selon PlanDeCoursAIResponse ce qui suit: {o1_response_content}"
                    )
                }
            ],
            response_format=PlanDeCoursAIResponse,
        )
    except Exception as e:
        logging.error(f"OpenAI error (second appel): {e}")
        return jsonify({'error': f"Erreur API OpenAI second appel: {str(e)}"}), 500

    # Récupérer les tokens du deuxième appel
    if hasattr(completion, 'usage'):
        total_prompt_tokens += completion.usage.prompt_tokens
        total_completion_tokens += completion.usage.completion_tokens

    # ----------------------------------------------------------
    # Calculer le coût total
    # ----------------------------------------------------------
    usage_1_prompt = o1_response.usage.prompt_tokens if hasattr(o1_response, 'usage') else 0
    usage_1_completion = o1_response.usage.completion_tokens if hasattr(o1_response, 'usage') else 0
    cost_first_call = calculate_call_cost(usage_1_prompt, usage_1_completion, ai_model)

    usage_2_prompt = completion.usage.prompt_tokens if hasattr(completion, 'usage') else 0
    usage_2_completion = completion.usage.completion_tokens if hasattr(completion, 'usage') else 0
    cost_second_call = calculate_call_cost(usage_2_prompt, usage_2_completion, "gpt-4o")

    total_cost = cost_first_call + cost_second_call

    print(f"Premier appel ({ai_model}): {cost_first_call:.6f}$ "
          f"({usage_1_prompt} prompt, {usage_1_completion} completion)")
    print(f"Second appel (gpt-4o): {cost_second_call:.6f}$ "
          f"({usage_2_prompt} prompt, {usage_2_completion} completion)")
    print(f"Coût total: {total_cost:.6f}$")

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
    second_response_content = completion.choices[0].message.content if completion.choices else ""
    print(second_response_content)

    if hasattr(completion.choices[0].message, 'parsed'):
        ai_response = completion.choices[0].message.parsed
    else:
        try:
            ai_response = PlanDeCoursAIResponse.parse_raw(second_response_content)
        except ValidationError as e:
            logging.error(f"Validation Pydantic error: {e}")
            return jsonify({'error': "Erreur de structuration des données par l'IA."}), 500

    # Mise à jour du plan avec les données de l'IA
    plan.compatibility_percentage = ai_response.compatibility_percentage
    plan.recommendation_ameliore = ai_response.recommendation_ameliore
    plan.recommendation_plan_cadre = ai_response.recommendation_plan_cadre

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Erreur lors de la mise à jour du plan après IA: {e}")
        return jsonify({'error': "Erreur lors de la mise à jour du plan après IA."}), 500

    return jsonify({
        'compatibility_percentage': plan.compatibility_percentage,
        'recommendation_ameliore': plan.recommendation_ameliore,
        'recommendation_plan_cadre': plan.recommendation_plan_cadre
    })

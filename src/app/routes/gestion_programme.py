# gestion_programme.py

import json
from typing import Optional

from flask import Blueprint, jsonify, render_template
from flask_login import login_required, current_user
from openai import OpenAI
from pydantic import BaseModel, ValidationError, ConfigDict

# Import SQLAlchemy DB and models
from ..models import (
    db,
    PlanDeCours,
    Cours,
    AnalysePlanCoursPrompt,
    SectionAISettings
)
from ...utils.decorator import ensure_profile_completed
from ...utils.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Modèle Pydantic pour la réponse de PlanDeCours
# ---------------------------------------------------------------------------
def _postprocess_openai_schema(schema: dict) -> None:
    schema.pop('default', None)
    if '$ref' in schema:
        return
    if schema.get('type') == 'object' or 'properties' in schema:
        schema['additionalProperties'] = False
    props = schema.get('properties')
    if props:
        # OpenAI Responses JSON schema requires a 'required' array listing
        # every key present in 'properties', even if values may be null.
        # Align with the pattern used elsewhere in the project.
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
    plan = db.session.get(PlanDeCours, plan_id) or abort(404)

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
    """[Déprécié] Utiliser l'endpoint asynchrone /gestion_programme/analyse_plan_de_cours/<id>/start.

    Cette route est conservée temporairement pour compatibilité et renvoie 410.
    """
    return jsonify({
        'error': "Endpoint déprécié. Utiliser /gestion_programme/analyse_plan_de_cours/<id>/start",
        'replacement': f"/gestion_programme/analyse_plan_de_cours/{plan_id}/start"
    }), 410


# ---------------------------------------------------------------------------
# Démarrage asynchrone (pattern unifié /tasks) pour l'analyse Plan de cours
# ---------------------------------------------------------------------------
from ..tasks.analyse_plan_de_cours import analyse_plan_de_cours_task


@gestion_programme_bp.route('/analyse_plan_de_cours/<int:plan_id>/start', methods=['POST'])
@login_required
@ensure_profile_completed
def start_analyse_plan_de_cours(plan_id):
    """Déclenche l'analyse du plan de cours en tâche Celery et retourne { task_id } (202)."""
    # Permissions identiques à la vérification synchronisée
    if current_user.role not in ['admin', 'coordo']:
        return jsonify({'error': "Vous n'avez pas les droits nécessaires pour vérifier ce plan de cours."}), 403
    # Existence minimale
    plan = db.session.get(PlanDeCours, plan_id) or abort(404)
    # Lancer la tâche en passant l'id utilisateur pour l'accès à la clé et crédits
    task = analyse_plan_de_cours_task.delay(plan.id, current_user.id)
    return jsonify({'task_id': task.id}), 202

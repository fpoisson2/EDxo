# gestion_programme.py

from flask import jsonify, Blueprint, request, render_template
from flask_login import login_required, current_user
from app.models import db, PlanDeCours, Cours  # Importez vos modèles appropriés
from datetime import datetime
import time  # Importez le module time pour ajouter un délai

gestion_programme_bp = Blueprint('gestion_programme', __name__, url_prefix='/gestion-programme')

# Route existante pour afficher la gestion des plans de cours
@gestion_programme_bp.route('/', methods=['GET'])
@login_required
def gestion_programme():
    plans = PlanDeCours.query.join(Cours).all()
    return render_template('gestion_programme/gestion_programme.html', plans=plans)

# Route GET pour récupérer les données de vérification existantes
@gestion_programme_bp.route('/get_verifier_plan_cours/<int:plan_id>', methods=['GET'])
@login_required
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

# Route POST pour lancer la vérification et mettre à jour les données
@gestion_programme_bp.route('/update_verifier_plan_cours/<int:plan_id>', methods=['POST'])
@login_required
def update_verifier_plan_cours(plan_id):
    plan = PlanDeCours.query.get_or_404(plan_id)

    # Vérifier les permissions de l'utilisateur
    if current_user.role not in ['admin', 'coordo']:
        return jsonify({'error': "Vous n'avez pas les droits nécessaires pour vérifier ce plan de cours."}), 403

    # Implémentez votre logique de vérification ici
    try:
        compatibility_percentage = 5
        recommendation_ameliore = "allo"
        recommendation_plan_cadre = "patate"
    except Exception as e:
        # En cas d'erreur dans les fonctions de calcul
        return jsonify({'error': f"Erreur lors du calcul des données de vérification: {str(e)}"}), 500

    # Simuler un délai pour tester le spinner de chargement
    time.sleep(5)  # Délai de 5 secondes

    # Mettre à jour le plan de cours avec les nouvelles données
    plan.compatibility_percentage = compatibility_percentage
    plan.recommendation_ameliore = recommendation_ameliore
    plan.recommendation_plan_cadre = recommendation_plan_cadre

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': "Erreur lors de la mise à jour des données de vérification."}), 500

    return jsonify({
        'compatibility_percentage': compatibility_percentage,
        'recommendation_ameliore': recommendation_ameliore,
        'recommendation_plan_cadre': recommendation_plan_cadre
    })

# Fonctions hypothétiques pour la logique de vérification
def calculate_compatibility(plan):
    """
    Calcule le pourcentage de compatibilité du plan de cours avec le plan-cadre.
    Remplacez cette logique par votre méthode réelle de calcul.
    """
    # Exemple de calcul statique
    return 85  # Pourcentage fictif

def generate_improvement_recommendation(plan):
    """
    Génère une recommandation pour améliorer le plan de cours.
    Remplacez cette logique par votre méthode réelle de génération.
    """
    # Exemple de recommandation statique
    return "Ajouter plus d'exemples pratiques dans le cours."

def generate_framework_recommendation(plan):
    """
    Génère une recommandation pour le plan-cadre.
    Remplacez cette logique par votre méthode réelle de génération.
    """
    # Exemple de recommandation statique
    return "Mettre à jour le plan-cadre avec les nouvelles directives."

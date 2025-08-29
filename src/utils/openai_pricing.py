import logging
from app.models import OpenAIModel

# Barèmes par défaut (USD / 1M tokens) utilisés en secours
# lorsqu'un modèle n'est pas encore enregistré en base.
# Ces valeurs servent de filet de sécurité pour éviter une 500.
# Mettez à jour via l'UI Admin dès que possible.
DEFAULT_PRICING = {
    # Famille gpt-5 uniquement
    "gpt-5": {"input": 5.00, "output": 15.00},
    "gpt-5-mini": {"input": 0.30, "output": 1.20},
    "gpt-5-nano": {"input": 0.05, "output": 0.20},
}
logger = logging.getLogger(__name__)

def calculate_call_cost(usage_prompt, usage_completion, model):
    """
    Calcule le coût d'un appel API en fonction du nombre de tokens et du modèle.
    """
    pricing = get_model_pricing(model)
    cost_input = usage_prompt * pricing["input"]/1000000
    cost_output = usage_completion * pricing["output"]/1000000
    return cost_input + cost_output
    
def get_all_models():
    """
    Retourne la liste de tous les modèles OpenAI enregistrés en base de données.
    """
    return OpenAIModel.query.all()

def get_model_pricing(model_name: str):
    """
    Récupère les tarifs d'un modèle OpenAI donné.
    
    :param model_name: Le nom du modèle (tel qu'enregistré dans la base de données).
    :return: Un dictionnaire contenant les tarifs en 'input' et 'output'.
    :raises ValueError: Si le modèle n'est pas trouvé.
    """
    # 1) Recherche en base
    model = OpenAIModel.query.filter_by(name=model_name).first()
    if model:
        return {"input": model.input_price, "output": model.output_price}

    # 2) Filet de sécurité: barème par défaut connu
    if model_name in DEFAULT_PRICING:
        logger.info(
            "Tarif du modèle '%s' absent de la base. Utilisation du barème par défaut.",
            model_name,
        )
        return DEFAULT_PRICING[model_name]

    # 3) Heuristique simple: si nom se termine par '-mini', caler sur gpt-5-mini
    if model_name.endswith("-mini") and "gpt-5-mini" in DEFAULT_PRICING:
        logger.info(
            "Tarif du modèle '%s' introuvable. Fallback heuristique sur 'gpt-5-mini'.",
            model_name,
        )
        return DEFAULT_PRICING["gpt-5-mini"]

    # 4) Heuristique pour la famille gpt-5 (et variantes)
    # Beaucoup de variantes (ex: gpt-5, gpt-5.1, gpt-5-preview) peuvent ne pas
    # être encore enregistrées en base. On cale par défaut sur gpt-5 pour éviter
    # une erreur 500 côté application, tout en journalisant le fallback.
    if model_name.startswith("gpt-5") and "gpt-5" in DEFAULT_PRICING:
        logger.info(
            "Tarif du modèle '%s' introuvable. Fallback heuristique sur 'gpt-5'.",
            model_name,
        )
        return DEFAULT_PRICING["gpt-5"]

    # Sinon: erreur explicite pour signaler un vrai manque de configuration
    raise ValueError(f"Modèle '{model_name}' non trouvé dans la base de données.")

from app.models import OpenAIModel

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
    model = OpenAIModel.query.filter_by(name=model_name).first()
    if not model:
        raise ValueError(f"Modèle '{model_name}' non trouvé dans la base de données.")
    return {"input": model.input_price, "output": model.output_price}
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from openai import OpenAI
from forms import ChatForm
from models import User, PlanCadre, db
import json

chat = Blueprint('chat', __name__)

def get_plan_cadre_function():
    """Définition de la fonction pour OpenAI"""
    print("[DEBUG] Defining plan cadre function")
    function_def = {
        "name": "get_plan_cadre",
        "description": "Récupère les informations complètes d'un plan-cadre à partir du nom ou du code d'un cours. Le plan-cadre contient les détails sur le contenu du cours, les objectifs, les évaluations, les compétences, et plus encore.",
        "parameters": {
            "type": "object",
            "properties": {
                "nom": {
                    "type": "string",
                    "description": "Nom complet ou partiel du cours (ex: 'Systèmes analogiques', 'Programmation')"
                },
                "code": {
                    "type": "string",
                    "description": "Code complet ou partiel du cours (ex: '243-2J5', '420')"
                }
            },
            "required": ["nom", "code"]
        },
        "return_info": {
            "description": "Retourne un objet contenant :",
            "fields": {
                "id": "Identifiant unique du plan-cadre",
                "cours": {
                    "description": "Informations de base sur le cours",
                    "fields": ["id", "nom", "code"]
                },
                "contenu": {
                    "description": "Contenu détaillé du cours",
                    "fields": {
                        "place_intro": "Introduction et place du cours",
                        "objectif_terminal": "Objectif terminal du cours",
                        "structure": [
                            "Introduction",
                            "Activités théoriques",
                            "Activités pratiques",
                            "Activités prévues"
                        ],
                        "evaluation": [
                            "Évaluation sommative",
                            "Nature des évaluations",
                            "Évaluation de la langue",
                            "Évaluation des apprentissages"
                        ]
                    }
                },
                "relations": {
                    "description": "Relations avec d'autres éléments",
                    "fields": {
                        "capacites": "Liste des capacités à développer",
                        "savoirs_etre": "Liste des savoirs-être",
                        "objets_cibles": "Objets d'apprentissage ciblés",
                        "cours_relies": "Cours en relation",
                        "cours_prealables": "Cours préalables requis",
                        "competences_certifiees": "Compétences certifiées",
                        "competences_developpees": "Compétences développées"
                    }
                }
            }
        }
    }
    print(f"[DEBUG] Function definition: {json.dumps(function_def, indent=2)}")
    return function_def

def handle_get_plan_cadre(params):
    """Gère l'appel à la fonction get_plan_cadre"""
    print(f"[DEBUG] handle_get_plan_cadre called with params: {params}")
    
    nom = params.get('nom')
    code = params.get('code')
    print(f"[DEBUG] Extracted nom={nom}, code={code}")
    
    plan_cadre = PlanCadre.get_by_cours_info(nom=nom, code=code)
    print(f"[DEBUG] Query result: {plan_cadre}")
    
    if plan_cadre:
        print(f"[DEBUG] Retrieved Cours: {plan_cadre.cours.nom} (ID: {plan_cadre.id})")
        result = {
            'id': plan_cadre.id,
            'cours': {
                'id': plan_cadre.cours.id,
                'nom': plan_cadre.cours.nom,
                'code': plan_cadre.cours.code
            },
            'contenu': {
                'place_intro': plan_cadre.place_intro,
                'objectif_terminal': plan_cadre.objectif_terminal,
                'structure': {
                    'introduction': plan_cadre.structure_intro,
                    'activites_theoriques': plan_cadre.structure_activites_theoriques,
                    'activites_pratiques': plan_cadre.structure_activites_pratiques,
                    'activites_prevues': plan_cadre.structure_activites_prevues
                },
                'evaluation': {
                    'sommative': plan_cadre.eval_evaluation_sommative,
                    'nature_evaluations': plan_cadre.eval_nature_evaluations_sommatives,
                    'evaluation_langue': plan_cadre.eval_evaluation_de_la_langue,
                    'evaluation_apprentissages': plan_cadre.eval_evaluation_sommatives_apprentissages
                }
            },
            'relations': {
                'capacites': [{
                    'id': c.id, 
                    'capacite': c.capacite,
                    'description': c.description_capacite,
                    'ponderation': {
                        'min': c.ponderation_min,
                        'max': c.ponderation_max
                    },
                    'savoirs_necessaires': [s.texte for s in c.savoirs_necessaires],
                    'savoirs_faire': [{
                        'texte': sf.texte,
                        'cible': sf.cible,
                        'seuil_reussite': sf.seuil_reussite
                    } for sf in c.savoirs_faire],
                    'moyens_evaluation': [m.texte for m in c.moyens_evaluation]
                } for c in plan_cadre.capacites],
                'savoirs_etre': [{'id': s.id, 'texte': s.texte} for s in plan_cadre.savoirs_etre],
                'objets_cibles': [{'id': o.id, 'texte': o.texte, 'description': o.description} for o in plan_cadre.objets_cibles],
                'cours_relies': [{'id': c.id, 'texte': c.texte, 'description': c.description} for c in plan_cadre.cours_relies],
                'cours_prealables': [{'id': c.id, 'texte': c.texte, 'description': c.description} for c in plan_cadre.cours_prealables],
                'competences_certifiees': [{'id': c.id, 'texte': c.texte, 'description': c.description} for c in plan_cadre.competences_certifiees],
                'competences_developpees': [{'id': c.id, 'texte': c.texte, 'description': c.description} for c in plan_cadre.competences_developpees]
            },
            'additional_info': plan_cadre.additional_info,
            'ai_model': plan_cadre.ai_model
        }
        print(f"[DEBUG] Returning full result: {json.dumps(result, indent=2)}")
        return result
    
    print("[DEBUG] No plan cadre found")
    return None

@chat.route('/chat')
@login_required
def index():
    print("[DEBUG] Accessing chat index route")
    form = ChatForm()
    return render_template('chat/index.html', form=form)


@chat.route('/chat/send', methods=['POST'])
@login_required
def send_message():
    print("[DEBUG] send_message route called")
    
    user = User.query.get(current_user.id)
    openai_key = user.openai_key if user else None
    
    if not openai_key:
        print("[DEBUG] No OpenAI key configured")
        return jsonify({'error': 'Clé OpenAI non configurée'}), 400

    form = ChatForm()
    if form.validate_on_submit():
        try:
            message = form.message.data
            print(f"[DEBUG] Received message: {message}")
            
            client = OpenAI(api_key=openai_key)
            
            edxo_function = {
                "role": "system",
                "content": "Vous êtes EDxo, un assistant spécialisé dans les informations pédagogiques liées aux programmes de cégep. Vous aidez à fournir des renseignements détaillés et des conseils en matière de gestion pédagogique."
            }

            # Premier appel à OpenAI pour identifier si on a besoin du plan-cadre
            print("[DEBUG] Sending initial request to OpenAI")
            initial_response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    edxo_function,
                    {"role": "user", "content": message}
                ],
                functions=[get_plan_cadre_function()]
            )
            
            initial_message = initial_response.choices[0].message
            
            # Si OpenAI demande des informations du plan-cadre
            if initial_message.function_call:
                print(f"[DEBUG] Function call detected: {initial_message.function_call}")
                args = json.loads(initial_message.function_call.arguments)
                func_result = handle_get_plan_cadre(args)
                
                if func_result:
                    # Deuxième appel à OpenAI avec le résultat du plan-cadre
                    print("[DEBUG] Sending follow-up request to OpenAI")
                    follow_up_response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "Vous devez fournir des réponses concises et ciblées, en vous concentrant uniquement sur les éléments spécifiquement demandés par l'utilisateur. Évitez d'inclure des informations supplémentaires non demandées."},
                            {"role": "user", "content": message},
                            {"role": "assistant", "content": None, "function_call": initial_message.function_call},
                            {"role": "function", "name": "get_plan_cadre", "content": json.dumps(func_result)}
                        ],
                        temperature=0.7  # Ajout d'un peu de température pour des réponses plus naturelles
                    )
                    
                    final_response = follow_up_response.choices[0].message.content
                    
                    response_data = {
                        'status': 'success',
                        'content': final_response,
                        'type': 'message',
                        'function_result': func_result  # Optionnel: garder les données brutes si nécessaire
                    }
                else:
                    response_data = {
                        'status': 'error',
                        'content': "Plan-cadre non trouvé",
                        'type': 'message'
                    }
                
                return jsonify(response_data)
            
            # Si pas de function call, retourner la réponse directe
            response_data = {
                'status': 'success',
                'content': initial_message.content,
                'type': 'message'
            }
            return jsonify(response_data)

        except Exception as e:
            error_msg = f"Erreur lors de l'envoi du message: {str(e)}"
            print(f"[DEBUG] General error: {error_msg}")
            current_app.logger.error(error_msg)
            return jsonify({'error': error_msg}), 500

    print("[DEBUG] Form validation failed")
    return jsonify({'error': 'Validation failed'}), 400
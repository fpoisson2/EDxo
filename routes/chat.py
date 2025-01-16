from flask import Blueprint, render_template, request, jsonify, current_app, Response, stream_with_context
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
    print("\n" + "="*50)
    print("DÉBUT DE LA REQUÊTE CHAT")
    print("="*50)
    
    # Vérification de la requête
    print("\n1. VÉRIFICATION DE LA REQUÊTE")
    print(f"Method: {request.method}")
    print(f"Content-Type: {request.headers.get('Content-Type')}")
    print(f"Data reçue: {request.get_json()}")
    
    # Vérification de l'utilisateur
    print("\n2. VÉRIFICATION DE L'UTILISATEUR")
    user = User.query.get(current_user.id)
    print(f"User ID: {current_user.id}")
    print(f"OpenAI Key présente: {'Oui' if user and user.openai_key else 'Non'}")
    
    if not user or not user.openai_key:
        print("❌ Pas de clé OpenAI")
        return jsonify({'error': 'Clé OpenAI non configurée'}), 400

    form = ChatForm()
    if form.validate_on_submit():
        try:
            message = form.message.data
            print(f"\n3. MESSAGE REÇU: {message}")
            
            client = OpenAI(api_key=user.openai_key)
            print("✅ Client OpenAI créé")
            
            def generate_stream():
                print("\n4. DÉBUT DU STREAMING")
                
                def send_event(event_type, content):
                    """Helper function to format SSE messages"""
                    data = json.dumps({"type": event_type, "content": content})
                    print(f"📤 Envoi SSE: {data}")
                    return f"data: {data}\n\n"
                
                try:
                    print("\n5. APPEL INITIAL À OPENAI")
                    initial_response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {
                                "role": "system",
                                "content": "Vous êtes EDxo, un assistant spécialisé dans les informations pédagogiques."
                            },
                            {"role": "user", "content": message}
                        ],
                        functions=[get_plan_cadre_function()],
                        stream=True
                    )
                    print("✅ Connexion au stream établie")
                    
                    yield send_event("processing", "Connexion établie...")
                    
                    function_call_data = None
                    function_args = ""
                    collected_content = ""
                    
                    print("\n6. TRAITEMENT DES CHUNKS")
                    for chunk_index, chunk in enumerate(initial_response):
                        print(f"\nChunk #{chunk_index}:")
                        print(f"Raw chunk: {chunk}")
                        
                        if not hasattr(chunk.choices[0], 'delta'):
                            print("⚠️ Pas de delta dans le chunk")
                            continue
                        
                        delta = chunk.choices[0].delta
                        print(f"Delta content: {delta}")
                        
                        # Gestion des function calls
                        if hasattr(delta, 'function_call') and delta.function_call is not None:
                            print("Function call détectée dans le delta")
                            if function_call_data is None and hasattr(delta.function_call, 'name'):
                                function_call_data = delta.function_call.name
                                print(f"Nom de la fonction: {function_call_data}")
                            if hasattr(delta.function_call, 'arguments'):
                                function_args += delta.function_call.arguments
                                print(f"Arguments ajoutés: {delta.function_call.arguments}")
                        
                        # Gestion du contenu normal
                        elif hasattr(delta, 'content') and delta.content:
                            print(f"Contenu reçu: {delta.content}")
                            collected_content += delta.content
                            yield send_event("content", delta.content)
                    
                    # Traitement de la function call si présente
                    if function_call_data and function_args:
                        print(f"\n7. TRAITEMENT FUNCTION CALL: {function_call_data}")
                        print(f"Arguments complets: {function_args}")
                        
                        try:
                            args = json.loads(function_args)
                            func_result = handle_get_plan_cadre(args)
                            
                            if func_result:
                                yield send_event("processing", "Recherche des informations du plan-cadre...")
                                
                                follow_up_response = client.chat.completions.create(
                                    model="gpt-4o-mini",
                                    messages=[
                                        {"role": "system", "content": "Vous devez fournir une réponse concise."},
                                        {"role": "user", "content": message},
                                        {"role": "assistant", "content": collected_content, 
                                         "function_call": {"name": function_call_data, "arguments": function_args}},
                                        {"role": "function", "name": "get_plan_cadre", "content": json.dumps(func_result)}
                                    ],
                                    stream=True
                                )
                                
                                for chunk in follow_up_response:
                                    if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                                        yield send_event("content", chunk.choices[0].delta.content)
                            else:
                                yield send_event("error", "Plan-cadre non trouvé")
                        except Exception as e:
                            print(f"❌ Erreur function call: {str(e)}")
                            yield send_event("error", str(e))
                    
                    yield send_event("done", "")
                    
                except Exception as e:
                    print(f"❌ Erreur stream: {str(e)}")
                    yield send_event("error", str(e))
                    yield send_event("done", "")

            print("\n10. PRÉPARATION DE LA RÉPONSE")
            response = Response(
                stream_with_context(generate_stream()),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'Content-Type': 'text/event-stream',
                    'X-Accel-Buffering': 'no'
                }
            )
            print("✅ Réponse prête à être envoyée")
            return response

        except Exception as e:
            error_msg = f"Erreur lors de l'envoi du message: {str(e)}"
            print(f"❌ Erreur générale: {error_msg}")
            current_app.logger.error(error_msg)
            return jsonify({'error': error_msg}), 500

    print("❌ Validation du formulaire échouée")
    return jsonify({'error': 'Validation failed'}), 400
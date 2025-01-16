from flask import Blueprint, render_template, request, jsonify, current_app, Response, stream_with_context, session
from flask_login import login_required, current_user
from openai import OpenAI
from forms import ChatForm
from models import User, PlanCadre, db, ChatHistory
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
    # Initialiser l'historique du chat s'il n'existe pas
    if 'chat_history' not in session:
        session['chat_history'] = []
        session.modified = True  # Marquer la session comme modifiée
    return render_template('chat/index.html', form=form)


# Dans routes/chat.py
@chat.route('/chat/send', methods=['POST'])
@login_required
def send_message():
    print("\n" + "="*50)
    print("DÉBUT DE LA REQUÊTE CHAT")
    print("="*50)
    
    # Récupération de l'historique depuis la base de données
    recent_messages = ChatHistory.get_recent_history(current_user.id)
    current_history = [
        {"role": msg.role, "content": msg.content}
        for msg in reversed(recent_messages)  # Inverser pour avoir l'ordre chronologique
    ]
    
    print("\nHISTORIQUE ACTUEL:")
    print(json.dumps(current_history, indent=2))
    
    # Vérification de la requête
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({'error': 'Message manquant'}), 400
        
    message = data.get('message')
    print(f"\nMESSAGE REÇU: {message}")
    
    # Vérification de l'utilisateur
    user = User.query.get(current_user.id)
    if not user or not user.openai_key:
        return jsonify({'error': 'Clé OpenAI non configurée'}), 400
        
    client = OpenAI(api_key=user.openai_key)
    
    def generate_stream():
        try:
            # Création des messages avec l'historique actuel
            messages = [
                {
                    "role": "system",
                    "content": "Vous êtes EDxo, un assistant spécialisé dans les informations pédagogiques."
                }
            ]
            messages.extend(current_history)
            messages.append({"role": "user", "content": message})
            
            # Sauvegarde du message utilisateur dans la BD
            new_message = ChatHistory(user_id=current_user.id, role="user", content=message)
            db.session.add(new_message)
            db.session.commit()
            
            # Premier appel à OpenAI
            initial_response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                functions=[get_plan_cadre_function()],
                stream=True
            )
            
            function_call_data = None
            function_args = ""
            collected_content = ""
            
            for chunk in initial_response:
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    collected_content += content
                    yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                elif hasattr(chunk.choices[0].delta, 'function_call'):
                    if function_call_data is None and hasattr(chunk.choices[0].delta.function_call, 'name'):
                        function_call_data = chunk.choices[0].delta.function_call.name
                    if hasattr(chunk.choices[0].delta.function_call, 'arguments'):
                        function_args += chunk.choices[0].delta.function_call.arguments
            
            # Traitement de la function call
            if function_call_data and function_args:
                try:
                    args = json.loads(function_args)
                    result = handle_get_plan_cadre(args)
                    
                    if result:
                        follow_up_messages = messages.copy()
                        follow_up_messages.extend([
                            {
                                "role": "assistant",
                                "content": collected_content,
                                "function_call": {
                                    "name": function_call_data,
                                    "arguments": function_args
                                }
                            },
                            {
                                "role": "function",
                                "name": "get_plan_cadre",
                                "content": json.dumps(result)
                            }
                        ])
                        
                        follow_up_response = client.chat.completions.create(
                            model="gpt-4o",
                            messages=follow_up_messages,
                            stream=True
                        )
                        
                        follow_up_content = ""
                        for chunk in follow_up_response:
                            if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                                content = chunk.choices[0].delta.content
                                follow_up_content += content
                                yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                        
                        if follow_up_content:
                            # Sauvegarde de la réponse dans la BD
                            assistant_message = ChatHistory(
                                user_id=current_user.id,
                                role="assistant",
                                content=follow_up_content
                            )
                            db.session.add(assistant_message)
                            db.session.commit()
                    else:
                        error_msg = "Plan-cadre non trouvé"
                        assistant_message = ChatHistory(
                            user_id=current_user.id,
                            role="assistant",
                            content=error_msg
                        )
                        db.session.add(assistant_message)
                        db.session.commit()
                        yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
                        
                except Exception as e:
                    error_msg = f"Erreur: {str(e)}"
                    assistant_message = ChatHistory(
                        user_id=current_user.id,
                        role="assistant",
                        content=error_msg
                    )
                    db.session.add(assistant_message)
                    db.session.commit()
                    yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            else:
                # Sauvegarde de la réponse normale dans la BD
                if collected_content:
                    assistant_message = ChatHistory(
                        user_id=current_user.id,
                        role="assistant",
                        content=collected_content
                    )
                    db.session.add(assistant_message)
                    db.session.commit()
            
            print("\nHISTORIQUE FINAL:")
            recent_messages = ChatHistory.get_recent_history(current_user.id)
            final_history = [
                {"role": msg.role, "content": msg.content}
                for msg in reversed(recent_messages)
            ]
            print(json.dumps(final_history, indent=2))
            yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"
            
        except Exception as e:
            error_msg = f"Erreur: {str(e)}"
            print(f"Erreur dans generate_stream: {error_msg}")
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"
    
    return Response(
        stream_with_context(generate_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Content-Type': 'text/event-stream',
            'X-Accel-Buffering': 'no'
        }
    )
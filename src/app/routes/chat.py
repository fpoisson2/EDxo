import json

import tiktoken
from flask import Blueprint, render_template, request, current_app, Response, stream_with_context, session
from flask_login import login_required, current_user
from openai import OpenAI

from app.forms import ChatForm
from app.models import User, PlanCadre, PlanDeCours, Cours, db, ChatHistory
from utils.decorator import ensure_profile_completed
# Importez votre fonction pour récupérer la tarification depuis la BD
from utils.openai_pricing import calculate_call_cost

chat = Blueprint('chat', __name__)

def estimate_tokens_for_text(text, model="gpt-4o"):
    """Retourne une estimation du nombre de tokens d'un texte pur avec des prints de débogage."""
    print(f"[DEBUG] estimate_tokens_for_text() - Texte d'entrée : {text[:80]}...")
    print(f"[DEBUG] estimate_tokens_for_text() - Modèle demandé : {model}")
    
    try:
        encoding = tiktoken.encoding_for_model(model)
        print(f"[DEBUG] estimate_tokens_for_text() - Encodage sélectionné : {encoding.name}")
    except KeyError:
        print(f"[DEBUG] estimate_tokens_for_text() - ⚠️ Modèle '{model}' non trouvé. Sélection d'un encodage alternatif...")
        available_encodings = tiktoken.list_encoding_names()
        print(f"[DEBUG] estimate_tokens_for_text() - Encodages disponibles : {available_encodings}")
        encoding_name = "o200k_base" if "o200k_base" in available_encodings else "cl100k_base"
        encoding = tiktoken.get_encoding(encoding_name)
        print(f"[DEBUG] estimate_tokens_for_text() - Encodage de repli sélectionné : {encoding.name}")

    encoded_text = encoding.encode(text)
    print(f"[DEBUG] estimate_tokens_for_text() - Nombre de tokens : {len(encoded_text)}")
    return len(encoded_text)

# -------------------------------------------------------------------------
# Fonctions pour get_plan_de_cours
# -------------------------------------------------------------------------
def get_plan_de_cours_function():
    return {
        "name": "get_plan_de_cours",
        "description": (
            "Récupère les informations détaillées d'un plan de cours à partir "
            "du code du cours et, si fourni, de la session."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Code complet ou partiel du cours (ex: '243-2J5', '420')"
                },
                "session": {
                    "type": "string",
                    "description": (
                        "Session précise (ex: 'Hiver 2025', 'Automne 2024'). "
                        "Si non spécifié, prendre la plus récente disponible."
                    )
                }
            },
            "required": ["code"]
        },
    }

def handle_get_plan_de_cours(params):
    print(f"[DEBUG] handle_get_plan_de_cours() - Paramètres reçus : {params}")
    code = params.get("code", "").strip()
    session_str = params.get("session", "").strip()

    query = PlanDeCours.query.join(Cours).filter(Cours.code.ilike(f"%{code}%"))

    if session_str:
        print(f"[DEBUG] handle_get_plan_de_cours() - Filtrage par session '{session_str}'")
        query = query.filter(PlanDeCours.session.ilike(f"%{session_str}%"))
    else:
        print("[DEBUG] handle_get_plan_de_cours() - Aucune session spécifiée, on prend la plus récente.")
        query = query.order_by(PlanDeCours.session.desc())

    plan_de_cours = query.first()

    if plan_de_cours:
        print(f"[DEBUG] handle_get_plan_de_cours() - PlanDeCours trouvé : ID={plan_de_cours.id}, session={plan_de_cours.session}")
        return plan_de_cours.to_dict()
    else:
        print("[DEBUG] handle_get_plan_de_cours() - Aucun plan de cours trouvé.")
        return None

# -------------------------------------------------------------------------
# Fonctions pour get_plan_cadre
# -------------------------------------------------------------------------
def get_plan_cadre_function():
    return {
        "name": "get_plan_cadre",
        "description": (
            "Récupère un plan-cadre à partir du nom ou du code d'un cours. "
            "Le plan-cadre contient les détails sur le contenu, les objectifs, "
            "les évaluations, les compétences, etc."
        ),
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
    }

def handle_get_plan_cadre(params):
    print(f"[DEBUG] handle_get_plan_cadre() - Paramètres reçus : {params}")
    nom = params.get('nom', "")
    code = params.get('code', "")
    
    plan_cadre = PlanCadre.get_by_cours_info(nom=nom, code=code)
    print(f"[DEBUG] handle_get_plan_cadre() - Résultat de la requête : {plan_cadre}")
    
    if plan_cadre:
        print(f"[DEBUG] handle_get_plan_cadre() - PlanCadre trouvé : ID={plan_cadre.id}")
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
                'objets_cibles': [
                    {'id': o.id, 'texte': o.texte, 'description': o.description} 
                    for o in plan_cadre.objets_cibles
                ],
                'cours_relies': [
                    {'id': c.id, 'texte': c.texte, 'description': c.description} 
                    for c in plan_cadre.cours_relies
                ],
                'cours_prealables': [
                    {'id': c.id, 'texte': c.texte, 'description': c.description} 
                    for c in plan_cadre.cours_prealables
                ],
                'competences_certifiees': [
                    {'id': c.id, 'texte': c.texte, 'description': c.description} 
                    for c in plan_cadre.competences_certifiees
                ],
                'competences_developpees': [
                    {'id': c.id, 'texte': c.texte, 'description': c.description} 
                    for c in plan_cadre.competences_developpees
                ]
            },
            'additional_info': plan_cadre.additional_info,
            'ai_model': plan_cadre.ai_model
        }
        return result
    return None

# -------------------------------------------------------------------------
# NOUVELLES FONCTIONS : list_all_plan_de_cours & list_all_plan_cadre
# -------------------------------------------------------------------------
def list_all_plan_de_cours_function():
    return {
        "name": "list_all_plan_de_cours",
        "description": (
            "Retourne la liste de tous les plans de cours disponibles. "
            "Chaque élément contient les informations principales du plan de cours."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
    }

def handle_list_all_plan_de_cours():
    print("[DEBUG] handle_list_all_plan_de_cours() - Récupération de tous les plans de cours.")
    plans = PlanDeCours.query.all()
    result = []
    for plan in plans:
        result.append({
            "id": plan.id,
            "session": plan.session,
            "cours": plan.cours.code if plan.cours else None,
            # Ajoutez d'autres champs si nécessaire
        })
    return result

def list_all_plan_cadre_function():
    return {
        "name": "list_all_plan_cadre",
        "description": (
            "Retourne la liste de tous les plans-cadres disponibles. "
            "Chaque élément contient les informations principales du plan-cadre."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
    }

def handle_list_all_plan_cadre():
    print("[DEBUG] handle_list_all_plan_cadre() - Récupération de tous les plans-cadres.")
    plans = PlanCadre.query.all()
    result = []
    for plan in plans:
        result.append({
            "id": plan.id,
            "cours_id": plan.cours.id if plan.cours else None,
            "cours_code": plan.cours.code if plan.cours else None,
            "cours_nom": plan.cours.nom if plan.cours else None,
            # Ajoutez d'autres champs si nécessaire
        })
    return result

# -------------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------------
@chat.route('/chat')
@login_required
@ensure_profile_completed
def index():
    print("[DEBUG] Accessing chat index route.")
    form = ChatForm()
    if 'chat_history' not in session:
        print("[DEBUG] Initialisation de session['chat_history'].")
        session['chat_history'] = []
        session.modified = True
    return render_template('chat/index.html', form=form)

@chat.route('/chat/send', methods=['POST'])
@login_required
@ensure_profile_completed
def send_message():
    # --- Partie 1 : Vérifications (aucun yield ici) ---
    # On peut utiliser directement current_app ici puisque nous sommes dans le contexte de la requête
    app_obj = current_app  # pas besoin de _get_current_object() ici

    print("\n" + "=" * 50)
    print("[DEBUG] DÉBUT DE LA REQUÊTE /chat/send")
    print("=" * 50)
    
    # Récupération de l'utilisateur via Flask-Login
    try:
        user = current_user
    except Exception as e:
        print("[DEBUG] Erreur lors de la récupération de current_user:", str(e))
        user = None

    if user is None:
        print("[DEBUG] Erreur: current_user est None")
        return app_obj.response_class(
            response=json.dumps({'error': 'Utilisateur non authentifié'}),
            status=401,
            mimetype='application/json'
        )

    # Récupération de l'historique depuis la DB
    recent_messages = ChatHistory.get_recent_history(user.id)
    current_history = [
        {"role": msg.role, "content": msg.content}
        for msg in reversed(recent_messages)
    ]
    print("[DEBUG] Historique actuel (depuis DB):")
    for i, msg in enumerate(current_history, start=1):
        print(f"  {i}. {msg['role']} -> {msg['content'][:80]}...")

    data = request.get_json()
    if not data or 'message' not in data:
        print("[DEBUG] Erreur: 'message' est manquant dans la requête.")
        return app_obj.response_class(
            response=json.dumps({'error': 'Message manquant'}),
            status=400,
            mimetype='application/json'
        )

    # Vérification des crédits
    if user.credits is None:
        user.credits = 0.0
    if user.credits <= 0:
        print("[DEBUG] Erreur: Crédits insuffisants.")
        return app_obj.response_class(
            response=json.dumps({'error': 'Crédits insuffisants. Veuillez recharger votre compte.'}),
            status=403,
            mimetype='application/json'
        )

    message = data.get('message')
    print(f"[DEBUG] MESSAGE REÇU du front-end: {message}")

    # Vérification de la clé API OpenAI
    if not user.openai_key:
        print("[DEBUG] Erreur: Clé OpenAI non configurée pour l'utilisateur.")
        return app_obj.response_class(
            response=json.dumps({'error': 'Clé OpenAI non configurée'}),
            status=400,
            mimetype='application/json'
        )

    client = OpenAI(api_key=user.openai_key)

    # --- Partie 2 : Création du générateur de streaming ---
    def generate_stream():
        try:
            # On peut dès le début émettre un message "processing"
            yield f"data: {json.dumps({'type': 'processing', 'content': 'En attente d\'une réponse...'})}\n\n"

            # Construction des messages pour GPT
            messages = [
                {"role": "system", "content": "Vous êtes EDxo, un assistant spécialisé dans les informations pédagogiques."}
            ]
            messages.extend(current_history)
            messages.append({"role": "user", "content": message})
            
            # Sauvegarde du message utilisateur dans la DB
            new_message = ChatHistory(user_id=user.id, role="user", content=message)
            db.session.add(new_message)
            db.session.commit()

            model = "gpt-4o"
            prompt_text = "\n".join([msg["content"] for msg in messages])
            prompt_tokens = estimate_tokens_for_text(prompt_text, model)

            # Définition des fonctions disponibles pour GPT
            functions = [
                get_plan_cadre_function(),
                get_plan_de_cours_function(),
                list_all_plan_de_cours_function(),
                list_all_plan_cadre_function()
            ]
            
            print("[DEBUG] Envoi de la requête initiale à OpenAI avec fonctions disponibles.")
            initial_response = client.chat.completions.create(
                model=model,
                messages=messages,
                functions=functions,
                stream=True
            )
            
            output_chunks = []
            collected_content = ""
            function_call_data = None
            function_args = ""

            # Parcours du flux de la réponse initiale
            for chunk in initial_response:
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    output_chunks.append(content)
                    collected_content += content
                    yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                elif hasattr(chunk.choices[0].delta, "function_call"):
                    fc = chunk.choices[0].delta.function_call
                    if function_call_data is None and hasattr(fc, 'name'):
                        function_call_data = fc.name
                        yield f"data: {json.dumps({'type': 'function_call', 'content': 'Appel de fonction en cours...'})}\n\n"
                    if hasattr(fc, 'arguments'):
                        function_args += fc.arguments

            full_output = "".join(output_chunks)
            completion_tokens = estimate_tokens_for_text(full_output, model)
            total_cost_initial = calculate_call_cost(prompt_tokens, completion_tokens, model)
            print(f"[DEBUG] Coût estimé - prompt: {prompt_tokens:.6f}, output: {completion_tokens:.6f}, total: {total_cost_initial:.6f}")

            total_cost_follow_up = 0

            # Si une fonction a été appelée, on traite le résultat
            if function_call_data:
                print(f"[DEBUG] Une fonction a été appelée: {function_call_data}")
                try:
                    args = {}
                    if function_args.strip():
                        args = json.loads(function_args)
                    
                    if function_call_data == "get_plan_cadre":
                        result = handle_get_plan_cadre(args)
                    elif function_call_data == "get_plan_de_cours":
                        result = handle_get_plan_de_cours(args)
                    elif function_call_data == "list_all_plan_de_cours":
                        result = handle_list_all_plan_de_cours()
                    elif function_call_data == "list_all_plan_cadre":
                        result = handle_list_all_plan_cadre()
                    else:
                        print(f"[DEBUG] Nom de fonction inattendu: {function_call_data}")
                        result = None
                    
                    if result:
                        print(f"[DEBUG] Résultat de {function_call_data} obtenu, on relance GPT.")
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
                                "name": function_call_data,
                                "content": json.dumps(result)
                            }
                        ])

                        follow_up_response = client.chat.completions.create(
                            model=model,
                            messages=follow_up_messages,
                            stream=True
                        )
                        follow_up_chunks = []
                        follow_up_content = ""

                        for chunk in follow_up_response:
                            if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                                content = chunk.choices[0].delta.content
                                follow_up_chunks.append(content)
                                follow_up_content += content
                                yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                            elif hasattr(chunk.choices[0].delta, 'function_call'):
                                yield f"data: {json.dumps({'type': 'function_call', 'content': 'Appel de fonction en cours...'})}\n\n"

                        full_follow_up_output = "".join(follow_up_chunks)
                        completion_tokens_follow_up = estimate_tokens_for_text(full_follow_up_output, model)
                        total_cost_follow_up = calculate_call_cost(prompt_tokens, completion_tokens_follow_up, model)

                        # Sauvegarde de la réponse finale du bot
                        if follow_up_content:
                            assistant_message = ChatHistory(user_id=user.id, role="assistant", content=follow_up_content)
                            db.session.add(assistant_message)
                            db.session.commit()
                    else:
                        print(f"[DEBUG] La fonction {function_call_data} n'a rien retourné.")
                        no_result_msg = "Aucun résultat correspondant."
                        yield f"data: {json.dumps({'type': 'content', 'content': no_result_msg})}\n\n"

                except Exception as err:
                    error_msg = f"[DEBUG] Erreur lors du traitement de la fonction: {str(err)}"
                    print(error_msg)
                    yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            
            total_cost_global = round(total_cost_initial + total_cost_follow_up, 6)
            print(f"[DEBUG] Coût total combiné : {total_cost_global:.6f}")
            
            # Mise à jour des crédits de l'utilisateur
            try:
                updated_user = db.session.get(User, user.id)
                if updated_user.credits is None:
                    updated_user.credits = 0.0
                updated_user.credits = round(updated_user.credits - total_cost_global, 6)
                db.session.commit()
                print(f"[DEBUG] Crédit utilisateur mis à jour. Nouveau solde: {updated_user.credits}")
            except Exception as err:
                print(f"[DEBUG] ❌ Erreur lors de la mise à jour du crédit: {str(err)}")
            
            yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"
            
        except Exception as err:
            error_msg = f"[DEBUG] Exception globale dans generate_stream(): {str(err)}"
            print(error_msg)
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"

    # --- Partie 3 : Retour de la réponse SSE ---
    print("[DEBUG] Retour d'une Response SSE (Server-Sent Events).")
    return Response(
        stream_with_context(generate_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Content-Type': 'text/event-stream',
            'X-Accel-Buffering': 'no'
        }
    )


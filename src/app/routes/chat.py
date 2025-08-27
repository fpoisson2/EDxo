# chat.py – Responses API + DEBUG (SDK 1.23 → ≥1.25) - WITH ADDED LOGGING
import json, pprint, tiktoken, logging
from flask import Blueprint, render_template, request, Response, stream_with_context, session, current_app
from flask_login import login_required, current_user
from openai import OpenAI, OpenAIError
import itertools

# Configure basic logging if you prefer over print statements
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
# logger = logging.getLogger(__name__)
# Use logger.debug(...) instead of print(...) if using logging module

# ─── évènements texte ───────────────────────────────────────────
try:
    from openai.types.responses import ResponseTextBlockDeltaEvent
    TEXT_EVENTS = (ResponseTextBlockDeltaEvent,)
except ImportError:
    from openai.types.responses import ResponseTextDeltaEvent
    TEXT_EVENTS = (ResponseTextDeltaEvent,)

# ─── évènements function_call (SDK ≥ 1.25) ─────────────────────
try:
    from openai.types.responses import (
        ResponseOutputItemAddedEvent,
        ResponseOutputItemDoneEvent,
    )
    OUTPUT_ITEM_EVENTS = (ResponseOutputItemAddedEvent, ResponseOutputItemDoneEvent)
    TEXT_EVENTS += (ResponseOutputItemAddedEvent,)
except ImportError:
    OUTPUT_ITEM_EVENTS = ()

from openai.types.responses import ResponseFunctionCallArgumentsDeltaEvent
try:
    from openai.types.responses import ResponseCreatedEvent
except ImportError:
    ResponseCreatedEvent = None
try:
    # Added ResponseCompletedEvent for better ID handling logic check
    from openai.types.responses import ResponseCompletedEvent
except ImportError:
    ResponseCompletedEvent = None


from openai.types.responses import ResponseFunctionToolCall  # ← Fallback

from ..forms import ChatForm
from ..models import User, PlanCadre, PlanDeCours, Cours, db, ChatHistory, ChatModelConfig

from ...utils.decorator import ensure_profile_completed
from ...utils.openai_pricing import calculate_call_cost

chat = Blueprint("chat", __name__)

def extract_text(ev):
    """Return ONLY assistant output_text, never reasoning text.

    We filter by event type to avoid treating reasoning summary deltas as normal content.
    """
    etype = getattr(ev, 'type', '') or ''
    # Ignore any reasoning-related events
    if 'reasoning' in etype:
        return None

    # Output text delta events (Responses API)
    if hasattr(ev, 'delta') and isinstance(ev.delta, str):
        # Only accept if the event type clearly indicates output text delta
        if 'output_text.delta' in etype:
            return ev.delta
        # Otherwise ignore (likely a non-text or reasoning delta)
        return None

    # Some SDKs emit items with a type; only accept output_text items
    item = getattr(ev, 'item', None)
    if item is not None:
        itype = getattr(item, 'type', '') or ''
        if itype == 'output_text':
            return getattr(item, 'text', None)
        return None

    return None

def _collect_summary(items):
    """Concatenate summary_text blocks from Responses API event payloads."""
    text = ""
    if not items:
        return text
    if not isinstance(items, (list, tuple)):
        items = [items]
    for item in items:
        if getattr(item, "type", "") == "summary_text":
            text += getattr(item, "text", "")
    return text


# ─── token util ─────────────────────────────────────────────────
def estimate_tokens_for_text(txt: str, model=None):
    if model is None:
        model = current_app.config.get("OPENAI_MODEL_SECTION")
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(txt))

# ─── TOOLS (schéma strict) ─────────────────────────────────────
def get_plan_de_cours_function():
    return {"type": "function","name": "get_plan_de_cours","description": "Récupère un plan de cours.",
            "parameters": {"type": "object","properties": {"code": {"type": "string"}}, "required": ["code"],
                           "additionalProperties": False}, "strict": True}

def get_plan_cadre_function():
    return {"type": "function","name": "get_plan_cadre","description": "Récupère un plan-cadre.",
            "parameters": {"type": "object","properties": {"nom": {"type": "string"}, "code": {"type": "string"}},
                           "required": ["nom","code"],"additionalProperties": False},"strict": True}

def get_multiple_plan_cadre_function():
    return {"type": "function","name": "get_multiple_plan_cadre","description": "Récupère plusieurs plans-cadres.",
            "parameters": {"type": "object","properties": {"codes": {"type": "array","items": {"type": "string"}}},
                           "required": ["codes"],"additionalProperties": False},"strict": True}

def list_all_plan_cadre_function():
    return {"type": "function","name": "list_all_plan_cadre","description": "Liste tous les plans-cadres.",
            "parameters": {"type": "object","properties": {}, "required": [],"additionalProperties": False},"strict": True}

def list_all_plan_de_cours_function():
    return {"type": "function","name": "list_all_plan_de_cours","description": "Liste tous les plans de cours.",
            "parameters": {"type": "object","properties": {}, "required": [],"additionalProperties": False},"strict": True}


# --- TOOL HANDLERS ---
def handle_get_plan_de_cours(params):
    print(f"[DEBUG LOG] Entered handle_get_plan_de_cours with params: {params}")
    code = params.get("code", "").strip()
    session_str = params.get("session", "").strip()

    query = PlanDeCours.query.join(Cours).filter(Cours.code.ilike(f"%{code}%"))

    if session_str:
        print(f"[DEBUG LOG] handle_get_plan_de_cours() - Filtrage par session '{session_str}'")
        query = query.filter(PlanDeCours.session.ilike(f"%{session_str}%"))
    else:
        print("[DEBUG LOG] handle_get_plan_de_cours() - Aucune session spécifiée, on prend la plus récente.")
        query = query.order_by(PlanDeCours.session.desc())

    plan_de_cours = query.first()

    if plan_de_cours:
        print(f"[DEBUG LOG] handle_get_plan_de_cours() - PlanDeCours trouvé : ID={plan_de_cours.id}, session={plan_de_cours.session}")
        return plan_de_cours.to_dict() # Assurez-vous que to_dict() existe et est sérialisable en JSON
    else:
        print("[DEBUG LOG] handle_get_plan_de_cours() - Aucun plan de cours trouvé.")
        return None

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


def handle_get_multiple_plan_cadre(params):
    """
    Permet de récupérer plusieurs plans-cadres à partir d'une liste
    de codes de cours. Retourne un tableau de dictionnaires complets
    (similaire à handle_get_plan_cadre).
    """
    print(f"[DEBUG] handle_get_multiple_plan_cadre() - Paramètres reçus : {params}")
    codes = params.get('codes', [])

    results = []
    for code in codes:
        # Ex.: on recherche par code partiel, d'où le '%{code}%'
        plan_cadre = (PlanCadre.query
                                  .join(Cours)
                                  .filter(Cours.code.ilike(f"%{code}%"))
                                  .first())

        if plan_cadre:
            print(f"[DEBUG] handle_get_multiple_plan_cadre() - PlanCadre trouvé : ID={plan_cadre.id} pour code={code}")

            # Construire la réponse détaillée, comme dans handle_get_plan_cadre
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
                    'savoirs_etre': [
                        {'id': s.id, 'texte': s.texte} 
                        for s in plan_cadre.savoirs_etre
                    ],
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
            results.append(result)
        else:
            print(f"[DEBUG] handle_get_multiple_plan_cadre() - Aucun plan-cadre trouvé pour code={code}")
            results.append({
                'code': code,
                'error': 'Aucun plan-cadre trouvé pour ce code'
            })

    return results


def handle_list_all_plan_de_cours():
    print(f"[DEBUG LOG] Entered handle_list_all_plan_de_cours")
    plans = PlanDeCours.query.all()
    result = []
    for plan in plans:
        result.append({
            "id": plan.id,
            "session": plan.session,
            "cours": plan.cours.code if plan.cours else None,
        })
    print(f"[DEBUG LOG] handle_list_all_plan_de_cours - Found {len(result)} plans.")
    return result


def handle_list_all_plan_cadre():
    print(f"[DEBUG LOG] Entered handle_list_all_plan_cadre")
    plans = PlanCadre.query.all()
    result = []
    for plan in plans:
        result.append({
            "id": plan.id,
            "cours_id": plan.cours.id if plan.cours else None,
            "cours_code": plan.cours.code if plan.cours else None,
            "cours_nom": plan.cours.nom if plan.cours else None,
        })
    print(f"[DEBUG LOG] handle_list_all_plan_cadre - Found {len(result)} plans.")
    return result

# --- UPDATED ID Management ---
# Centralized function to manage ID based on events
def maybe_store_id(ev):
    # Ensure imports are available
    from openai.types.responses import ResponseCreatedEvent, ResponseCompletedEvent

    current_id_before = session.get("last_response_id") # Get ID before potential change
    new_id = None
    event_type = ev.__class__.__name__ if hasattr(ev, '__class__') else type(ev).__name__
    response_id = getattr(getattr(ev, 'response', None), 'id', None) # Safely get response ID

    if not response_id:
        # print(f"[DEBUG LOG] maybe_store_id ({event_type}): Event has no response ID. Skipping.")
        return # Cannot store if event has no response.id

    if isinstance(ev, ResponseCreatedEvent):
        new_id = response_id
        session["last_response_id"] = new_id
        session.modified = True
        print(f"[DEBUG LOG] maybe_store_id ({event_type}): Set last_response_id. Before='{current_id_before}', New='{new_id}'")
    elif isinstance(ev, ResponseCompletedEvent) and ResponseCompletedEvent is not None:
        # Check output type condition
        is_function_call = False
        # Check if output exists and the first item's type is function_call
        if ev.response and hasattr(ev.response, 'output') and ev.response.output:
             output_item_1 = ev.response.output[0]
             if hasattr(output_item_1, "type"):
                  is_function_call = (getattr(output_item_1, "type", "") == "function_call")

        print(f"[DEBUG LOG] maybe_store_id ({event_type}): Completed ID='{response_id}'. Final output[0] is function call: {is_function_call}.")

        if not is_function_call: # Update only if not ending with a function call
            new_id = response_id
            session["last_response_id"] = new_id
            session.modified = True
            print(f"[DEBUG LOG] maybe_store_id ({event_type}): Confirmed/Set last_response_id (not function call). Before='{current_id_before}', New='{new_id}'")
        else:
            # Log that we are *not* updating because it's a function call completion
            print(f"[DEBUG LOG] maybe_store_id ({event_type}): NOT updating last_response_id on completion because output[0] is function call. ID remains '{current_id_before}'.")
    # else:
    #     # Optionally log other event types if needed for deeper debugging
    #     print(f"[DEBUG LOG] maybe_store_id ({event_type}): Did not match Created/Completed event. ID='{response_id}'. No action.")

# --- Safe Stream Wrapper ---
# (safe_openai_stream reste majoritairement inchangé, mais on lira l'ID depuis current_user maintenant)
def safe_openai_stream(**kwargs):
    """Appelle l'API et, si erreur « No tool output », ré-essaye sans prev_id."""
    # Note: La logique de pop session est enlevée ici car on gère via DB
    print(f"[DEBUG LOG] safe_openai_stream: Attempting API call with kwargs (partial): model={kwargs.get('model')}, prev_id={kwargs.get('previous_response_id')}")
    try:
        client = OpenAI(api_key=current_user.openai_key)
        return client.responses.create(**kwargs, stream=True)
    except OpenAIError as e:
        print(f"[ERROR LOG] safe_openai_stream: Encountered OpenAIError: {e}")
        # Gérer l'erreur spécifique en N'UTILISANT PAS l'ID fautif lors de la relance
        if "No tool output found for function call" in str(e) and kwargs.get("previous_response_id"):
            import re
            faulty_id = kwargs.get('previous_response_id')
            # Try to recover by emitting a minimal error output for the pending tool call
            m = re.search(r"function call (call_[A-Za-z0-9]+)", str(e))
            if m:
                call_id = m.group(1)
                print(f"[RETRY] safe_openai_stream: Re-emitting minimal tool error for call_id={call_id} with previous_response_id={faulty_id}")
                client = OpenAI(api_key=current_user.openai_key)
                text_params = kwargs.get("text") or {"format": {"type": "text"}}
                follow_kwargs = dict(
                    model=kwargs.get("model"),
                    previous_response_id=faulty_id,
                    input=[{"type": "function_call_output", "call_id": call_id, "output": json.dumps({"error": "tool failed"})}],
                    tool_choice="auto",
                    text=text_params,
                    stream=True,
                )
                if "temperature" in kwargs:
                    follow_kwargs["temperature"] = kwargs["temperature"]
                if "max_output_tokens" in kwargs:
                    follow_kwargs["max_output_tokens"] = kwargs["max_output_tokens"]
                if "reasoning" in kwargs:
                    follow_kwargs["reasoning"] = kwargs["reasoning"]
                return client.responses.create(**follow_kwargs)
            # If we can't parse call_id, last resort: start new thread
            print(f"[DEBUG LOG] safe_openai_stream: Could not parse call_id from error. Starting a new thread without previous_response_id.")
            kwargs["previous_response_id"] = None
            client = OpenAI(api_key=current_user.openai_key)
            return client.responses.create(**kwargs, stream=True)
        print(f"[ERROR LOG] safe_openai_stream: Error not handled by specific clause, re-raising.")
        raise
@chat.route("/chat")
@login_required
@ensure_profile_completed
def index():
    """Reset conversation state on page load and render the chat interface."""

    # Supprime tout ID de réponse précédent côté session pour repartir à zéro.
    session.pop("last_response_id", None)
    session.modified = True

    # Réinitialise l'ID de réponse persistant en base de données.
    try:
        current_user.last_openai_response_id = None
        db.session.commit()
        print("[DB LOG] Cleared last_openai_response_id for user on /chat load.")
    except Exception as db_err:
        db.session.rollback()
        current_app.logger.error(
            "Failed to clear last_openai_response_id in DB on /chat load: %s",
            db_err,
        )

    cfg = ChatModelConfig.get_current()
    current_model = (cfg.chat_model or "gpt-5-mini") if cfg else "gpt-5-mini"
    prev_id = current_user.last_openai_response_id
    return render_template(
        "chat/index.html",
        form=ChatForm(),
        chat_model_name=current_model,
        previous_response_id=prev_id,
    )

# ────────────────────────────────────────────────────────────────
#  Route /chat/send - MODIFIED TO INCLUDE HISTORY
# ----------------------------------------------------------------
@chat.route("/chat/send", methods=["POST"])
@login_required
@ensure_profile_completed
def send_message():
    print(f"\n[DEBUG LOG] === New /chat/send request received (API Responses + ChatHistory Log) ===")
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg: # (gestion message vide)
        print("[WARN LOG] Empty user message received.")
        return Response("Empty message", 400)
    print(f"[DEBUG LOG] User message: '{user_msg}'")

    client = OpenAI(api_key=current_user.openai_key)
    cfg = ChatModelConfig.get_current()
    chat_model = cfg.chat_model or "gpt-5-mini"
    # Règle stricte: tool_model = chat_model (même modèle pour initial et follow-up)
    tool_model = chat_model
    reasoning_effort = cfg.reasoning_effort
    verbosity = cfg.verbosity

    # --- Fetch and Format History ---
    print("[DEBUG LOG] Fetching last 10 messages from ChatHistory.")
    history_input = []
    try:
        # Fetch last 10 records, ordered by time (using ID as proxy if no timestamp)
        history_records = ChatHistory.query.filter_by(user_id=current_user.id) \
                                         .order_by(ChatHistory.id.desc()) \
                                         .limit(10).all()
        # Reverse to get chronological order (oldest first) for the API
        history_records.reverse()

        for record in history_records:
            role = record.role
            content = record.content
            function_name = record.name # For function role

            # --- Convert history records to API input format ---

            if role == 'user':
                if content:
                     history_input.append({
                         "type": "message",
                         "role": "user",
                         "content": [{"type": "input_text", "text": content}] # User role uses input_text (Correct)
                     })
                     print(f"[DEBUG LOG] Added history record ID {record.id} (Role: user) to input.")
                else:
                     print(f"[DEBUG LOG] Skipping history record ID {record.id} (Role: user, No Content)")

            elif role == 'assistant':
                # If assistant message has text content, add it
                if content:
                     history_input.append({
                         "type": "message",
                         "role": "assistant",
                         # V---- FIX: Use output_text for assistant history ----V
                         "content": [{"type": "output_text", "text": content}]
                     })
                     print(f"[DEBUG LOG] Added history record ID {record.id} (Role: assistant, Text Content) to input.")
                # If it was a function call *request* (check how you log this)
                elif record.function_call_name and record.function_call_args:
                     # Skipping as before, as Responses API input doesn't cleanly represent this.
                     print(f"[DEBUG LOG] Skipping history record ID {record.id} (Role: assistant, Function Call Request '{record.function_call_name}')")
                else:
                     print(f"[DEBUG LOG] Skipping history record ID {record.id} (Role: assistant, No Content/Function Call)")

            elif role == 'function':
                 # Format it as if the assistant is stating the function result
                 if function_name and content:
                      text_content = f"[Résultat de la fonction {function_name}]:\n{content}"
                      history_input.append({
                           "type": "message",
                           "role": "assistant", # Presenting the result as assistant text
                           # V---- FIX: Use output_text for assistant history ----V
                           "content": [{"type": "output_text", "text": text_content}]
                      })
                      print(f"[DEBUG LOG] Added history record ID {record.id} (Role: function, Name: {function_name}) to input as assistant text.")
                 else:
                      print(f"[DEBUG LOG] Skipping history record ID {record.id} (Role: function, Missing Name or Content)")
            else:
                 print(f"[WARN LOG] Skipping history record ID {record.id} with unknown role: {role}")
    except Exception as hist_err:
        print(f"[ERROR LOG] Failed to fetch or process chat history: {hist_err}")
        # Decide if you want to proceed without history or return an error
        # Proceeding without history for now:
        history_input = []


    # --- Construct Final Input ---
    inp = []
    prev_id = current_user.last_openai_response_id
    print(f"[DEBUG LOG] Constructing API input. prev_id={prev_id}. History items to add={len(history_input)}")

    # Add system prompt ONLY if there's no previous ID (start of a conversation state)
    # The Responses API relies primarily on prev_id for context continuity.
    # Manually adding history might be supplementary or potentially ignored if prev_id exists.
    if prev_id is None:
        print("[DEBUG LOG] No prev_id found, adding system prompt.")
        inp.append({"type": "message", "role": "system", "content": [{"type": "input_text", "text": "Vous êtes EDxo, un assistant IA spécialisé dans les plans de cours et plans-cadres du Cégep Garneau. Répondez de manière concise et professionnelle en français québécois."}]}) # Customize your system prompt

    # Add formatted history messages only when there is no prev_id
    # Une fois previous_response_id disponible, on ne renvoie plus d'historique manuel
    if prev_id is None:
        inp.extend(history_input)

    # Add current user message LAST
    inp.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": user_msg}]})

    # (Existing tools_schema definition)
    tools_schema = [
        get_plan_cadre_function(), get_plan_de_cours_function(),
        get_multiple_plan_cadre_function(), list_all_plan_cadre_function(),
        list_all_plan_de_cours_function(),
    ]

    # ───── Appel API (peut être le premier ou le seul) ─────────────────────────────
    print(f"[DEBUG LOG] Final input structure preview (first item type): {inp[0]['type'] if inp else 'empty'}, role: {inp[0].get('role') if inp else 'n/a'}")
    print(f"[DEBUG LOG] Total items in input: {len(inp)}")
    print("[DEBUG LOG] Initiating API call (raw_stream)...")
    text_params = {"format": {"type": "text"}}
    if verbosity in {"low", "medium", "high"}:
        text_params["verbosity"] = verbosity
    request_kwargs = dict(
        model=chat_model,
        input=inp,
        tools=tools_schema,
        previous_response_id=prev_id,
        tool_choice="auto",
        text=text_params,
        temperature=1,
        max_output_tokens=2048,
    )
    if reasoning_effort in {"minimal", "low", "medium", "high"}:
        request_kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
    try:
        print(f"[LOG] Initial call model={chat_model}, previous_response_id={prev_id}")
        raw_stream = safe_openai_stream(**request_kwargs)
        print("[DEBUG LOG] API call initiated.")

        # Lire le premier event pour l'itération
        print("[DEBUG LOG] Reading first event from raw_stream...")
        first_ev = next(raw_stream)
        print(f"[DEBUG LOG] First event received: {first_ev.__class__.__name__}")

    except StopIteration: # (gestion erreur)
        print("[ERROR LOG] OpenAI stream (raw_stream) was empty.")
        # Potentially add user feedback here if possible
        return Response("Flux OpenAI vide après l'appel initial.", 500)
    except OpenAIError as e: # Catch API errors specifically from safe_openai_stream
        print(f"[ERROR LOG] OpenAI API error during initial call: {e}")
        return Response(f"Erreur API OpenAI: {e}", 500)
    except Exception as e: # (gestion autre erreur)
        print(f"[ERROR LOG] Error reading first event or during initial safe_openai_stream call preparation: {e}")
        # Add more specific error logging if possible (e.g., dump `inp` if it fails serialization within the client)
        return Response(f"Erreur interne avant le traitement du flux: {e}", 500)


    # ───── Générateur SSE ─────────────────────────────────────────────────
    print("[DEBUG LOG] Starting SSE generator...")
    def sse():
        # --- Variables for internal tracking and DB logging ---
        # ... (rest of your sse generator variables remain the same) ...
        current_request_last_created_id = None
        final_id_to_persist_for_api = None
        last_response_object_id = None
        # Track follow-up stream latest ID to persist it preferentially
        had_followup = False
        last_followup_response_id = None

        pending_tool = False
        fn_name = fn_args_str = call_id = None
        tool_result_obj = None
        tool_result_json = None

        logs_to_add_db = []
        accumulated_assistant_text = ""
        reasoning_summary_text = ""


        print("[DEBUG LOG] SSE: Yielding initial processing message.")
        yield "data: {\"type\": \"processing\"}\n\n"

        # --- Log User Message for ChatHistory ---
        print("[DB LOG] Preparing user message log.")
        # Make sure user_msg is the original message, not potentially modified history parts
        user_log = ChatHistory(user_id=current_user.id, role="user", content=data.get("message", "").strip())
        logs_to_add_db.append(user_log)

        print("[DEBUG LOG] SSE: Processing event stream (starting with first_ev)...")
        event_iterator = itertools.chain([first_ev], raw_stream)

        try: # Enclose the main loop
            # ... (The entire loop processing events, handling tools, calling follow_stream, accumulating text, etc. remains the same) ...
            for ev_count, ev in enumerate(event_iterator):
                print(f"[DEBUG LOG] SSE Loop ({ev_count}): Processing event type: {ev.__class__.__name__}")

                # Track the last response ID seen
                response_id = getattr(getattr(ev, 'response', None), 'id', None)
                if response_id:
                    last_response_object_id = response_id

                # Store the ID from ResponseCreatedEvent
                if isinstance(ev, ResponseCreatedEvent) and response_id:
                    current_request_last_created_id = response_id
                    print(f"[LOG] Created initial response.id={current_request_last_created_id} (model={chat_model}, prev_id={prev_id})")

                # Log completion events
                if ResponseCompletedEvent is not None and isinstance(ev, ResponseCompletedEvent) and response_id:
                    print(f"[LOG] Completed initial response.id={response_id}")

                # --- Surface reasoning summary if present on this event ---
                try:
                    etype = getattr(ev, 'type', '') or ''
                    if etype.endswith('response.reasoning_summary_text.delta') or etype == 'response.reasoning_summary_text.delta':
                        rs_delta = getattr(ev, 'delta', '') or ''
                        if rs_delta:
                            reasoning_summary_text += rs_delta
                    elif etype.endswith('reasoning.summary.delta') or etype == 'reasoning.summary.delta':
                        reasoning_summary_text += _collect_summary(getattr(ev, 'delta', None))
                    elif getattr(ev, 'summary', None):
                        reasoning_summary_text += _collect_summary(getattr(ev, 'summary', None))
                    reasoning_summary_text = reasoning_summary_text.strip()
                    if reasoning_summary_text:
                        yield "data: " + json.dumps({"type": "reasoning_summary", "content": reasoning_summary_text}) + "\n\n"
                except Exception:
                    pass

                # --- Tool Call Detection and Processing ---
                if (isinstance(ev, ResponseOutputItemAddedEvent)
                        and getattr(ev.item, "type", "") == "function_call"):
                    pending_tool = True
                    fn_name = getattr(ev.item, "name", None)
                    call_id = getattr(ev.item, "call_id", None)
                    fn_args_str = "" # Reset args
                    print(f"[LOG] Tool call requested: name='{fn_name}', call_id='{call_id}' on response.id={last_response_object_id}")
                    yield f"data: {json.dumps({'type': 'function_call', 'content': fn_name})}\n\n"
                    continue

                if pending_tool and isinstance(ev, ResponseFunctionCallArgumentsDeltaEvent):
                    fn_args_str += getattr(ev, "delta", "")
                    continue

                if pending_tool and isinstance(ev, ResponseOutputItemDoneEvent) and getattr(ev.item, "type", "") == "function_call":
                    print(f"[DEBUG LOG] SSE: Detected function_call end. Name='{fn_name}'. Args='{fn_args_str}'")
                    pending_tool = False

                    if not fn_name or not call_id: # Validation
                        print(f"[ERROR LOG] SSE: Missing fn_name/call_id. Name={fn_name}, CallID={call_id}")
                        yield f"data: {json.dumps({'type': 'error', 'content': 'Internal error processing tool call.'})}\n\n"
                        continue # Skip this invalid tool call attempt

                    # --- Log Assistant Function Call Request ---
                    print(f"[DB LOG] Preparing assistant function call request log for '{fn_name}'.")
                    assistant_fcall_log = ChatHistory(
                        user_id=current_user.id, role='assistant', content=None, # No text content for the request itself
                        function_call_name=fn_name, function_call_args=fn_args_str
                    )
                    logs_to_add_db.append(assistant_fcall_log)

                    # --- Execute Tool ---
                    tool_result_obj = None # Reset
                    try:
                        parsed_args = json.loads(fn_args_str or "{}")
                        print(f"[DEBUG LOG] SSE: Executing tool handler '{fn_name}' with args: {parsed_args}")
                        handler = {
                            "get_plan_cadre": handle_get_plan_cadre, "get_plan_de_cours": handle_get_plan_de_cours,
                            "get_multiple_plan_cadre": handle_get_multiple_plan_cadre, "list_all_plan_cadre": lambda p: handle_list_all_plan_cadre(),
                            "list_all_plan_de_cours": lambda p: handle_list_all_plan_de_cours(),
                        }.get(fn_name)

                        if handler:
                            tool_result_obj = handler(parsed_args)
                        else:
                            tool_result_obj = {"error": f"Fonction outil inconnue: {fn_name}"} # User-friendly error
                        print(f"[DEBUG LOG] SSE: Tool handler '{fn_name}' executed. Result type: {type(tool_result_obj)}, Snippet: {str(tool_result_obj)[:200]}...")

                        # --- Log Function Result ---
                        # Ensure the result is serializable *before* logging
                        try:
                            tool_result_json = json.dumps(tool_result_obj)
                        except TypeError as json_err:
                            print(f"[ERROR LOG] SSE: Failed to serialize tool result for '{fn_name}': {json_err}")
                            tool_result_obj = {"error": f"Le résultat de l'outil '{fn_name}' n'a pas pu être sérialisé."}
                            tool_result_json = json.dumps(tool_result_obj)

                        print(f"[DB LOG] Preparing function result log for '{fn_name}'.")
                        func_result_log = ChatHistory(
                            user_id=current_user.id, role='function', name=fn_name, content=tool_result_json
                        )
                        logs_to_add_db.append(func_result_log)

                    except json.JSONDecodeError as json_err:
                         print(f"[ERROR LOG] SSE: Failed to parse JSON arguments for tool '{fn_name}': {fn_args_str}. Error: {json_err}")
                         tool_result_obj = {"error": f"Arguments invalides fournis pour l'outil {fn_name}."}
                         tool_result_json = json.dumps(tool_result_obj)
                         # Log this error state as a function result? Maybe.
                         # func_error_log = ChatHistory(user_id=current_user.id, role='function', name=fn_name, content=tool_result_json)
                         # logs_to_add_db.append(func_error_log)
                         # Need to decide if we call the follow_stream with this error or yield an error to the user directly.
                         # Let's send the error back to the LLM via follow_stream.

                    except Exception as tool_exec_e:
                        print(f"[ERROR LOG] SSE: Exception during tool execution or handling '{fn_name}': {tool_exec_e}")
                        tool_result_obj = {"error": f"Erreur lors de l'exécution de l'outil {fn_name}: {tool_exec_e}"}
                        tool_result_json = json.dumps(tool_result_obj)
                        # Log this error state
                        func_error_log = ChatHistory(user_id=current_user.id, role='function', name=fn_name, content=tool_result_json)
                        logs_to_add_db.append(func_error_log)


                    # --- Call Follow-up API ---
                    id_for_followup = current_request_last_created_id # Use the ID created *before* the tool call
                    if not id_for_followup:
                        print("[ERROR LOG] SSE: Cannot make follow_stream call because current_request_last_created_id is missing!")
                        yield f"data: {json.dumps({'type': 'error', 'content': 'Erreur interne: Impossible de continuer après l\'exécution de l\'outil.'})}\n\n"
                        # Maybe try to recover or just end here? Ending is safer.
                        break # Exit the main loop

                    print(f"[LOG] Preparing follow-up with previous_response_id={id_for_followup}, model={tool_model}, call_id={call_id}")

                    try:
                        print("[DEBUG LOG] SSE: Initiating follow_stream API call...")
                        text_params = {"format": {"type": "text"}}
                        if verbosity in {"low", "medium", "high"}:
                            text_params["verbosity"] = verbosity
                        follow_kwargs = dict(
                            model=tool_model,
                            previous_response_id=id_for_followup,
                            input=[{"type": "function_call_output", "call_id": call_id, "output": tool_result_json}],
                            tool_choice="auto",
                            text=text_params,
                            stream=True,
                            temperature=1,
                            max_output_tokens=2048,
                        )
                        if reasoning_effort in {"minimal", "low", "medium", "high"}:
                            follow_kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
                        follow_stream = client.responses.create(**follow_kwargs)
                        print("[DEBUG LOG] SSE: follow_stream call initiated.")

                        # --- Process Follow-up Stream ---
                        print("[DEBUG LOG] SSE: Processing follow_stream...")
                        for ev2_count, ev2 in enumerate(follow_stream):
                            print(f"[DEBUG LOG] SSE Follow Loop ({ev2_count}): Processing event type: {ev2.__class__.__name__}")
                            # Surface reasoning summary during follow-up
                            try:
                                etype2 = getattr(ev2, 'type', '') or ''
                                if etype2.endswith('response.reasoning_summary_text.delta') or etype2 == 'response.reasoning_summary_text.delta':
                                    rs_delta2 = getattr(ev2, 'delta', '') or ''
                                    if rs_delta2:
                                        reasoning_summary_text += rs_delta2
                                elif etype2.endswith('reasoning.summary.delta') or etype2 == 'reasoning.summary.delta':
                                    reasoning_summary_text += _collect_summary(getattr(ev2, 'delta', None))
                                elif getattr(ev2, 'summary', None):
                                    reasoning_summary_text += _collect_summary(getattr(ev2, 'summary', None))
                                reasoning_summary_text = reasoning_summary_text.strip()
                                if reasoning_summary_text:
                                    yield "data: " + json.dumps({"type": "reasoning_summary", "content": reasoning_summary_text}) + "\n\n"
                            except Exception:
                                pass
                            # Track the latest response ID seen (from the follow-up stream)
                            response_id2 = getattr(getattr(ev2, 'response', None), 'id', None)
                            if response_id2:
                                last_response_object_id = response_id2 # Update with the newest ID
                                last_followup_response_id = response_id2
                                had_followup = True
                            if isinstance(ev2, ResponseCreatedEvent) and response_id2:
                                print(f"[LOG] Created follow-up response.id={response_id2} (model={tool_model}, prev_id={id_for_followup}, call_id={call_id})")
                            if ResponseCompletedEvent is not None and isinstance(ev2, ResponseCompletedEvent) and response_id2:
                                print(f"[LOG] Completed follow-up response.id={response_id2} (call_id={call_id})")

                            # Extract and accumulate text from the follow-up
                            txt = extract_text(ev2)
                            if txt:
                                accumulated_assistant_text += txt # Accumulate final response
                                yield "data: " + json.dumps({"type": "content", "content": txt}) + "\n\n"
                        print("[DEBUG LOG] SSE: Finished processing follow_stream.")

                    except OpenAIError as api_e: # Handle API errors during follow-up
                        print(f"[ERROR LOG] SSE: OpenAI API Error during follow_stream for tool '{fn_name}': {api_e}")
                        # Retry strategy for "No tool output found for function call"
                        if "No tool output found for function call" in str(api_e):
                            try:
                                print(f"[RETRY] Re-emitting minimal error output with same previous_response_id={id_for_followup}, call_id={call_id}")
                                minimal_err = json.dumps({"error": "tool failed"})
                                text_params2 = {"format": {"type": "text"}}
                                if verbosity in {"low", "medium", "high"}:
                                    text_params2["verbosity"] = verbosity
                                retry_kwargs = dict(
                                    model=tool_model,
                                    previous_response_id=id_for_followup,
                                    input=[{"type": "function_call_output", "call_id": call_id, "output": minimal_err}],
                                    tool_choice="auto",
                                    text=text_params2,
                                    stream=True,
                                    temperature=1,
                                    max_output_tokens=2048,
                                )
                                if reasoning_effort in {"minimal", "low", "medium", "high"}:
                                    retry_kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
                                retry_stream = client.responses.create(**retry_kwargs)
                                for ev3_count, ev3 in enumerate(retry_stream):
                                    response_id3 = getattr(getattr(ev3, 'response', None), 'id', None)
                                    if response_id3:
                                        last_response_object_id = response_id3
                                        last_followup_response_id = response_id3
                                        had_followup = True
                                    if isinstance(ev3, ResponseCreatedEvent) and response_id3:
                                        print(f"[LOG] Created follow-up(retry) response.id={response_id3} (model={tool_model}, prev_id={id_for_followup}, call_id={call_id})")
                                    if ResponseCompletedEvent is not None and isinstance(ev3, ResponseCompletedEvent) and response_id3:
                                        print(f"[LOG] Completed follow-up(retry) response.id={response_id3} (call_id={call_id})")
                                    # Surface reasoning summary on retry
                                    try:
                                        etype3 = getattr(ev3, 'type', '') or ''
                                        if etype3.endswith('response.reasoning_summary_text.delta') or etype3 == 'response.reasoning_summary_text.delta':
                                            rs_delta3 = getattr(ev3, 'delta', '') or ''
                                            if rs_delta3:
                                                reasoning_summary_text += rs_delta3
                                        elif etype3.endswith('reasoning.summary.delta') or etype3 == 'reasoning.summary.delta':
                                            reasoning_summary_text += _collect_summary(getattr(ev3, 'delta', None))
                                        elif getattr(ev3, 'summary', None):
                                            reasoning_summary_text += _collect_summary(getattr(ev3, 'summary', None))
                                        reasoning_summary_text = reasoning_summary_text.strip()
                                        if reasoning_summary_text:
                                            yield "data: " + json.dumps({"type": "reasoning_summary", "content": reasoning_summary_text}) + "\n\n"
                                    except Exception:
                                        pass

                                    txt3 = extract_text(ev3)
                                    if txt3:
                                        accumulated_assistant_text += txt3
                                        yield "data: " + json.dumps({"type": "content", "content": txt3}) + "\n\n"
                                # If retry succeeded, continue the outer loop
                                print("[RETRY] Minimal error output follow-up completed.")
                            except OpenAIError as retry_e:
                                print(f"[ERROR LOG] Retry follow-up failed: {retry_e}")
                                # Last resort: start a new thread (no previous_response_id)
                                try:
                                    print("[FALLBACK] Starting a new thread (nouvelle conversation) without previous_response_id due to follow-up failure.")
                                    text_params3 = {"format": {"type": "text"}}
                                    if verbosity in {"low", "medium", "high"}:
                                        text_params3["verbosity"] = verbosity
                                    new_thread_kwargs = dict(
                                        model=tool_model,
                                        input=[{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "L'outil a échoué; je poursuis sans lui."}]}],
                                        tool_choice="auto",
                                        text=text_params3,
                                        stream=True,
                                        temperature=1,
                                        max_output_tokens=2048,
                                    )
                                    new_thread_stream = client.responses.create(**new_thread_kwargs)
                                    for ev4 in new_thread_stream:
                                        response_id4 = getattr(getattr(ev4, 'response', None), 'id', None)
                                        if response_id4:
                                            last_response_object_id = response_id4
                                        if isinstance(ev4, ResponseCreatedEvent) and response_id4:
                                            print(f"[LOG] Created new-thread response.id={response_id4} (model={tool_model})")
                                        if ResponseCompletedEvent is not None and isinstance(ev4, ResponseCompletedEvent) and response_id4:
                                            print(f"[LOG] Completed new-thread response.id={response_id4}")
                                        # Surface reasoning summary in new thread stream
                                        try:
                                            etype4 = getattr(ev4, 'type', '') or ''
                                            if etype4.endswith('response.reasoning_summary_text.delta') or etype4 == 'response.reasoning_summary_text.delta':
                                                rs_delta4 = getattr(ev4, 'delta', '') or ''
                                                if rs_delta4:
                                                    reasoning_summary_text += rs_delta4
                                            elif etype4.endswith('reasoning.summary.delta') or etype4 == 'reasoning.summary.delta':
                                                reasoning_summary_text += _collect_summary(getattr(ev4, 'delta', None))
                                            elif getattr(ev4, 'summary', None):
                                                reasoning_summary_text += _collect_summary(getattr(ev4, 'summary', None))
                                            reasoning_summary_text = reasoning_summary_text.strip()
                                            if reasoning_summary_text:
                                                yield "data: " + json.dumps({"type": "reasoning_summary", "content": reasoning_summary_text}) + "\n\n"
                                        except Exception:
                                            pass

                                        txt4 = extract_text(ev4)
                                        if txt4:
                                            accumulated_assistant_text += txt4
                                            yield "data: " + json.dumps({"type": "content", "content": txt4}) + "\n\n"
                                except Exception as new_thread_e:
                                    print(f"[ERROR LOG] New-thread fallback failed: {new_thread_e}")
                                    error_content = f"Erreur API OpenAI après l'exécution de l'outil {fn_name}."
                                    accumulated_assistant_text += f"\n[ERREUR] {error_content}"
                                    yield f"data: {json.dumps({'type': 'error', 'content': error_content})}\n\n"
                        else:
                            error_content = f"Erreur API OpenAI après l'exécution de l'outil {fn_name}."
                            accumulated_assistant_text += f"\n[ERREUR] {error_content}" # Add error to log
                            yield f"data: {json.dumps({'type': 'error', 'content': error_content})}\n\n"
                    except Exception as follow_e: # Handle generic errors during follow-up
                        print(f"[ERROR LOG] SSE: Unexpected error during follow_stream processing for tool '{fn_name}': {follow_e}")
                        error_content = "Une erreur inattendue s'est produite lors du traitement de la réponse de l'outil."
                        accumulated_assistant_text += f"\n[ERREUR] {error_content}" # Add error to log
                        yield f"data: {json.dumps({'type': 'error', 'content': error_content})}\n\n"

                    # Reset state after tool call processing is complete
                    fn_name = fn_args_str = call_id = tool_result_obj = tool_result_json = None
                    continue # Move to the next event in the *original* iterator (if any)


                # ------------ Normal Text (not part of a tool call sequence being processed currently) -------------
                txt = extract_text(ev)
                if txt:
                    # This text comes from the initial stream if no tool call happened,
                    # OR potentially from the initial stream *before* a tool call was fully detected.
                    # We accumulate it here. If a tool call *does* happen later, the follow_stream's
                    # text will overwrite/append to this in the final log.
                    accumulated_assistant_text += txt
                    yield "data: " + json.dumps({"type": "content", "content": txt}) + "\n\n"

            # --- End of the main event processing loop ---
            # Prefer the last follow-up response id if one occurred; else use the last seen id
            final_id_to_persist_for_api = last_followup_response_id if had_followup and last_followup_response_id else last_response_object_id
            if had_followup:
                print(f"[LOG] Prefer persisting follow-up id: {final_id_to_persist_for_api}")
            print(f"[DEBUG LOG] SSE: Event stream processing finished. Determined final_id_to_persist_for_api = {final_id_to_persist_for_api}")
            print(f"[DEBUG LOG] SSE: Accumulated final assistant text: '{accumulated_assistant_text[:100]}...'")

        except Exception as e_main_loop:
            print(f"[ERROR LOG] SSE: Exception in main event processing loop: {e_main_loop}")
            # Log the error and yield an error message to the client
            accumulated_assistant_text += f"\n[ERREUR SYSTÈME] Une erreur est survenue: {e_main_loop}"
            yield f"data: {json.dumps({'type': 'error', 'content': 'Une erreur est survenue lors du traitement de la réponse.'})}\n\n"
            # Ensure we still try to persist logs and potentially the last valid ID seen
            final_id_to_persist_for_api = last_response_object_id # Persist the last ID seen before the crash

        finally:
            # --- Log Final Assistant Response (Text) ---
            if accumulated_assistant_text:
                print("[DB LOG] Preparing final assistant text response log.")
                final_assistant_log = ChatHistory(
                    user_id=current_user.id, role='assistant', content=accumulated_assistant_text.strip()
                )
                # Avoid logging empty assistant messages if only errors occurred or stream was empty
                if final_assistant_log.content:
                     # Check if the last log entry was the function call request for this text; avoid duplicate role logging if possible?
                     # Simpler: just log the final text. The UI should handle displaying the flow.
                     logs_to_add_db.append(final_assistant_log)
                else:
                     print("[DEBUG LOG] SSE: Accumulated assistant text was empty or whitespace. Not logging.")
            else:
                # This might happen if only a tool call occurred and the follow_stream failed or yielded nothing.
                print("[DEBUG LOG] SSE: No accumulated assistant text to log.")

            # --- Commit ChatHistory Logs ---
            if logs_to_add_db:
                try:
                    db.session.add_all(logs_to_add_db)
                    db.session.commit()
                    print(f"[DB LOG] COMMITTED {len(logs_to_add_db)} ChatHistory records.")
                except Exception as log_commit_err:
                    print(f"[ERROR LOG] FAILED to commit ChatHistory logs: {log_commit_err}")
                    db.session.rollback() # Rollback history logs on failure

            # --- Commit Final Response ID for API State (Separate Commit) ---
            if final_id_to_persist_for_api:
                try:
                    # Re-fetch the user within the session context for update
                    user_to_update = db.session.get(User, current_user.id)
                    if user_to_update:
                        user_to_update.last_openai_response_id = final_id_to_persist_for_api
                        db.session.commit()
                        print(f"[DB LOG] COMMITTED final last_openai_response_id for user {current_user.id} to {final_id_to_persist_for_api}")
                        print(f"[LOG] Persisted previous_response_id={final_id_to_persist_for_api}")
                    else:
                        # This should ideally not happen if the user is logged in
                        print(f"[ERROR LOG] Could not find user {current_user.id} in session to update response ID.")
                        db.session.rollback() # Rollback just this attempted ID update
                except Exception as db_err:
                    print(f"[ERROR LOG] FAILED to commit final last_openai_response_id to DB: {db_err}")
                    db.session.rollback() # Rollback just this attempted ID update
            else:
                # This could happen if the stream was empty or errored out immediately.
                print("[DEBUG LOG] SSE: No final_id_to_persist_for_api determined. DB not updated for Responses API state.")

            # Emit done with model and persisted id so UI can refresh badge
            done_payload = {"type": "done", "model": chat_model, "prev_id": final_id_to_persist_for_api}
            yield "data: " + json.dumps(done_payload) + "\n\n"
            print(f"[DEBUG LOG] === SSE generator yielding done (Final API ID persisted: {final_id_to_persist_for_api}) === ")


    # ───── Retour de la réponse SSE -----------------------------------------
    print("[DEBUG LOG] Returning SSE Response object.")
    return Response(
        stream_with_context(sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

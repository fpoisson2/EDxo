# chat.py – Responses API + DEBUG (SDK 1.23 → ≥1.25)
import json, pprint, tiktoken
from flask import Blueprint, render_template, request, Response, stream_with_context, session
from flask_login import login_required, current_user
from openai import OpenAI, OpenAIError
import itertools

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

from openai.types.responses import ResponseFunctionToolCall   # ← Fallback


# ─── app imports internes ───────────────────────────────────────
from app.forms import ChatForm
from app.models import User, PlanCadre, PlanDeCours, Cours, db, ChatHistory
from utils.decorator import ensure_profile_completed
from utils.openai_pricing import calculate_call_cost

chat = Blueprint("chat", __name__)

def extract_text(ev):
    """Renvoie le texte s’il existe, sinon None."""
    if hasattr(ev, "delta") and isinstance(ev.delta, str):
        return ev.delta
    if getattr(ev, "item", None) and isinstance(ev.item, object):
        return getattr(ev.item, "text", None)
    return None


# ─── token util ─────────────────────────────────────────────────
def estimate_tokens_for_text(txt: str, model="gpt-4.1"):
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

# ─── route index ───────────────────────────────────────────────
@chat.route("/chat")
@login_required
@ensure_profile_completed
def index():
    session.pop("last_response_id", None)
    return render_template("chat/index.html", form=ChatForm())


def _update_last_response_id(ev):
    """Stocke dans la session l'id de la dernière réponse complétée."""
    from openai.types.responses import ResponseCreatedEvent, ResponseCompletedEvent

    if isinstance(ev, ResponseCreatedEvent):
        session["last_response_id"] = ev.response.id
        session.modified = True
    elif isinstance(ev, ResponseCompletedEvent):
        session["last_response_id"] = ev.response.id
        session.modified = True


# ────────────────────────────────────────────────────────────────
#  Route /chat/send
# ----------------------------------------------------------------
@chat.route("/chat/send", methods=["POST"])
@login_required
@ensure_profile_completed
def send_message():
    # ───── 1. Lecture du message utilisateur ────────────────────────────────
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return Response("", 400)

    client       = OpenAI(api_key=current_user.openai_key)
    prev_id      = session.get("last_response_id")  # peut être None
    tools_schema = [
        get_plan_cadre_function(),
        get_plan_de_cours_function(),
        get_multiple_plan_cadre_function(),
        list_all_plan_cadre_function(),
        list_all_plan_de_cours_function(),
    ]

    # construction de l'input
    inp = []
    if prev_id is None:          # tout premier tour => system-prompt
        inp.append({
            "type": "message",
            "role": "system",
            "content": [{"type": "input_text", "text": "Vous êtes EDxo …"}]
        })
    inp.append({
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": user_msg}]
    })

    # petite fonction utilitaire ------------------------------------------------
    def safe_openai_stream(**kwargs):
        """Appelle l'API et, si erreur « No tool output », ré-essaye sans prev_id."""
        try:
            return client.responses.create(**kwargs, stream=True)
        except OpenAIError as e:
            if "No tool output found for function call" in str(e) and kwargs.get("previous_response_id"):
                # on efface l'id fautif et on relance une conversation propre
                session.pop("last_response_id", None)
                kwargs["previous_response_id"] = None
                return client.responses.create(**kwargs, stream=True)
            raise

    # ───── 2. Premier appel API (avec safeguard) ─────────────────────────────
    raw_stream = safe_openai_stream(
        model="gpt-4.1-mini",
        input=inp,
        tools=tools_schema,
        previous_response_id=prev_id,
        tool_choice="auto",
        text={"format": {"type": "text"}},
        temperature=1,
        max_output_tokens=2048,
    )

    # lit le premier event pour avoir tout de suite le nouvel id
    try:
        first_ev = next(raw_stream)
    except StopIteration:
        return Response("Flux OpenAI vide", 500)

    # on NE stocke l'id que si la réponse *n'est pas* un function_call
    def maybe_store_id(ev):
        from openai.types.responses import ResponseCreatedEvent, ResponseCompletedEvent
        if isinstance(ev, ResponseCreatedEvent):
            session["last_response_id"] = ev.response.id
            session.modified = True
        elif isinstance(ev, ResponseCompletedEvent):
            # si la réponse se termine par un vrai message assistant
            if (ev.response.output and
                getattr(ev.response.output[0], "type", "") != "function_call"):
                session["last_response_id"] = ev.response.id
                session.modified = True

    maybe_store_id(first_ev)

    # ───── 3. Générateur SSE ─────────────────────────────────────────────────
    from openai.types.responses import (
        ResponseOutputItemAddedEvent, ResponseOutputItemDoneEvent,
        ResponseFunctionCallArgumentsDeltaEvent
    )

    def sse():
        yield "data: {\"type\": \"processing\"}\n\n"

        # on traite le 1ᵉʳ évènement puis le reste
        pending_tool = False  # sommes-nous en train de gérer un call ?
        fn_name = fn_args = call_id = None

        for ev in itertools.chain([first_ev], raw_stream):
            maybe_store_id(ev)

            # ------------ nouveau function_call --------------------------------
            if (isinstance(ev, ResponseOutputItemAddedEvent)
                    and getattr(ev.item, "type", "") == "function_call"):
                pending_tool = True
                fn_name      = ev.item.name
                call_id      = ev.item.call_id
                fn_args      = ""
                yield f"data: {{\"type\": \"function_call\", \"content\": \"{fn_name}\"}}\n\n"
                continue

            # ------------ accumulation des arguments ---------------------------
            if pending_tool and isinstance(ev, ResponseFunctionCallArgumentsDeltaEvent):
                fn_args += ev.delta
                continue

            # ------------ fin du function_call ---------------------------------
            if pending_tool and isinstance(ev, ResponseOutputItemDoneEvent):
                pending_tool = False
                # exécution locale du tool
                result = {
                    "get_plan_cadre":           handle_get_plan_cadre,
                    "get_plan_de_cours":        handle_get_plan_de_cours,
                    "get_multiple_plan_cadre":  handle_get_multiple_plan_cadre,
                    "list_all_plan_cadre":      lambda _: handle_list_all_plan_cadre(),
                    "list_all_plan_de_cours":   lambda _: handle_list_all_plan_de_cours(),
                }[fn_name](json.loads(fn_args or "{}"))

                # follow-up avec la sortie --------------------------------------
                follow_stream = client.responses.create(
                    model="gpt-4.1-mini",
                    previous_response_id=session.get("last_response_id"),
                    input=[{
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result)
                    }],
                    tool_choice="auto",
                    text={"format": {"type": "text"}},
                    stream=True,
                )

                for ev2 in follow_stream:
                    maybe_store_id(ev2)
                    txt = extract_text(ev2)
                    if txt:
                        yield "data: " + json.dumps({"type": "content", "content": txt}) + "\n\n"
                continue  # retourne à la boucle principale

            # ------------ texte normal -----------------------------------------
            txt = extract_text(ev)
            if txt:
                yield "data: " + json.dumps({"type": "content", "content": txt}) + "\n\n"

        yield "data: {\"type\": \"done\"}\n\n"

    # ───── 4. Response SSE ----------------------------------------------------
    return Response(
        stream_with_context(sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

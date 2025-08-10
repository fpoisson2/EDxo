from flask import Blueprint, request, Response, stream_with_context, render_template
from flask_login import login_required, current_user

from utils.decorator import ensure_profile_completed

from .history import add_message, get_last_messages
from .stream import simple_stream
from app.forms import ChatForm
from types import SimpleNamespace
from openai import OpenAI, OpenAIError

chat = Blueprint("chat", __name__)

@chat.route("/chat")
@login_required
@ensure_profile_completed
def index():
    """Endpoint principal du chat."""
    form = ChatForm()
    if not hasattr(form, "csrf_token"):
        form.csrf_token = SimpleNamespace(current_token="")
    return render_template("chat/index.html", form=form)

@chat.route("/chat/send", methods=["POST"])
@login_required
@ensure_profile_completed
def send_message():
    """Réception d'un message utilisateur et diffusion via SSE."""
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    add_message(current_user.id, "user", message)
    history = get_last_messages(current_user.id)
    messages = [{"role": m.role, "content": m.content} for m in history]

    try:
        client = OpenAI(api_key=current_user.openai_key)
        response = client.responses.create(model="gpt-4o-mini", input=messages)
        reply = response.output[0].content[0].text
    except OpenAIError:
        reply = "Erreur lors de l'appel à OpenAI"

    add_message(current_user.id, "assistant", reply)
    generator = simple_stream(reply, history)
    return Response(stream_with_context(generator), mimetype="text/event-stream")

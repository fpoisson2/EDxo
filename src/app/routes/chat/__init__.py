from flask import Blueprint, request, Response, stream_with_context, render_template
from flask_login import login_required, current_user

from utils.decorator import ensure_profile_completed

from .history import add_message, get_last_messages
from .stream import simple_stream
from app.forms import ChatForm
from types import SimpleNamespace

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
    reply = f"Je suis un bot, vous avez dit : {message}"
    add_message(current_user.id, "assistant", reply)
    generator = simple_stream(reply, history)
    return Response(stream_with_context(generator), mimetype="text/event-stream")

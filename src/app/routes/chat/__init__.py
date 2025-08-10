from flask import Blueprint, request, Response, stream_with_context
from flask_login import login_required, current_user

from utils.decorator import ensure_profile_completed

from .history import add_message, get_last_messages
from .stream import simple_stream

chat = Blueprint("chat", __name__)

@chat.route("/chat")
@login_required
@ensure_profile_completed
def index():
    """Endpoint principal du chat."""
    return "chat index"

@chat.route("/chat/send", methods=["POST"])
@login_required
@ensure_profile_completed
def send_message():
    """Réception d'un message utilisateur et diffusion via SSE."""
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    add_message(current_user.id, "user", message)
    history = get_last_messages(current_user.id)
    generator = simple_stream(message, history)
    return Response(stream_with_context(generator), mimetype="text/event-stream")

"""Gestion de l'historique des conversations."""
from typing import List

from app.models import ChatHistory, db


def add_message(user_id: int, role: str, content: str) -> ChatHistory:
    """Ajoute un message à l'historique et le persiste."""
    entry = ChatHistory(user_id=user_id, role=role, content=content)
    db.session.add(entry)
    db.session.commit()
    return entry


def get_last_messages(user_id: int, limit: int = 10) -> List[ChatHistory]:
    """Retourne les derniers messages pour un utilisateur."""
    return ChatHistory.get_recent_history(user_id, limit=limit)

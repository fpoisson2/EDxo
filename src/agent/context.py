from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .app_session import AppSession


_CURRENT_CTX: "EDxoContext | None" = None


@dataclass
class EDxoContext:
    """Context passed to the agent run, holding credentials and session cache."""

    username: Optional[str] = None
    password: Optional[str] = None
    # Cached app session (created on demand)
    _session: Optional[AppSession] = field(default=None, init=False, repr=False)

    def ensure_session(self) -> AppSession:
        if self._session is None:
            self._session = AppSession.create(testing=False)
        # Login if needed
        if (self.username and self.password) and not self._session.user_id:
            self._session.login_with_password(self.username, self.password)
        return self._session


def set_current_context(ctx: EDxoContext) -> None:
    global _CURRENT_CTX
    _CURRENT_CTX = ctx


def get_current_context() -> EDxoContext:
    if _CURRENT_CTX is None:
        # Provide an empty context by default
        return EDxoContext()
    return _CURRENT_CTX


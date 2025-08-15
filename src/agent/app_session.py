from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from flask import Flask
from werkzeug.security import check_password_hash


@dataclass
class AppSession:
    """Wraps a Flask app + test client with an authenticated session.

    Usage:
        sess = AppSession.create()
        assert sess.login_with_password("admin", "admin1234")
        r = sess.post_json("/plan_de_cours/generate_all_start", {...})
    """

    app: Flask
    client: Any
    user_id: Optional[int] = None

    @classmethod
    def create(cls, testing: bool = False) -> "AppSession":
        from src.app.__init__ import create_app

        app = create_app(testing=testing)
        client = app.test_client()
        return cls(app=app, client=client)

    def login_with_password(self, username: str, password: str) -> bool:
        """Authenticate against DB and set Flask-Login session for test client.

        Returns True on success, False otherwise.
        """
        from src.app.models import User

        with self.app.app_context():
            user = (
                User.query.filter(User.username.ilike(username.strip())).first()
            )
            if not user:
                return False
            if not check_password_hash(user.password, password):
                return False

            # Establish Flask-Login session in the test client
            with self.client.session_transaction() as sess:
                sess["_user_id"] = str(user.id)
                sess["_fresh"] = True
            self.user_id = int(user.id)
            return True

    # -------------
    # HTTP helpers
    # -------------
    def get(self, path: str, query: Optional[Dict[str, Any]] = None):
        return self.client.get(path, query_string=query or {})

    def post_form(self, path: str, data: Dict[str, Any]):
        return self.client.post(path, data=data, follow_redirects=False)

    def post_json(self, path: str, data: Dict[str, Any]):
        return self.client.post(path, json=data)

    # Convenience wrappers for common endpoints
    def version(self) -> str:
        r = self.get("/version")
        return (r.get_json() or {}).get("version", "")

    def health(self) -> Dict[str, Any]:
        r = self.get("/health")
        return r.get_json() or {}

    def complete_profile(self) -> bool:
        """Mark the current user as having completed the first connection.

        Needed to bypass ensure_profile_completed redirects for protected routes.
        """
        if not self.user_id:
            return False
        from src.app.models import User, db
        with self.app.app_context():
            user = User.query.get(self.user_id)
            if not user:
                return False
            if user.is_first_connexion:
                user.is_first_connexion = False
                db.session.commit()
        return True

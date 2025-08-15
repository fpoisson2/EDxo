import asyncio
from datetime import datetime, timedelta

from src.app import db
from src.app.models import OAuthToken
from src.mcp_server.server import DBTokenVerifier, init_app as init_mcp_app


def test_db_token_verifier(app):
    with app.app_context():
        token = OAuthToken(token="tok", client_id="cli", expires_at=datetime.utcnow() + timedelta(hours=1))
        db.session.add(token)
        db.session.commit()
        init_mcp_app(app)
        verifier = DBTokenVerifier()
        access = asyncio.run(verifier.verify_token("tok"))
        assert access is not None and access.client_id == "cli"
        assert asyncio.run(verifier.verify_token("bad")) is None

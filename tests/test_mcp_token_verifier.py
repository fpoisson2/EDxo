import asyncio
from datetime import timedelta

from src.app import db
from src.app.models import OAuthToken
from src.mcp_server.server import DBTokenVerifier, TOKEN_RESOURCES
from src.utils.datetime_utils import now_utc


def test_db_token_verifier_uses_host_url_for_audience(app):
    token_value = "tok123"
    expires_at = now_utc() + timedelta(minutes=5)

    with app.app_context():
        record = OAuthToken(
            token=token_value,
            client_id="cid-host-url",
            user_id=None,
            expires_at=expires_at,
        )
        db.session.add(record)
        db.session.commit()

    TOKEN_RESOURCES[token_value] = "https://example.com/sse"
    verifier = DBTokenVerifier()

    async def run_verification():
        with app.test_request_context(
            "/sse/",
            base_url="https://example.com/sse/",
            headers={"Authorization": f"Bearer {token_value}"},
        ):
            result = await verifier.verify_token(token_value)
            assert result is not None
            assert result.client_id == "cid-host-url"

    try:
        asyncio.run(run_verification())
    finally:
        TOKEN_RESOURCES.pop(token_value, None)
        with app.app_context():
            OAuthToken.query.filter_by(token=token_value).delete()
            db.session.commit()

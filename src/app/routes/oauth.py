"""OAuth endpoints for dynamic client registration and token issuance."""

from datetime import datetime, timedelta
import secrets

from flask import Blueprint, jsonify, request, url_for

from ..models import OAuthClient, OAuthToken, db

oauth_bp = Blueprint('oauth', __name__)


@oauth_bp.get('/.well-known/oauth-authorization-server')
def oauth_metadata():
    """Expose OAuth server metadata for discovery."""
    return (
        jsonify(
            {
                'issuer': request.url_root.rstrip('/'),
                'token_endpoint': url_for('oauth.issue_token', _external=True),
                'registration_endpoint': url_for('oauth.register_client', _external=True),
            }
        ),
        200,
    )


@oauth_bp.post('/register')
def register_client():
    """Register a new OAuth client and return credentials."""
    data = request.get_json() or {}
    name = data.get('name')
    redirect_uri = data.get('redirect_uri')
    client_id = secrets.token_hex(16)
    client_secret = secrets.token_hex(32)
    client = OAuthClient(
        client_id=client_id,
        client_secret=client_secret,
        name=name,
        redirect_uri=redirect_uri,
    )
    db.session.add(client)
    db.session.commit()
    return jsonify({'client_id': client_id, 'client_secret': client_secret}), 201


@oauth_bp.post('/token')
def issue_token():
    """Issue an access token for a registered client."""
    data = request.get_json() or {}
    client_id = data.get('client_id')
    client_secret = data.get('client_secret')
    client = OAuthClient.query.filter_by(client_id=client_id, client_secret=client_secret).first()
    if not client:
        return jsonify({'error': 'invalid_client'}), 401
    ttl = data.get('ttl', 3600)
    token = secrets.token_hex(16)
    expires_at = datetime.utcnow() + timedelta(seconds=ttl)
    oauth_token = OAuthToken(token=token, client_id=client_id, expires_at=expires_at)
    db.session.add(oauth_token)
    db.session.commit()
    return jsonify({'access_token': token, 'token_type': 'bearer', 'expires_in': ttl}), 200

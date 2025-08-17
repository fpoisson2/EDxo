"""OAuth endpoints for dynamic client registration and token issuance."""

from datetime import datetime, timedelta
import secrets
import hashlib
import base64

from flask import Blueprint, jsonify, request, url_for, redirect, render_template
from flask_login import login_required, current_user

from ..models import (
    OAuthClient,
    OAuthToken,
    OAuthAuthorizationCode,
    db,
)
from ...extensions import csrf

oauth_bp = Blueprint('oauth', __name__)


@oauth_bp.get('/.well-known/oauth-authorization-server')
@csrf.exempt
def oauth_metadata():
    """Expose OAuth server metadata for discovery."""
    return (
        jsonify(
            {
                'issuer': request.url_root.rstrip('/'),
                'authorization_endpoint': url_for('oauth.authorize', _external=True),
                'token_endpoint': url_for('oauth.issue_token', _external=True),
                'registration_endpoint': url_for('oauth.register_client', _external=True),
                'response_types_supported': ['code'],
                'grant_types_supported': ['authorization_code', 'refresh_token'],
                'code_challenge_methods_supported': ['S256'],
                'token_endpoint_auth_methods_supported': ['none'],
            }
        ),
        200,
    )


@oauth_bp.get('/.well-known/oauth-protected-resource')
@csrf.exempt
def resource_metadata():
    """Expose metadata for the protected resource."""
    resource = request.url_root.rstrip('/')
    return (
        jsonify(
            {
                'resource': resource,
                'authorization_servers': [resource],
                'scopes_supported': ['mcp:read', 'mcp:write'],
            }
        ),
        200,
    )


@oauth_bp.post('/register')
@csrf.exempt
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
@csrf.exempt
def issue_token():
    """Issue an access token for a registered client.

    OAuth token requests are ``application/x-www-form-urlencoded``. To remain
    compatible with tests and legacy clients we also accept JSON payloads, but
    the form body takes precedence.
    """
    data = request.form.to_dict()
    if not data:
        data = request.get_json(silent=True) or {}

    client_id = data.get('client_id')
    client_secret = data.get('client_secret')
    client = OAuthClient.query.filter_by(client_id=client_id).first()
    if not client or (client_secret and client.client_secret != client_secret):
        return jsonify({'error': 'invalid_client'}), 401

    grant_type = data.get('grant_type', 'client_credentials')
    ttl = int(data.get('ttl', 3600))

    if grant_type == 'authorization_code':
        code = data.get('code')
        code_verifier = data.get('code_verifier')
        if not code or not code_verifier:
            return jsonify({'error': 'invalid_request'}), 400
        auth_code = OAuthAuthorizationCode.query.filter_by(code=code, client_id=client_id).first()
        if not auth_code or auth_code.expires_at <= datetime.utcnow():
            return jsonify({'error': 'invalid_grant'}), 400
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b'=').decode()
        if auth_code.code_challenge != expected:
            return jsonify({'error': 'invalid_grant'}), 400
        user_id = auth_code.user_id
        db.session.delete(auth_code)
    else:
        user_id = None

    token = secrets.token_hex(16)
    expires_at = datetime.utcnow() + timedelta(seconds=ttl)
    oauth_token = OAuthToken(
        token=token,
        client_id=client_id,
        user_id=user_id,
        expires_at=expires_at,
    )
    db.session.add(oauth_token)
    db.session.commit()
    return jsonify({'access_token': token, 'token_type': 'bearer', 'expires_in': ttl}), 200


@oauth_bp.route('/authorize', methods=['GET', 'POST'])
@login_required
def authorize():
    """Display a consent page and issue an authorization code."""
    client_id = request.args.get('client_id')
    redirect_uri = request.args.get('redirect_uri')
    code_challenge = request.values.get('code_challenge')
    state = request.values.get('state')
    client = OAuthClient.query.filter_by(client_id=client_id).first()
    if not client or (client.redirect_uri and client.redirect_uri != redirect_uri):
        return jsonify({'error': 'invalid_client'}), 400

    if request.method == 'POST' and request.form.get('confirm') == 'yes':
        code = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        auth_code = OAuthAuthorizationCode(
            code=code,
            client_id=client_id,
            user_id=current_user.id,
            code_challenge=code_challenge,
            expires_at=expires_at,
        )
        db.session.add(auth_code)
        db.session.commit()
        redirect_url = f"{redirect_uri}?code={code}"
        if state:
            redirect_url += f"&state={state}"
        return redirect(redirect_url)

    return render_template(
        'oauth/authorize.html',
        client=client,
        code_challenge=code_challenge,
        state=state,
    )

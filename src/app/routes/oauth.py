"""OAuth endpoints for dynamic client registration and token issuance."""

from datetime import datetime, timedelta
import secrets
import hashlib
import base64
from typing import Dict

from flask import Blueprint, jsonify, request, url_for, redirect, render_template
from flask_login import login_required, current_user

from ..models import (
    OAuthClient,
    OAuthToken,
    db,
)
from ...extensions import csrf

oauth_bp = Blueprint('oauth', __name__)


AUTH_CODES: Dict[str, Dict[str, object]] = {}
TOKEN_RESOURCES: Dict[str, str] = {}


def canonical_mcp_resource() -> str:
    """Return the canonical MCP server URI (without trailing slash).

    We expose the MCP server over SSE under '/sse/'. The canonical resource
    is the absolute URI to that path without a trailing slash, as recommended
    by the MCP Authorization spec (RFC 8707 alignment).
    """
    base = request.url_root.rstrip('/')
    return f"{base}/sse"


def b64url_no_pad(data: bytes) -> str:
    """Return URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def issue_auth_code(client_id: str, redirect_uri: str, code_challenge: str, scope: str, user_id: int) -> str:
    """Generate and store a short-lived authorization code."""
    code = secrets.token_urlsafe(32)
    AUTH_CODES[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "scope": scope,
        "user_id": user_id,
        "expires_at": datetime.utcnow() + timedelta(minutes=5),
    }
    return code


def _json_error(status: int, error: str, description: str):
    resp = jsonify(error=error, error_description=description)
    resp.status_code = status
    resp.headers[
        "WWW-Authenticate"
    ] = (
        f'Bearer resource_metadata="{request.url_root.rstrip("/")}/.well-known/oauth-protected-resource"'
    )
    return resp


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
    resource = canonical_mcp_resource()
    return (
        jsonify(
            {
                'resource': resource,
                # The AS lives at the same origin; clients will fetch
                # '/.well-known/oauth-authorization-server' under it.
                'authorization_servers': [request.url_root.rstrip('/')],
                'scopes_supported': ['mcp:read', 'mcp:write'],
            }
        ),
        200,
    )


@oauth_bp.post('/register')
@csrf.exempt
def register_client():
    """Register a public OAuth client using dynamic client registration."""
    data = request.get_json(force=True, silent=True) or {}
    redirect_uris = data.get('redirect_uris') or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return (
            jsonify(
                error='invalid_client_metadata',
                error_description='redirect_uris required',
            ),
            400,
        )

    client_name = data.get('client_name')
    client_id = secrets.token_urlsafe(24)
    # store only the first redirect URI since the model supports a single value
    client = OAuthClient(
        client_id=client_id,
        client_secret='',
        name=client_name,
        redirect_uri=redirect_uris[0],
    )
    db.session.add(client)
    db.session.commit()

    import time

    return (
        jsonify(
            {
                'client_id': client_id,
                'client_id_issued_at': int(time.time()),
                'token_endpoint_auth_method': 'none',
                'redirect_uris': redirect_uris,
                'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'],
                'application_type': 'web',
            }
        ),
        201,
    )


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
        return _json_error(401, 'invalid_client', 'Client authentication failed')

    grant_type = data.get('grant_type', 'client_credentials')
    resource = data.get('resource')
    if not resource:
        return _json_error(400, 'invalid_request', 'resource parameter required')
    ttl = int(data.get('ttl', 3600))

    if grant_type == 'authorization_code':
        code = data.get('code')
        code_verifier = data.get('code_verifier')
        redirect_uri = data.get('redirect_uri')
        if not code or not code_verifier or not redirect_uri:
            return _json_error(401, 'unauthorized', 'Invalid code')
        record = AUTH_CODES.pop(code, None)
        if (
            not record
            or record['client_id'] != client_id
            or record['redirect_uri'] != redirect_uri
            or record['expires_at'] <= datetime.utcnow()
        ):
            return _json_error(401, 'unauthorized', 'Invalid code')
        calc_challenge = b64url_no_pad(hashlib.sha256(code_verifier.encode()).digest())
        if calc_challenge != record['code_challenge']:
            return _json_error(401, 'unauthorized', 'Bad PKCE verifier')
        # Enforce audience binding by matching the resource
        if record.get('resource') and record['resource'] != resource:
            return _json_error(401, 'unauthorized', 'Bad resource audience')
        user_id = record['user_id']
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
    # Cache the resource audience in-memory for verifier binding checks
    TOKEN_RESOURCES[token] = resource
    return jsonify({'access_token': token, 'token_type': 'bearer', 'expires_in': ttl}), 200


@oauth_bp.route('/authorize', methods=['GET', 'POST'])
@login_required
def authorize():
    """Display a consent page and issue an authorization code."""
    client_id = request.args.get('client_id')
    redirect_uri = request.args.get('redirect_uri')
    code_challenge = request.values.get('code_challenge')
    state = request.values.get('state')
    scope = request.values.get('scope')
    resource = request.values.get('resource')
    client = OAuthClient.query.filter_by(client_id=client_id).first()
    if not client or (client.redirect_uri and client.redirect_uri != redirect_uri):
        return jsonify({'error': 'invalid_client'}), 400

    if request.method == 'POST' and request.form.get('confirm') == 'yes':
        code = issue_auth_code(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            user_id=current_user.id,
        )
        # Also persist the resource for this short-lived code
        if resource:
            AUTH_CODES[code]['resource'] = resource
        redirect_url = f"{redirect_uri}?code={code}"
        if state:
            redirect_url += f"&state={state}"
        return redirect(redirect_url)

    return render_template(
        'oauth/authorize.html',
        client=client,
        code_challenge=code_challenge,
        state=state,
        resource=resource,
    )

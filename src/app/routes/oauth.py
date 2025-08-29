"""OAuth endpoints for dynamic client registration and token issuance.

Adds INFO logs to help diagnose OAuth/MCP integration behind Nginx.
Sensitive headers are redacted.
"""

from datetime import timedelta
from src.utils.datetime_utils import now_utc, ensure_aware_utc
import secrets
import hashlib
import base64
from typing import Dict
import logging

from flask import Blueprint, jsonify, request, url_for, redirect, render_template
from flask_login import login_required, current_user

from ..models import (
    OAuthClient,
    OAuthToken,
    OAuthAuthorizationCode,
    db,
)
from ...extensions import csrf
from ...utils.logging_config import get_logger, redact_headers

oauth_bp = Blueprint('oauth', __name__)
logger = get_logger(__name__)


TOKEN_RESOURCES: Dict[str, str] = {}


def canonical_mcp_resource() -> str:
    """Return the canonical MCP server URI (no trailing slash).

    We expose the MCP server over SSE under '/sse'. The canonical resource
    must match what the verifier reconstructs, e.g. 'https://host/sse'.
    """
    base = request.url_root.rstrip('/')
    resource = f"{base}/sse"
    logger.info("OAuth: canonical MCP resource resolved", extra={
        "resource": resource,
        "host": request.host,
        "scheme": request.scheme,
    })
    return resource


def b64url_no_pad(data: bytes) -> str:
    """Return URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def issue_auth_code(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    scope: str,
    user_id: int,
    resource: str | None,
) -> str:
    """Generate and persist a short-lived authorization code.

    Persisting in DB ensures multi-worker/process consistency behind a proxy.
    """
    code = secrets.token_urlsafe(32)
    record = OAuthAuthorizationCode(
        code=code,
        client_id=client_id,
        user_id=user_id,
        code_challenge=code_challenge,
        expires_at=now_utc() + timedelta(minutes=5),
        redirect_uri=redirect_uri,
        resource=(resource.rstrip('/') if resource else None),
    )
    db.session.add(record)
    db.session.commit()
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
    payload = {
        'issuer': request.url_root.rstrip('/'),
        'authorization_endpoint': url_for('oauth.authorize', _external=True),
        'token_endpoint': url_for('oauth.issue_token', _external=True),
        'registration_endpoint': url_for('oauth.register_client', _external=True),
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported': ['S256'],
        'token_endpoint_auth_methods_supported': ['none'],
    }
    logger.info("OAuth: served authorization server metadata", extra={
        "host": request.host,
        "scheme": request.scheme,
        "headers": redact_headers(request.headers),
    })
    return (
        jsonify(payload),
        200,
    )


@oauth_bp.get('/.well-known/oauth-protected-resource')
@csrf.exempt
def resource_metadata():
    """Expose metadata for the protected resource."""
    resource = canonical_mcp_resource()
    payload = {
        'resource': resource,
        # Per tests and audience-binding, set AS to the resource value
        # so that authorization_servers == [resource].
        'authorization_servers': [resource],
        'scopes_supported': ['mcp:read', 'mcp:write'],
    }
    logger.info("OAuth: served protected-resource metadata", extra={
        "resource": resource,
        "host": request.host,
        "scheme": request.scheme,
        "headers": redact_headers(request.headers),
    })
    return (jsonify(payload), 200)


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
    logger.info("OAuth: client registered", extra={
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "remote_addr": request.remote_addr,
        "headers": redact_headers(request.headers),
    })

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
        logger.info("OAuth: invalid_client at token endpoint", extra={
            "client_id": client_id,
            "has_secret": bool(client_secret),
            "remote_addr": request.remote_addr,
        })
        return _json_error(401, 'invalid_client', 'Client authentication failed')

    grant_type = data.get('grant_type', 'client_credentials')
    resource = data.get('resource')
    if not resource:
        # Backward compatibility: default to canonical MCP resource when missing
        resource = canonical_mcp_resource()
        logger.info(
            "OAuth: token request missing resource → defaulted",
            extra={
                "client_id": client_id,
                "grant_type": grant_type,
                "resource": resource,
            },
        )
    # Normalize resource to avoid trailing-slash mismatches
    resource = (resource or "").rstrip('/')
    ttl = int(data.get('ttl', 3600))

    if grant_type == 'authorization_code':
        code = data.get('code')
        code_verifier = data.get('code_verifier')
        redirect_uri = data.get('redirect_uri')
        if not code or not code_verifier or not redirect_uri:
            logger.info("OAuth: authorization_code missing fields", extra={
                "client_id": client_id,
                "has_code": bool(code),
                "has_verifier": bool(code_verifier),
                "has_redirect": bool(redirect_uri),
            })
            return _json_error(401, 'unauthorized', 'Invalid code')
        # Look up and invalidate one-time code in DB
        record = OAuthAuthorizationCode.query.filter_by(code=code).first()
        if not record:
            logger.info("OAuth: invalid or expired code", extra={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
            })
            return _json_error(401, 'unauthorized', 'Invalid code')
        if (
            record.client_id != client_id
            or (record.redirect_uri and record.redirect_uri != redirect_uri)
            or ensure_aware_utc(record.expires_at) <= now_utc()
        ):
            logger.info("OAuth: invalid or expired code", extra={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
            })
            return _json_error(401, 'unauthorized', 'Invalid code')
        calc_challenge = b64url_no_pad(hashlib.sha256(code_verifier.encode()).digest())
        if calc_challenge != record.code_challenge:
            logger.info("OAuth: PKCE verifier mismatch", extra={
                "client_id": client_id,
            })
            return _json_error(401, 'unauthorized', 'Bad PKCE verifier')
        # Enforce audience binding by matching the resource
        if getattr(record, 'resource', None) and record.resource != resource:
            logger.info("OAuth: audience mismatch", extra={
                "client_id": client_id,
                "requested_resource": resource,
                "bound_resource": record.resource,
            })
            return _json_error(401, 'unauthorized', 'Bad resource audience')
        user_id = record.user_id
        # Invalidate one-time code
        try:
            db.session.delete(record)
            db.session.commit()
        except Exception:
            db.session.rollback()
    else:
        user_id = None

    token = secrets.token_hex(16)
    expires_at = now_utc() + timedelta(seconds=ttl)
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
    logger.info("OAuth: access token issued", extra={
        "client_id": client_id,
        "grant_type": grant_type,
        "resource": resource,
        "ttl": ttl,
        "user_bound": bool(user_id),
    })
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
        logger.info("OAuth: authorize invalid_client or redirect mismatch", extra={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        })
        return jsonify({'error': 'invalid_client'}), 400

    if request.method == 'POST' and request.form.get('confirm') == 'yes':
        code = issue_auth_code(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            user_id=current_user.id,
            resource=(resource.rstrip('/') if resource else None),
        )
        logger.info("OAuth: authorization code issued", extra={
            "client_id": client_id,
            "has_state": bool(state),
            "resource": resource,
        })
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


@oauth_bp.get('/debug/headers')
@csrf.exempt
def debug_headers():
    """Return a sanitized view of request headers and forwarding info.

    Marked public to ease reverse-proxy debugging. Remove after diagnosis.
    """
    meta = {
        "method": request.method,
        "url": request.url,
        "base_url": request.base_url,
        "url_root": request.url_root,
        "remote_addr": request.remote_addr,
        "scheme": request.scheme,
        "path": request.path,
    }
    data = {
        "meta": meta,
        "headers": redact_headers(request.headers),
        # Avoid reserved LogRecord key name 'args'
        "query": request.args.to_dict(flat=True),
    }
    logger.info("Debug headers", extra=data)
    return jsonify(data), 200

# Mark route as public for the app.before_request guard
debug_headers.is_public = True  # type: ignore[attr-defined]

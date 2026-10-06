import base64
import hashlib
import ipaddress
import os
import secrets
import socket
import time
from dataclasses import asdict
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from gateway_mcp.services.observability import record_auth_failure
from gateway_mcp.services.policy import (
    GatewayActor,
    actor_from_claims,
    actor_from_user_info,
    has_scope,
    is_user_allowed,
)
from gateway_mcp.services.storage import (
    consume_gateway_oauth_refresh_token,
    gateway_oauth_access_token_revoked,
    revoke_gateway_oauth_access_token,
    revoke_gateway_oauth_refresh_token,
    save_gateway_oauth_refresh_token,
    save_user_oauth_token,
)
from gateway_mcp.services.storage import pop_oauth_state as pop_postgres_oauth_state
from gateway_mcp.services.storage import save_oauth_state as save_postgres_oauth_state

YANDEX_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
YANDEX_TOKEN_URL = "https://oauth.yandex.ru/token"
YANDEX_USERINFO_URL = "https://login.yandex.ru/info"
YANDEX_VERIFICATION_CODE_URL = "https://oauth.yandex.ru/verification_code"
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

_OAUTH_STATES: dict[str, dict[str, Any]] = {}
_OAUTH_REFRESH_TOKENS: dict[str, dict[str, Any]] = {}
_REVOKED_ACCESS_TOKENS: dict[str, float] = {}
_CIMD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
OAUTH_CLIENT_ID_PREFIX = "gateway-client."
OAUTH_REFRESH_TOKEN_PREFIX = "gateway-refresh."
DEFAULT_SUPPORTED_SCOPES = [
    "access:admin",
    "access:read",
    "access:request",
    "approvals:admin",
    "approvals:read",
    "approvals:write",
    "bitrix24:read",
    "bitrix24:write",
    "calendar:read",
    "company:read",
    "factory:claim",
    "factory:read",
    "factory:write",
    "factory:admin",
    "factory:projects:write",
    "factory:git",
    "files:read",
    "files:write",
    "gitlab:read",
    "gitlab:write",
    "google_drive:read",
    "google_drive:write",
    "google_docs:read",
    "google_docs:write",
    "google_sheets:read",
    "google_sheets:write",
    "infra:read",
    "infra:ssh:exec",
    "mail:read",
    "mail:send",
    "llm:proxy",
    "memory:admin",
    "memory:read",
    "memory:write",
    "metrika:read",
    "notifications:read",
    "notifications:write",
    "openrouter:audio",
    "process:read",
    "privacy:use",
    "skills:read",
    "telemetry:read",
    "telemetry:write",
    "telegram:read",
    "telegram:write",
    "tools:call",
    "tools:read",
    "tracker:read",
    "tracker:write",
    "webmaster:read",
    "yandex_disk:read",
    "yandex_disk:write",
    "yonote:read",
    "yonote:write",
]


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.casefold() in {"1", "true", "yes", "on"}


def auth_enabled() -> bool:
    return _bool_env("GATEWAY_AUTH_ENABLED", False)


def cimd_enabled() -> bool:
    return _bool_env("GATEWAY_CIMD_ENABLED", False)


def issuer_url() -> str:
    return os.getenv("GATEWAY_ISSUER_URL", "http://localhost:8000").rstrip("/")


def resource_url() -> str:
    return os.getenv("GATEWAY_RESOURCE_URL", f"{issuer_url()}/mcp").rstrip("/")


def public_url() -> str:
    return os.getenv("GATEWAY_PUBLIC_URL", issuer_url()).rstrip("/")


def required_scopes() -> list[str]:
    raw = os.getenv("GATEWAY_REQUIRED_SCOPES", "skills:read")
    return [scope.strip() for scope in raw.split(",") if scope.strip()]


def supported_scopes() -> list[str]:
    raw = os.getenv("GATEWAY_SUPPORTED_SCOPES", "")
    if raw:
        return [
            scope.strip() for scope in raw.replace(",", " ").split() if scope.strip()
        ]
    return list(DEFAULT_SUPPORTED_SCOPES)


def jwt_secret() -> str:
    secret = os.getenv("GATEWAY_JWT_SECRET", "")
    if auth_enabled() and not secret:
        raise RuntimeError(
            "GATEWAY_JWT_SECRET must be set when GATEWAY_AUTH_ENABLED=true"
        )
    return secret or "dev-gateway-secret"


def token_ttl_seconds() -> int:
    return int(os.getenv("GATEWAY_TOKEN_TTL_SECONDS", "31536000"))


def refresh_token_ttl_seconds() -> int:
    return int(os.getenv("GATEWAY_REFRESH_TOKEN_TTL_SECONDS", "31536000"))


def mcp_auth_settings() -> AuthSettings | None:
    if not auth_enabled():
        return None
    return AuthSettings(
        issuer_url=issuer_url(),
        resource_server_url=resource_url(),
        required_scopes=supported_scopes(),
    )


class GatewayJwtVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = verify_gateway_token_claims(token)
        except Exception as exc:  # noqa: BLE001 - authentication boundary fails closed
            record_auth_failure(exc.__class__.__name__)
            return None

        scopes = claims.get("scope", "")
        if isinstance(scopes, str):
            scope_values = [scope for scope in scopes.split(" ") if scope]
        else:
            scope_values = list(scopes or [])

        # FastMCP uses AuthSettings.required_scopes both as transport-level required
        # scopes and as protected-resource metadata. GatewayMCP keeps authorization
        # at tool level, so any valid Gateway token may open the MCP transport while
        # current_actor() and per-tool checks still use the real JWT claims.
        transport_scopes = sorted(set(scope_values).union(supported_scopes()))
        return AccessToken(
            token=token,
            client_id=str(claims.get("sub", "")),
            scopes=transport_scopes,
            expires_at=int(claims.get("exp", 0)) or None,
            resource=str(claims.get("aud", "")),
        )


def token_verifier() -> GatewayJwtVerifier | None:
    return GatewayJwtVerifier() if auth_enabled() else None


def decode_gateway_token(token: str, *, verify: bool) -> dict[str, Any]:
    options = {
        "verify_signature": verify,
        "verify_exp": verify,
        "verify_aud": verify,
        "verify_iss": verify,
    }
    kwargs: dict[str, Any] = {
        "algorithms": ["HS256"],
        "options": options,
    }
    if verify:
        kwargs["audience"] = resource_url()
        kwargs["issuer"] = issuer_url()
    return jwt.decode(token, jwt_secret(), **kwargs)


def verify_gateway_token_claims(token: str) -> dict[str, Any]:
    claims = decode_gateway_token(token, verify=True)
    if _access_token_revoked(str(claims.get("jti") or "")):
        raise PermissionError("Gateway access token is revoked")
    actor_from_claims(claims)
    return claims


def current_actor() -> GatewayActor:
    if not auth_enabled():
        return GatewayActor(
            subject="dev:local", login="local-dev", groups=("admins",), scopes=("*",)
        )

    access_token = get_access_token()
    if access_token is None:
        return GatewayActor(subject="anonymous")

    try:
        return actor_from_claims(decode_gateway_token(access_token.token, verify=False))
    except jwt.PyJWTError:
        return GatewayActor(
            subject=access_token.client_id, scopes=tuple(access_token.scopes)
        )


def require_scope(required_scope: str, *, tool: str) -> GatewayActor:
    actor = current_actor()
    if has_scope(actor, required_scope):
        return actor
    raise PermissionError(f"missing required scope for {tool}: {required_scope}")


def mint_gateway_token(actor: GatewayActor, *, ttl_seconds: int | None = None) -> str:
    now = int(time.time())
    exp = now + (ttl_seconds if ttl_seconds is not None else token_ttl_seconds())
    claims = {
        "iss": issuer_url(),
        "aud": resource_url(),
        "sub": actor.subject,
        "iat": now,
        "exp": exp,
        "jti": secrets.token_urlsafe(24),
        "scope": " ".join(actor.scopes),
        "groups": list(actor.groups),
        "email": actor.email,
        "login": actor.login,
        "yandex_id": actor.yandex_id,
    }
    return jwt.encode(claims, jwt_secret(), algorithm="HS256")


def create_oauth_state(next_url: str = "") -> str:
    return create_oauth_state_payload({"next": next_url}, ttl_seconds=600)


def create_oauth_state_payload(
    payload: dict[str, Any], *, ttl_seconds: int = 600
) -> str:
    state = secrets.token_urlsafe(32)
    expires_at = time.time() + ttl_seconds
    saved_payload = {**payload, "expires_at": expires_at}
    if save_postgres_oauth_state(state, saved_payload, expires_at):
        return state

    _OAUTH_STATES[state] = saved_payload
    return state


def pop_oauth_state(state: str) -> dict[str, Any] | None:
    postgres_value = pop_postgres_oauth_state(state)
    if postgres_value is not None:
        return postgres_value

    value = _OAUTH_STATES.pop(state, None)
    if not value:
        return None
    if value["expires_at"] < time.time():
        return None
    return value


def oauth_authorization_server_metadata() -> dict[str, Any]:
    base = public_url()
    metadata = {
        "issuer": issuer_url(),
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": supported_scopes(),
        "resource_indicators_supported": True,
    }
    if cimd_enabled():
        metadata["client_id_metadata_document_supported"] = True
    return metadata


def register_oauth_client(metadata: dict[str, Any]) -> dict[str, Any]:
    redirect_uris = metadata.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise ValueError("redirect_uris is required")
    normalized_redirects = [
        _validate_oauth_redirect_uri_value(str(uri).strip())
        for uri in redirect_uris
        if str(uri).strip()
    ]
    if not normalized_redirects:
        raise ValueError("redirect_uris is required")
    now = int(time.time())
    client_metadata = {
        "client_name": str(metadata.get("client_name") or "MCP Client"),
        "redirect_uris": normalized_redirects,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "application_type": str(metadata.get("application_type") or "native"),
        "iat": now,
    }
    client_id = OAUTH_CLIENT_ID_PREFIX + jwt.encode(
        {
            "typ": "gateway_oauth_client",
            "iat": now,
            "exp": now + int(os.getenv("GATEWAY_OAUTH_CLIENT_TTL_SECONDS", "7776000")),
            "metadata": client_metadata,
        },
        jwt_secret(),
        algorithm="HS256",
    )
    return {
        "client_id": client_id,
        "client_id_issued_at": now,
        **client_metadata,
    }


def decode_oauth_client(client_id: str) -> dict[str, Any]:
    if not client_id.startswith(OAUTH_CLIENT_ID_PREFIX):
        raise ValueError("unknown OAuth client_id")
    token = client_id.removeprefix(OAUTH_CLIENT_ID_PREFIX)
    claims = jwt.decode(token, jwt_secret(), algorithms=["HS256"])
    if claims.get("typ") != "gateway_oauth_client":
        raise ValueError("invalid OAuth client_id")
    metadata = claims.get("metadata")
    if not isinstance(metadata, dict):
        raise TypeError("invalid OAuth client metadata")
    return metadata


async def validate_oauth_redirect_uri(
    client_id: str, redirect_uri: str
) -> dict[str, Any]:
    if client_id.startswith("https://"):
        if not cimd_enabled():
            raise ValueError("CIMD client registration is disabled")
        metadata = await fetch_oauth_client_metadata(client_id)
    else:
        metadata = decode_oauth_client(client_id)
    allowed = {str(uri) for uri in metadata.get("redirect_uris", [])}
    if redirect_uri not in allowed:
        raise ValueError("redirect_uri is not registered for this client")
    return metadata


async def build_oauth_authorization_redirect(params: dict[str, str]) -> str:
    if params.get("response_type") != "code":
        raise ValueError("response_type must be code")
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    code_challenge = params.get("code_challenge", "")
    code_challenge_method = params.get("code_challenge_method", "")
    resource = params.get("resource") or resource_url()
    if not client_id or not redirect_uri:
        raise ValueError("client_id and redirect_uri are required")
    await validate_oauth_redirect_uri(client_id, redirect_uri)
    _validate_requested_scopes(params.get("scope", ""))
    if resource.rstrip("/") != resource_url():
        raise ValueError("resource is not served by this authorization server")
    if code_challenge_method != "S256" or not code_challenge:
        raise ValueError("PKCE S256 code_challenge is required")
    oauth_state = create_oauth_state_payload(
        {
            "flow": "mcp_oauth_authorize",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": params.get("scope", ""),
            "client_state": params.get("state", ""),
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "resource": resource,
        },
        ttl_seconds=600,
    )
    return build_yandex_authorize_url(oauth_state)


async def fetch_oauth_client_metadata(client_id: str) -> dict[str, Any]:
    """Fetch and validate an OAuth Client ID Metadata Document."""
    parsed = urlparse(client_id)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path in {"", "/"}:
        raise ValueError("CIMD client_id must be an HTTPS URL with a path")
    _validate_cimd_host(parsed.hostname)

    cached = _CIMD_CACHE.get(client_id)
    if cached and cached[0] > time.time():
        return dict(cached[1])

    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.get(client_id, headers={"Accept": "application/json"})
        response.raise_for_status()
        if len(response.content) > 65536:
            raise ValueError("CIMD document is too large")
        metadata = response.json()

    if not isinstance(metadata, dict):
        raise TypeError("CIMD document must be a JSON object")
    if str(metadata.get("client_id") or "") != client_id:
        raise ValueError("CIMD client_id does not match document URL")
    if not str(metadata.get("client_name") or "").strip():
        raise ValueError("CIMD client_name is required")
    redirect_uris = metadata.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not all(
        isinstance(uri, str) and uri for uri in redirect_uris
    ):
        raise TypeError("CIMD redirect_uris must be a non-empty string array")
    if not redirect_uris:
        raise ValueError("CIMD redirect_uris must be a non-empty string array")

    ttl = _cimd_cache_ttl(response.headers.get("cache-control", ""))
    normalized = dict(metadata)
    _CIMD_CACHE[client_id] = (time.time() + ttl, normalized)
    return normalized


def _validate_cimd_host(hostname: str) -> None:
    allowed_hosts = {
        value.strip().casefold()
        for value in os.getenv("GATEWAY_CIMD_ALLOWED_HOSTS", "").split(",")
        if value.strip()
    }
    normalized = hostname.rstrip(".").casefold()
    if allowed_hosts and normalized not in allowed_hosts:
        raise ValueError("CIMD host is not allowlisted")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError("CIMD host cannot be resolved") from exc
    if not addresses:
        raise ValueError("CIMD host cannot be resolved")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise ValueError("CIMD host must resolve only to public addresses")


def _cimd_cache_ttl(cache_control: str) -> int:
    for directive in cache_control.split(","):
        key, _, value = directive.strip().partition("=")
        if key.casefold() == "max-age" and value.isdigit():
            return min(max(int(value), 60), 86400)
    return 3600


def build_redirect_uri_with_params(uri: str, params: dict[str, str]) -> str:
    parsed = urlparse(uri)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: value for key, value in params.items() if value != ""})
    return urlunparse(parsed._replace(query=urlencode(query)))


def create_mcp_authorization_code(
    actor: GatewayActor, oauth_state: dict[str, Any]
) -> str:
    return create_oauth_state_payload(
        {
            "flow": "mcp_oauth_code",
            "actor": actor_payload(actor),
            "client_id": str(oauth_state["client_id"]),
            "redirect_uri": str(oauth_state["redirect_uri"]),
            "scope": str(oauth_state.get("scope") or ""),
            "code_challenge": str(oauth_state["code_challenge"]),
            "resource": str(oauth_state.get("resource") or resource_url()),
        },
        ttl_seconds=600,
    )


def exchange_mcp_authorization_code(
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    resource: str,
) -> dict[str, Any]:
    payload = pop_oauth_state(code)
    if not payload or payload.get("flow") != "mcp_oauth_code":
        raise ValueError("invalid or expired authorization code")
    if str(payload.get("client_id") or "") != client_id:
        raise ValueError("client_id does not match authorization code")
    if str(payload.get("redirect_uri") or "") != redirect_uri:
        raise ValueError("redirect_uri does not match authorization code")
    expected_resource = str(payload.get("resource") or resource_url())
    if resource and resource != expected_resource:
        raise ValueError("resource does not match authorization code")
    _verify_pkce_s256(str(payload.get("code_challenge") or ""), code_verifier)

    actor_data = payload.get("actor")
    if not isinstance(actor_data, dict):
        raise TypeError("authorization code has no actor")
    actor = GatewayActor(
        subject=str(actor_data.get("subject") or ""),
        email=str(actor_data.get("email") or ""),
        login=str(actor_data.get("login") or ""),
        yandex_id=str(actor_data.get("yandex_id") or ""),
        groups=tuple(actor_data.get("groups") or ()),
        scopes=tuple(actor_data.get("scopes") or ()),
    )
    _validate_requested_scopes(str(payload.get("scope") or ""))
    return _issue_oauth_tokens(
        actor=actor,
        client_id=client_id,
        resource=expected_resource,
    )


def exchange_mcp_refresh_token(
    *, refresh_token: str, client_id: str, resource: str
) -> dict[str, Any]:
    if not refresh_token.startswith(OAUTH_REFRESH_TOKEN_PREFIX):
        raise ValueError("invalid refresh token")
    payload = _consume_refresh_token(refresh_token)
    if not payload:
        raise ValueError("invalid or expired refresh token")
    if str(payload.get("client_id") or "") != client_id:
        raise ValueError("client_id does not match refresh token")
    expected_resource = str(payload.get("resource") or resource_url()).rstrip("/")
    if resource and resource.rstrip("/") != expected_resource:
        raise ValueError("resource does not match refresh token")

    actor_data = payload.get("actor_payload") or payload.get("actor")
    if isinstance(actor_data, str):
        import json

        actor_data = json.loads(actor_data)
    if not isinstance(actor_data, dict):
        raise TypeError("refresh token has no actor")
    user_info = {
        "id": str(actor_data.get("yandex_id") or ""),
        "uid": str(actor_data.get("yandex_id") or ""),
        "login": str(actor_data.get("login") or ""),
        "default_email": str(actor_data.get("email") or ""),
        "email": str(actor_data.get("email") or ""),
    }
    if not is_user_allowed(user_info):
        raise PermissionError("Gateway user is no longer allowed")
    actor = actor_from_user_info(user_info)
    return _issue_oauth_tokens(
        actor=actor,
        client_id=client_id,
        resource=expected_resource,
    )


def revoke_mcp_oauth_token(token: str) -> None:
    if token.startswith(OAUTH_REFRESH_TOKEN_PREFIX):
        token_hash = _oauth_token_hash(token)
        if not revoke_gateway_oauth_refresh_token(token_hash):
            _OAUTH_REFRESH_TOKENS.pop(token_hash, None)
        return
    try:
        claims = decode_gateway_token(token, verify=True)
    except jwt.PyJWTError:
        return
    jti = str(claims.get("jti") or "")
    expires_at = float(claims.get("exp") or 0)
    if not jti or expires_at <= time.time():
        return
    if not revoke_gateway_oauth_access_token(jti=jti, expires_at_epoch=expires_at):
        _REVOKED_ACCESS_TOKENS[jti] = expires_at


def _issue_oauth_tokens(
    *, actor: GatewayActor, client_id: str, resource: str
) -> dict[str, Any]:
    refresh_token = OAUTH_REFRESH_TOKEN_PREFIX + secrets.token_urlsafe(48)
    expires_at = time.time() + refresh_token_ttl_seconds()
    actor_data = actor_payload(actor)
    resource_value = resource.rstrip("/")
    scope_value = " ".join(actor.scopes)
    payload: dict[str, Any] = {
        "actor_payload": actor_data,
        "client_id": client_id,
        "resource": resource_value,
        "scope": scope_value,
        "expires_at": expires_at,
    }
    token_hash = _oauth_token_hash(refresh_token)
    saved = save_gateway_oauth_refresh_token(
        token_hash=token_hash,
        actor_payload=actor_data,
        client_id=client_id,
        resource=resource_value,
        scope=scope_value,
        expires_at_epoch=expires_at,
    )
    if not saved:
        _OAUTH_REFRESH_TOKENS[token_hash] = payload
    return {
        "access_token": mint_gateway_token(actor),
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": token_ttl_seconds(),
        "scope": scope_value,
    }


def _consume_refresh_token(token: str) -> dict[str, Any] | None:
    token_hash = _oauth_token_hash(token)
    stored = consume_gateway_oauth_refresh_token(token_hash)
    if stored:
        return stored
    payload = _OAUTH_REFRESH_TOKENS.pop(token_hash, None)
    if not payload or float(payload.get("expires_at") or 0) <= time.time():
        return None
    return payload


def _access_token_revoked(jti: str) -> bool:
    if not jti:
        return False
    if gateway_oauth_access_token_revoked(jti):
        return True
    now = time.time()
    expired = [key for key, value in _REVOKED_ACCESS_TOKENS.items() if value <= now]
    for key in expired:
        _REVOKED_ACCESS_TOKENS.pop(key, None)
    return jti in _REVOKED_ACCESS_TOKENS


def _oauth_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_requested_scopes(raw_scope: str) -> list[str]:
    requested = [scope for scope in raw_scope.replace(",", " ").split() if scope]
    unknown = sorted(set(requested).difference(supported_scopes()))
    if unknown:
        raise ValueError(f"unsupported OAuth scope: {', '.join(unknown)}")
    return requested


def _validate_oauth_redirect_uri_value(uri: str) -> str:
    parsed = urlparse(uri)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("redirect_uri must be an absolute URI")
    if parsed.fragment or parsed.username or parsed.password:
        raise ValueError("redirect_uri must not contain a fragment or userinfo")
    scheme = parsed.scheme.casefold()
    hostname = (parsed.hostname or "").casefold()
    if scheme == "https" and hostname:
        return uri
    if scheme == "http" and _loopback_hostname(hostname):
        return uri
    custom_schemes = {
        value.strip().casefold()
        for value in os.getenv("GATEWAY_OAUTH_ALLOWED_CUSTOM_SCHEMES", "").split(",")
        if value.strip()
    }
    if scheme in custom_schemes:
        return uri
    raise ValueError("redirect_uri must use HTTPS or an HTTP loopback address")


def _loopback_hostname(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _verify_pkce_s256(expected_challenge: str, verifier: str) -> None:
    actual = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    if not secrets.compare_digest(actual, expected_challenge):
        raise ValueError("invalid PKCE code_verifier")


def yandex_redirect_uri() -> str:
    return f"{public_url()}/auth/yandex/callback"


def google_redirect_uri() -> str:
    return f"{public_url()}/auth/google/callback"


def yandex_oauth_config(provider: str = "yandex") -> dict[str, str]:
    if provider == "yandex-disk":
        return {
            "client_id": os.getenv("YANDEX_DISK_OAUTH_CLIENT_ID", ""),
            "client_secret": os.getenv("YANDEX_DISK_OAUTH_CLIENT_SECRET", ""),
            "scopes": os.getenv(
                "YANDEX_DISK_OAUTH_SCOPES",
                "cloud_api:disk.read cloud_api:disk.write cloud_api:disk.info",
            ),
            "env_prefix": "YANDEX_DISK_OAUTH",
        }
    return {
        "client_id": os.getenv("YANDEX_OAUTH_CLIENT_ID", ""),
        "client_secret": os.getenv("YANDEX_OAUTH_CLIENT_SECRET", ""),
        "scopes": os.getenv("YANDEX_OAUTH_SCOPES", ""),
        "env_prefix": "YANDEX_OAUTH",
    }


def google_oauth_config() -> dict[str, str]:
    return {
        "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
        "scopes": os.getenv(
            "GOOGLE_OAUTH_SCOPES",
            "openid email profile https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/documents",
        ),
        "env_prefix": "GOOGLE_OAUTH",
    }


def build_yandex_authorize_url(
    state: str,
    *,
    login_hint: str = "",
    force_confirm: bool = False,
    provider: str = "yandex",
    redirect_uri: str | None = None,
) -> str:
    config = yandex_oauth_config(provider)
    client_id = config["client_id"]
    if not client_id:
        raise RuntimeError(
            f"{config['env_prefix']}_CLIENT_ID must be set for Yandex OAuth login"
        )

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri or yandex_redirect_uri(),
    }
    if state:
        params["state"] = state
    scopes = config["scopes"].strip()
    if scopes:
        params["scope"] = scopes
    if login_hint:
        params["login_hint"] = login_hint
    if force_confirm:
        params["force_confirm"] = "yes"
    return f"{YANDEX_AUTHORIZE_URL}?{urlencode(params)}"


def build_google_authorize_url(
    state: str,
    *,
    login_hint: str = "",
    force_confirm: bool = False,
    redirect_uri: str | None = None,
) -> str:
    config = google_oauth_config()
    client_id = config["client_id"]
    if not client_id:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID must be set for Google OAuth login")

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri or google_redirect_uri(),
        "access_type": "offline",
        "include_granted_scopes": "true",
    }
    if state:
        params["state"] = state
    scopes = config["scopes"].strip()
    if scopes:
        params["scope"] = scopes
    if login_hint:
        params["login_hint"] = login_hint
    if force_confirm:
        params["prompt"] = "consent"
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_yandex_code(
    code: str,
    *,
    provider: str = "yandex",
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    config = yandex_oauth_config(provider)
    client_id = config["client_id"]
    client_secret = config["client_secret"]
    if not client_id or not client_secret:
        raise RuntimeError(
            f"{config['env_prefix']}_CLIENT_ID and {config['env_prefix']}_CLIENT_SECRET must be set"
        )

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            YANDEX_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri or yandex_redirect_uri(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()


async def exchange_google_code(
    code: str, *, redirect_uri: str | None = None
) -> dict[str, Any]:
    config = google_oauth_config()
    client_id = config["client_id"]
    client_secret = config["client_secret"]
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET must be set"
        )

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri or google_redirect_uri(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()


async def refresh_google_access_token(refresh_token: str) -> dict[str, Any]:
    config = google_oauth_config()
    client_id = config["client_id"]
    client_secret = config["client_secret"]
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET must be set"
        )

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()


async def fetch_yandex_user_info(yandex_access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            YANDEX_USERINFO_URL,
            params={"format": "json"},
            headers={"Authorization": f"OAuth {yandex_access_token}"},
        )
        response.raise_for_status()
        return response.json()


async def fetch_google_user_info(google_access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={
                "Authorization": f"Bearer {google_access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()


async def fetch_yandex_disk_user_info(yandex_access_token: str) -> dict[str, Any]:
    base_url = os.getenv(
        "YANDEX_DISK_API_BASE_URL", "https://cloud-api.yandex.net/v1/disk"
    ).rstrip("/")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{base_url}/",
            headers={
                "Authorization": f"OAuth {yandex_access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()

    user = data.get("user") if isinstance(data, dict) else {}
    if not isinstance(user, dict):
        user = {}
    login = str(user.get("login") or "")
    uid = str(user.get("uid") or user.get("id") or "")
    email = login if "@" in login else ""
    return {
        "id": uid,
        "uid": uid,
        "login": login,
        "default_email": email,
        "email": email,
    }


async def login_with_yandex_code(code: str) -> tuple[GatewayActor, str]:
    token_payload = await exchange_yandex_code(code)
    yandex_token = str(token_payload["access_token"])
    user_info = await fetch_yandex_user_info(yandex_token)
    if not is_user_allowed(user_info):
        record_auth_failure("user_not_allowed")
        raise PermissionError("Yandex user is not allowed by Gateway policy")

    actor = actor_from_user_info(user_info)
    _save_yandex_actor_token(
        actor_subject=actor.subject,
        actor=actor,
        yandex_token=yandex_token,
        token_payload=token_payload,
        metadata={"source": "yandex_oauth_login"},
    )
    return actor, mint_gateway_token(actor)


async def bind_yandex_code_to_actor(
    *,
    code: str,
    actor_subject: str,
    expected_login: str = "",
    provider: str = "yandex",
    redirect_uri: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> GatewayActor:
    token_payload = await exchange_yandex_code(
        code, provider=provider, redirect_uri=redirect_uri
    )
    yandex_token = str(token_payload["access_token"])
    if provider == "yandex-disk":
        user_info = await fetch_yandex_disk_user_info(yandex_token)
        yandex_actor = _actor_from_disk_user_info(user_info)
    else:
        user_info = await fetch_yandex_user_info(yandex_token)
        if not is_user_allowed(user_info):
            record_auth_failure("user_not_allowed")
            raise PermissionError("Yandex user is not allowed by Gateway policy")
        yandex_actor = actor_from_user_info(user_info)

    if expected_login and not _matches_yandex_login(yandex_actor, expected_login):
        record_auth_failure("service_oauth_login_mismatch")
        raise PermissionError(
            f"Selected Yandex account does not match expected service login: {expected_login}"
        )
    _save_yandex_actor_token(
        provider=provider,
        actor_subject=actor_subject,
        actor=yandex_actor,
        yandex_token=yandex_token,
        token_payload=token_payload,
        metadata={
            "source": "yandex_service_oauth_bind",
            "provider": provider,
            "bound_actor_subject": actor_subject,
            "yandex_actor_subject": yandex_actor.subject,
            **(metadata or {}),
        },
    )
    return yandex_actor


async def bind_google_code_to_actor(
    *,
    code: str,
    actor_subject: str,
    expected_login: str = "",
    redirect_uri: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> GatewayActor:
    token_payload = await exchange_google_code(code, redirect_uri=redirect_uri)
    google_token = str(token_payload["access_token"])
    refresh_token = str(token_payload.get("refresh_token") or "")
    if not refresh_token:
        raise RuntimeError(
            "Google OAuth did not return a refresh token. Reconnect with consent prompt."
        )

    user_info = await fetch_google_user_info(google_token)
    google_actor = _actor_from_google_user_info(user_info)

    _save_google_actor_token(
        actor_subject=actor_subject,
        actor=google_actor,
        refresh_token=refresh_token,
        token_payload=token_payload,
        metadata={
            "source": "google_oauth_bind",
            "provider": "google",
            "bound_actor_subject": actor_subject,
            "google_actor_subject": google_actor.subject,
            **(metadata or {}),
        },
    )
    return google_actor


def _actor_from_disk_user_info(user_info: dict[str, Any]) -> GatewayActor:
    yandex_id = str(user_info.get("id") or user_info.get("uid") or "")
    login = str(user_info.get("login") or "")
    email = str(user_info.get("default_email") or user_info.get("email") or "")
    subject = f"yandex:{yandex_id or login or email}"
    return GatewayActor(subject=subject, email=email, login=login, yandex_id=yandex_id)


def _actor_from_google_user_info(user_info: dict[str, Any]) -> GatewayActor:
    google_id = str(user_info.get("sub") or user_info.get("id") or "")
    email = str(user_info.get("email") or "")
    login = email.split("@", 1)[0] if email else google_id
    subject = f"google:{google_id or email}"
    return GatewayActor(subject=subject, email=email, login=login, yandex_id="")


def _matches_yandex_login(actor: GatewayActor, expected_login: str) -> bool:
    expected = expected_login.strip().casefold()
    if not expected:
        return True
    candidates = {
        actor.email.strip().casefold(),
        actor.login.strip().casefold(),
    }
    if "@" in expected:
        candidates.add(expected.split("@", 1)[0])
    if "@" not in expected and actor.email:
        candidates.add(actor.email.split("@", 1)[0].strip().casefold())
    return expected in candidates


def _save_yandex_actor_token(
    *,
    provider: str = "yandex",
    actor_subject: str,
    actor: GatewayActor,
    yandex_token: str,
    token_payload: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    save_user_oauth_token(
        provider=provider,
        actor_subject=actor_subject,
        yandex_id=actor.yandex_id,
        login=actor.login,
        email=actor.email,
        access_token=yandex_token,
        token_type=str(token_payload.get("token_type") or "OAuth"),
        scopes=[
            scope
            for scope in str(
                token_payload.get("scope") or yandex_oauth_config(provider)["scopes"]
            ).split(" ")
            if scope
        ],
        metadata=metadata,
        expires_at_epoch=time.time() + int(token_payload["expires_in"])
        if token_payload.get("expires_in")
        else None,
    )


def _save_google_actor_token(
    *,
    actor_subject: str,
    actor: GatewayActor,
    refresh_token: str,
    token_payload: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    save_user_oauth_token(
        provider="google",
        actor_subject=actor_subject,
        yandex_id="",
        login=actor.login,
        email=actor.email,
        access_token=refresh_token,
        token_type="RefreshToken",
        scopes=[
            scope
            for scope in str(
                token_payload.get("scope") or google_oauth_config()["scopes"]
            ).split(" ")
            if scope
        ],
        metadata={**metadata, "credential_type": "google_oauth_refresh_token"},
        expires_at_epoch=None,
    )


def actor_payload(actor: GatewayActor) -> dict[str, Any]:
    payload = asdict(actor)
    payload["groups"] = list(actor.groups)
    payload["scopes"] = list(actor.scopes)
    return payload

import os
import json
from typing import Any

class BackendConfigError(RuntimeError):
    pass


class BackendRouteError(RuntimeError):
    pass


def _env(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise BackendConfigError(f"Missing required environment variable: {name}")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.casefold() in {"1", "true", "yes", "on"}


def _yandex_user_token(provider: str = "yandex") -> str:
    from gateway_mcp.services.auth import current_actor
    from gateway_mcp.services.storage import get_user_oauth_token

    actor = current_actor()
    token = get_user_oauth_token(provider, actor.subject)
    if provider != "yandex" and (not token or not token.get("access_token")):
        token = get_user_oauth_token("yandex", actor.subject)
    if token and token.get("access_token"):
        return str(token["access_token"])

    if _bool_env("GATEWAY_ALLOW_SERVER_YANDEX_TOKENS", False):
        fallback = os.getenv("YANDEX_OAUTH_ACCESS_TOKEN", "") or os.getenv("TRACKER_TOKEN", "") or os.getenv("YANDEX_DISK_TOKEN", "")
        if fallback:
            return fallback

    raise BackendConfigError(
        f"No {provider} OAuth token for current user. Open /credentials and grant the required Yandex scopes."
    )


def _caldav_user_credentials() -> tuple[str, str]:
    from gateway_mcp.services.auth import current_actor
    from gateway_mcp.services.storage import get_user_oauth_token

    actor = current_actor()
    credential = get_user_oauth_token("yandex-caldav", actor.subject)
    if credential and credential.get("access_token"):
        username = str(credential.get("email") or actor.email or actor.login or "")
        if not username:
            raise BackendConfigError("Missing Yandex user email/login for CalDAV")
        return username, str(credential["access_token"])

    if _bool_env("GATEWAY_ALLOW_SERVER_YANDEX_TOKENS", False):
        username = os.getenv("CALDAV_USERNAME") or os.getenv("YANDEX_USERNAME") or ""
        password = os.getenv("CALDAV_PASSWORD") or os.getenv("YANDEX_PASSWORD") or ""
        if username and password:
            return username, password

    raise BackendConfigError(
        "No per-user Yandex Calendar app password is configured. Yandex CalDAV requires an app password, not the regular OAuth token."
    )


def _yandex_user_email() -> str:
    from gateway_mcp.services.auth import current_actor

    actor = current_actor()
    email = actor.email or actor.login
    if not email:
        raise BackendConfigError("Missing Yandex user email/login")
    return email


def _xoauth2_string(username: str, token: str) -> str:
    return f"user={username}\x01auth=Bearer {token}\x01\x01"


def _gitlab_token() -> str:
    from gateway_mcp.services.auth import current_actor
    from gateway_mcp.services.storage import get_user_oauth_token

    actor = current_actor()
    credential = get_user_oauth_token("gitlab", actor.subject)
    if credential and credential.get("access_token"):
        return str(credential["access_token"])

    if _bool_env("GATEWAY_ALLOW_SERVER_GITLAB_TOKEN", False):
        token = os.getenv("GITLAB_TOKEN", "")
        if token:
            return token

    raise BackendConfigError("No GitLab token for current user. Open /credentials and add a personal GitLab access token.")


def _clean_args(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if value is not None and value != ""}


def _apply_argument_aliases(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    body = dict(arguments)
    aliases = route.get("argument_aliases", {})
    for source, target in aliases.items():
        if source in body and target not in body:
            body[target] = body.pop(source)
    return body

def _format_path(path_template: str, arguments: dict[str, Any]) -> str:
    path_args = {key: str(value) for key, value in arguments.items() if value is not None}
    try:
        return path_template.format(**path_args)
    except KeyError as exc:
        raise BackendRouteError(f"Missing path argument: {exc.args[0]}") from exc


def _json_or_text(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        text = response.text
        try:
            return json.loads(text)
        except ValueError:
            return text


def _route_params(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    query_arg_names = set(route.get("query_args", []))
    return {
        key: value
        for key, value in arguments.items()
        if key in query_arg_names and value is not None and value != ""
    }


def _route_body(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    query_arg_names = set(route.get("query_args", []))
    path_arg_names = set(route.get("path_args", []))
    body_arg_name = route.get("body_arg")
    if body_arg_name and isinstance(arguments.get(body_arg_name), dict):
        return dict(arguments[body_arg_name])
    excluded = query_arg_names | path_arg_names
    return {
        key: value
        for key, value in arguments.items()
        if key not in excluded and value is not None and value != ""
    }

import json
import os

READ_ACTIONS = {"read", "audio"}
WRITE_ACTIONS = {"write", "create", "update", "delete", "send", "admin"}

def resource_policy_mode() -> str:
    return os.getenv("GATEWAY_RESOURCE_POLICY_MODE", "permissive").strip().casefold()


def normalize_subject_type(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in {"user", "group"}:
        raise ValueError("subject_type must be user or group")
    return normalized


def normalize_key(value: str) -> str:
    return str(value or "").strip().casefold()


def normalize_system(value: str) -> str:
    return str(value or "").strip().casefold().replace("-", "_")


def normalize_action(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    return normalized or "read"


def parse_actions(actions_json: str) -> list[str]:
    try:
        data = json.loads(actions_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"actions_json must be a JSON array: {exc}") from exc
    if isinstance(data, str):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("actions_json must be a JSON array")
    actions = sorted({normalize_action(item) for item in data if str(item).strip()})
    if not actions:
        raise ValueError("actions_json must contain at least one action")
    return actions


def parse_ttl(ttl_days: int | None) -> int | None:
    if ttl_days is None:
        return None
    value = int(ttl_days)
    if value <= 0:
        return None
    return value


def _normalize_effect(value: str) -> str:
    normalized = str(value or "allow").strip().casefold()
    if normalized not in {"allow", "deny"}:
        raise ValueError("effect must be allow or deny")
    return normalized

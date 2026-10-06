import json

from gateway_mcp.services.auth import current_actor
from gateway_mcp.services.policy import GatewayActor


def actor_for_access_explain(subject_key: str, groups_json: str) -> GatewayActor:
    if not subject_key:
        return current_actor()
    try:
        groups = json.loads(groups_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"groups_json must be a JSON array: {exc}") from exc
    if isinstance(groups, str):
        groups = [groups]
    if not isinstance(groups, list):
        raise ValueError("groups_json must be a JSON array")
    key = str(subject_key).strip()
    return GatewayActor(
        subject=key,
        email=key if "@" in key else "",
        login="" if "@" in key else key,
        groups=tuple(str(group).strip() for group in groups if str(group).strip()),
    )

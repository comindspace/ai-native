from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from gateway_mcp.services.auth import jwt_secret

PrivacyPolicy = Literal["standard", "strict"]


@dataclass(frozen=True)
class PrivacyEntity:
    start: int
    end: int
    entity_type: str
    action: str
    replacement: str


@dataclass
class PrivacySummary:
    detected: int = 0
    pseudonymized: int = 0
    redacted: int = 0
    generalized: int = 0
    entity_types: set[str] = field(default_factory=set)
    by_type: dict[str, dict[str, int]] = field(default_factory=dict)

    def merge(self, other: PrivacySummary) -> None:
        self.detected += other.detected
        self.pseudonymized += other.pseudonymized
        self.redacted += other.redacted
        self.generalized += other.generalized
        self.entity_types.update(other.entity_types)
        for entity_type, actions in other.by_type.items():
            target = self.by_type.setdefault(entity_type, {})
            for action, count in actions.items():
                target[action] = target.get(action, 0) + count

    def as_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "pseudonymized": self.pseudonymized,
            "redacted": self.redacted,
            "generalized": self.generalized,
            "entity_types": sorted(self.entity_types),
            "by_type": {
                entity_type: dict(sorted(actions.items()))
                for entity_type, actions in sorted(self.by_type.items())
            },
        }


@dataclass
class PrivacyResult:
    value: Any
    summary: PrivacySummary
    entities: list[PrivacyEntity] = field(default_factory=list)
    restoration: dict[str, str] = field(default_factory=dict)


_FLAGS = re.IGNORECASE | re.MULTILINE
_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "private_key",
        "redact",
        re.compile(
            r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
            _FLAGS | re.DOTALL,
        ),
    ),
    (
        "credential",
        "redact",
        re.compile(
            r"(?P<prefix>\b(?:password|passwd|pwd|secret|api[_ -]?key|access[_ -]?token|refresh[_ -]?token)\b\s*[:=]\s*)"
            r"(?P<value>[^\s,;\"']{6,})",
            _FLAGS,
        ),
    ),
    (
        "api_key",
        "redact",
        re.compile(
            r"\b(?:sk-(?:or-v1-)?[A-Za-z0-9_-]{20,}|glpat-[A-Za-z0-9_-]{12,}|y0_[A-Za-z0-9_-]{20,}|\d{8,12}:AA[A-Za-z0-9_-]{20,})\b",
            _FLAGS,
        ),
    ),
    (
        "bearer_token",
        "redact",
        re.compile(
            r"(?P<prefix>\bBearer\s+)(?P<value>[A-Za-z0-9._~+/=-]{16,})", _FLAGS
        ),
    ),
    (
        "jwt",
        "redact",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "email",
        "pseudonymize",
        re.compile(
            r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", _FLAGS
        ),
    ),
    (
        "person",
        "pseudonymize",
        re.compile(
            r"(?P<prefix>\b(?:фио|сотрудник|контакт|клиент|ответственный|employee|contact|customer)\s*[:=-]?\s*)"
            r"(?P<value>[А-ЯЁA-Z][а-яёa-z-]+(?:\s+[А-ЯЁA-Z][а-яёa-z-]+){1,2})",
            _FLAGS,
        ),
    ),
    (
        "phone",
        "pseudonymize",
        re.compile(
            r"(?<!\d)(?:\+7|8)[\s(.-]*\d{3}[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"
        ),
    ),
    (
        "snils",
        "pseudonymize",
        re.compile(r"(?<!\d)\d{3}[- ]?\d{3}[- ]?\d{3}[ -]?\d{2}(?!\d)"),
    ),
    (
        "passport",
        "pseudonymize",
        re.compile(
            r"(?P<prefix>\b(?:паспорт|passport)\s*(?:серия)?\s*[:№#-]?\s*)(?P<value>\d{2}\s?\d{2}\s?\d{6})",
            _FLAGS,
        ),
    ),
    (
        "inn",
        "pseudonymize",
        re.compile(
            r"(?P<prefix>\b(?:инн|inn)\s*[:№#-]?\s*)(?P<value>\d{10}|\d{12})\b", _FLAGS
        ),
    ),
    (
        "bank_account",
        "pseudonymize",
        re.compile(
            r"(?P<prefix>\b(?:р[/. ]?с|сч[её]т|account)\s*[:№#-]?\s*)(?P<value>\d{20})\b",
            _FLAGS,
        ),
    ),
    (
        "ip_address",
        "pseudonymize",
        re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
    ),
)

_STRICT_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "financial_value",
        "generalize",
        re.compile(
            r"(?<!\w)(?:\d[\d\s.,]{0,18}\s?(?:₽|руб(?:лей|ля|ль)?|RUB|USD|EUR|\$|€))(?!\w)",
            _FLAGS,
        ),
    ),
    (
        "birth_date",
        "generalize",
        re.compile(
            r"(?P<prefix>\b(?:дата рождения|д[её]н[ь]? рождения|birth date)\s*[:=-]?\s*)"
            r"(?P<value>\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2})",
            _FLAGS,
        ),
    ),
)


def normalize_policy(value: str | None) -> PrivacyPolicy:
    policy = (
        str(value or os.getenv("GATEWAY_PRIVACY_POLICY", "standard")).strip().casefold()
    )
    if policy not in {"standard", "strict"}:
        raise ValueError("privacy policy must be standard or strict")
    return policy  # type: ignore[return-value]


def sanitize_text(
    text: str,
    *,
    actor_subject: str,
    policy: str | None = None,
) -> PrivacyResult:
    source = str(text or "")
    normalized_policy = normalize_policy(policy)
    if _looks_like_binary_payload(source):
        entity = PrivacyEntity(
            start=0,
            end=len(source),
            entity_type="binary_payload",
            action="redact",
            replacement="[GW_BINARY_OMITTED]",
        )
        return PrivacyResult(
            value=entity.replacement,
            summary=PrivacySummary(
                detected=1,
                redacted=1,
                entity_types={entity.entity_type},
                by_type={entity.entity_type: {entity.action: 1}},
            ),
            entities=[entity],
        )
    matches = _detect(source, policy=normalized_policy, actor_subject=actor_subject)
    summary = PrivacySummary()
    restoration: dict[str, str] = {}
    output = source
    for entity in reversed(matches):
        original = source[entity.start : entity.end]
        output = f"{output[: entity.start]}{entity.replacement}{output[entity.end :]}"
        summary.detected += 1
        summary.entity_types.add(entity.entity_type)
        action_counts = summary.by_type.setdefault(entity.entity_type, {})
        action_counts[entity.action] = action_counts.get(entity.action, 0) + 1
        if entity.action == "pseudonymize":
            summary.pseudonymized += 1
            restoration[entity.replacement] = original
        elif entity.action == "generalize":
            summary.generalized += 1
        else:
            summary.redacted += 1
    return PrivacyResult(
        value=output,
        summary=summary,
        entities=matches,
        restoration=restoration,
    )


def sanitize_value(
    value: Any,
    *,
    actor_subject: str,
    policy: str | None = None,
) -> PrivacyResult:
    summary = PrivacySummary()
    restoration: dict[str, str] = {}

    def visit(current: Any) -> Any:
        if isinstance(current, str):
            result = sanitize_text(
                current,
                actor_subject=actor_subject,
                policy=policy,
            )
            summary.merge(result.summary)
            restoration.update(result.restoration)
            return result.value
        if isinstance(current, list):
            return [visit(item) for item in current]
        if isinstance(current, tuple):
            return [visit(item) for item in current]
        if isinstance(current, dict):
            return {str(key): visit(item) for key, item in current.items()}
        return current

    return PrivacyResult(value=visit(value), summary=summary, restoration=restoration)


def sanitize_llm_request(
    payload: dict[str, Any],
    *,
    actor_subject: str,
    policy: str | None = None,
) -> PrivacyResult:
    protected = json.loads(json.dumps(payload, ensure_ascii=False))
    _validate_text_only_llm_payload(protected)
    summary = PrivacySummary()
    restoration: dict[str, str] = {}

    def protect(container: dict[str, Any] | list[Any], key: str | int) -> None:
        value = container[key]
        result = sanitize_value(value, actor_subject=actor_subject, policy=policy)
        container[key] = result.value
        summary.merge(result.summary)
        restoration.update(result.restoration)

    def protect_tool_value(value: Any, *, key: str = "") -> Any:
        if isinstance(value, str):
            if key in {"name", "type"}:
                return value
            result = sanitize_text(
                value,
                actor_subject=actor_subject,
                policy=policy,
            )
            summary.merge(result.summary)
            restoration.update(result.restoration)
            return result.value
        if isinstance(value, list):
            return [protect_tool_value(item) for item in value]
        if isinstance(value, dict):
            return {
                item_key: protect_tool_value(item, key=str(item_key))
                for item_key, item in value.items()
            }
        return value

    if isinstance(protected.get("instructions"), str):
        protect(protected, "instructions")
    if "input" in protected:
        protect(protected, "input")
    if "metadata" in protected:
        protect(protected, "metadata")
    prompt = protected.get("prompt")
    if isinstance(prompt, dict) and "variables" in prompt:
        protect(prompt, "variables")
    messages = protected.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            for key in ("content", "name", "tool_calls", "function_call"):
                if key in message:
                    protect(message, key)
    if isinstance(protected.get("tools"), list):
        protected["tools"] = protect_tool_value(protected["tools"])
    return PrivacyResult(
        value=protected,
        summary=summary,
        restoration=restoration,
    )


def protect_llm_response(
    value: Any,
    *,
    actor_subject: str,
    restoration: dict[str, str],
    policy: str | None = None,
) -> PrivacyResult:
    result = sanitize_value(value, actor_subject=actor_subject, policy=policy)
    result.value = restore_value(result.value, restoration=restoration)
    return result


def restore_value(value: Any, *, restoration: dict[str, str]) -> Any:
    if isinstance(value, str):
        output = value
        for token, original in restoration.items():
            output = output.replace(token, original)
        return output
    if isinstance(value, list):
        return [restore_value(item, restoration=restoration) for item in value]
    if isinstance(value, dict):
        return {
            key: restore_value(item, restoration=restoration)
            for key, item in value.items()
        }
    return value


def public_entities(entities: list[PrivacyEntity]) -> list[dict[str, Any]]:
    return [
        {
            "start": entity.start,
            "end": entity.end,
            "entity_type": entity.entity_type,
            "action": entity.action,
        }
        for entity in entities
    ]


def _detect(
    text: str,
    *,
    policy: PrivacyPolicy,
    actor_subject: str,
) -> list[PrivacyEntity]:
    candidates: list[PrivacyEntity] = []
    patterns = _PATTERNS + (_STRICT_PATTERNS if policy == "strict" else ())
    for entity_type, action, pattern in patterns:
        for match in pattern.finditer(text):
            start, end = (
                match.span("value") if "value" in match.groupdict() else match.span()
            )
            value = text[start:end]
            if entity_type == "ip_address" and not _valid_ipv4(value):
                continue
            candidates.append(
                PrivacyEntity(
                    start=start,
                    end=end,
                    entity_type=entity_type,
                    action=action,
                    replacement=_replacement(
                        actor_subject=actor_subject,
                        entity_type=entity_type,
                        action=action,
                        value=value,
                    ),
                )
            )
    for entity_type, values in _custom_terms().items():
        for value in values:
            for match in re.finditer(re.escape(value), text, _FLAGS):
                candidates.append(
                    PrivacyEntity(
                        start=match.start(),
                        end=match.end(),
                        entity_type=entity_type,
                        action="pseudonymize",
                        replacement=_replacement(
                            actor_subject=actor_subject,
                            entity_type=entity_type,
                            action="pseudonymize",
                            value=match.group(0),
                        ),
                    )
                )
    return _without_overlaps(candidates)


def _without_overlaps(candidates: list[PrivacyEntity]) -> list[PrivacyEntity]:
    priority = {"redact": 0, "pseudonymize": 1, "generalize": 2}
    ordered = sorted(
        candidates,
        key=lambda item: (priority[item.action], -(item.end - item.start), item.start),
    )
    selected: list[PrivacyEntity] = []
    for candidate in ordered:
        if any(
            candidate.start < current.end and current.start < candidate.end
            for current in selected
        ):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: item.start)


def _replacement(
    *, actor_subject: str, entity_type: str, action: str, value: str
) -> str:
    label = re.sub(r"[^A-Z0-9]+", "_", entity_type.upper()).strip("_")
    if action == "redact":
        return f"[GW_{label}_REDACTED]"
    if action == "generalize":
        return f"[GW_{label}]"
    digest = (
        hmac.new(
            _hmac_secret(),
            f"{actor_subject}\0{entity_type}\0{value.casefold().strip()}".encode(),
            hashlib.sha256,
        )
        .hexdigest()[:12]
        .upper()
    )
    return f"[[GW_{label}_{digest}]]"


def _hmac_secret() -> bytes:
    value = os.getenv("GATEWAY_PRIVACY_HMAC_SECRET", "").strip() or jwt_secret()
    return value.encode("utf-8")


def _custom_terms() -> dict[str, list[str]]:
    path_value = os.getenv("GATEWAY_PRIVACY_TERMS_FILE", "").strip()
    if not path_value:
        return {}
    path = Path(path_value).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, list[str]] = {}
    for raw_type, raw_values in payload.items():
        entity_type = re.sub(r"[^a-z0-9_]+", "_", str(raw_type).casefold()).strip("_")
        if not entity_type or not isinstance(raw_values, list):
            continue
        values = [
            str(value).strip() for value in raw_values if len(str(value).strip()) >= 3
        ]
        if values:
            result[entity_type] = values[:1000]
    return result


def _valid_ipv4(value: str) -> bool:
    try:
        return all(0 <= int(part) <= 255 for part in value.split("."))
    except ValueError:
        return False


def _looks_like_binary_payload(value: str) -> bool:
    stripped = value.strip()
    if re.match(r"^data:[^;,]+;base64,", stripped, re.IGNORECASE):
        return True
    if len(stripped) < 4096 or len(stripped) % 4:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", stripped))


def _validate_text_only_llm_payload(payload: dict[str, Any]) -> None:
    if payload.get("background") is True:
        raise ValueError(
            "background model requests are not allowed by the privacy proxy"
        )
    if payload.get("previous_response_id") or payload.get("conversation"):
        raise ValueError(
            "provider-side conversation state is not allowed by the privacy proxy"
        )

    unsupported = {
        "audio",
        "file",
        "image",
        "image_url",
        "input_audio",
        "input_file",
        "input_image",
    }
    hosted_tools = {
        "code_interpreter",
        "computer",
        "computer_use",
        "file_search",
        "image_generation",
        "local_shell",
        "mcp",
        "web_search",
        "web_search_preview",
    }

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        block_type = str(value.get("type") or "").strip().casefold()
        if block_type in unsupported:
            raise ValueError(
                f"{block_type} content is not supported by the text privacy proxy"
            )
        for item in value.values():
            visit(item)

    visit(payload.get("input"))
    visit(payload.get("messages"))
    tools = payload.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            tool_type = str(tool.get("type") or "").strip().casefold()
            if tool_type in hosted_tools:
                raise ValueError(
                    f"provider-hosted tool {tool_type} is not allowed by the privacy proxy"
                )

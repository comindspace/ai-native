"""Bounded JSON context responses for LLM-facing Gateway tools."""

from __future__ import annotations

import json
from typing import Any


DEFAULT_CONTEXT_MAX_CHARS = 12_000
MIN_CONTEXT_MAX_CHARS = 2_000
MAX_CONTEXT_MAX_CHARS = 32_000


def normalize_context_max_chars(value: int) -> int:
    return max(MIN_CONTEXT_MAX_CHARS, min(int(value), MAX_CONTEXT_MAX_CHARS))


def fit_context_payload(payload: dict[str, Any], max_chars: int = DEFAULT_CONTEXT_MAX_CHARS) -> dict[str, Any]:
    """Compact nested backend payloads while preserving valid JSON and top-level shape."""

    budget = normalize_context_max_chars(max_chars)
    original_chars = _json_chars(payload)
    profiles = (
        (6, 10, 1_200, 30),
        (5, 6, 700, 20),
        (4, 4, 400, 14),
        (3, 3, 220, 10),
        (2, 2, 120, 8),
    )

    for max_depth, max_items, max_string_chars, max_dict_items in profiles:
        compacted = _compact_value(
            payload,
            depth=0,
            max_depth=max_depth,
            max_items=max_items,
            max_string_chars=max_string_chars,
            max_dict_items=max_dict_items,
        )
        assert isinstance(compacted, dict)
        result = _with_budget_metadata(compacted, budget, original_chars)
        if _json_chars(result) <= budget:
            return result

    fallback = {
        "ok": bool(payload.get("ok", True)),
        "summary": "Context response exceeded the configured budget. Use a narrower typed query or explicit get call.",
    }
    return _with_budget_metadata(fallback, budget, original_chars, forced_truncated=True)


def compact_reference(value: Any) -> Any:
    """Keep source identity while dropping eagerly loaded backend data."""

    if not isinstance(value, dict):
        return value
    keys = ("provider", "mode", "document_id", "domain", "title", "query", "env_id", "uri")
    return {key: value[key] for key in keys if value.get(key) not in (None, "")}


def _compact_value(
    value: Any,
    *,
    depth: int,
    max_depth: int,
    max_items: int,
    max_string_chars: int,
    max_dict_items: int,
) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        return value[: max(1, max_string_chars - 18)] + "... [truncated]"
    if depth >= max_depth:
        if isinstance(value, list):
            return {"_truncated": True, "item_count": len(value)}
        if isinstance(value, dict):
            return {"_truncated": True, "field_count": len(value)}
        return str(value)[:max_string_chars]
    if isinstance(value, list):
        items = [
            _compact_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_string_chars=max_string_chars,
                max_dict_items=max_dict_items,
            )
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            items.append({"_truncated": True, "omitted_items": len(value) - max_items})
        return items
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        entries = list(value.items())
        for key, item in entries[:max_dict_items]:
            result[str(key)] = _compact_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_string_chars=max_string_chars,
                max_dict_items=max_dict_items,
            )
        if len(entries) > max_dict_items:
            result["_truncated_fields"] = len(entries) - max_dict_items
        return result
    return str(value)[:max_string_chars]


def _with_budget_metadata(
    payload: dict[str, Any],
    budget: int,
    original_chars: int,
    *,
    forced_truncated: bool = False,
) -> dict[str, Any]:
    result = dict(payload)
    compacted_chars = _json_chars(result)
    result["context_budget"] = {
        "max_chars": budget,
        "original_chars": original_chars,
        "compacted_chars": compacted_chars,
        "estimated_tokens": (compacted_chars + 3) // 4,
        "truncated": forced_truncated or compacted_chars < original_chars,
    }
    return result


def _json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))

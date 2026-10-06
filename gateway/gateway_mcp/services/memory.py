import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from gateway_mcp.backends import call_backend
from gateway_mcp.config import root
from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.services.storage import delete_memory_entry, insert_memory_entry, search_memory_entries


TIER_ALIASES = {
    "short": "short",
    "short_term": "short",
    "session": "short",
    "task": "short",
    "medium": "medium",
    "medium_term": "medium",
    "project": "medium",
    "team": "medium",
}
SCOPES = {"user", "team", "project", "company"}
SENSITIVITY = {"public", "internal", "restricted", "secret"}
SOURCE_SUFFIXES = {".md", ".mdx", ".txt", ".json", ".yaml", ".yml"}
MARKDOWN_SUFFIXES = {".md", ".mdx"}


def normalize_tier(value: str) -> str:
    tier = TIER_ALIASES.get(value.strip().casefold())
    if not tier:
        raise ValueError("tier must be short or medium")
    return tier


def parse_tiers(raw: str) -> list[str]:
    if not raw.strip():
        return ["short", "medium"]
    parsed = json.loads(raw)
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError("tiers_json must be a JSON array")
    tiers: list[str] = []
    for item in parsed:
        tier = normalize_tier(str(item))
        if tier not in tiers:
            tiers.append(tier)
    return tiers


def parse_tags(raw: str) -> list[str]:
    if not raw.strip():
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("tags_json must be a JSON array")
    return [str(item).strip() for item in parsed if str(item).strip()]


def parse_metadata(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("metadata_json must be a JSON object")
    return parsed


def validate_scope(scope: str) -> str:
    value = scope.strip().casefold() or "user"
    if value not in SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(sorted(SCOPES))}")
    return value


def validate_sensitivity(sensitivity: str) -> str:
    value = sensitivity.strip().casefold() or "internal"
    if value not in SENSITIVITY:
        raise ValueError(f"sensitivity must be one of: {', '.join(sorted(SENSITIVITY))}")
    return value


def default_ttl_days(tier: str) -> int:
    env_name = "GATEWAY_MEMORY_SHORT_TTL_DAYS" if tier == "short" else "GATEWAY_MEMORY_MEDIUM_TTL_DAYS"
    default = "7" if tier == "short" else "90"
    return int(os.getenv(env_name, default))


def normalize_ttl(tier: str, ttl_days: int | None) -> int:
    value = ttl_days if ttl_days and ttl_days > 0 else default_ttl_days(tier)
    max_days = int(os.getenv("GATEWAY_MEMORY_MAX_TTL_DAYS", "365"))
    return max(1, min(value, max_days))


def resolve_subject(actor: GatewayActor, scope: str, subject: str) -> str:
    value = subject.strip()
    if value:
        if scope == "user" and value != actor.subject and not has_scope(actor, "memory:admin"):
            raise PermissionError("user-scoped memory can only target the current actor")
        return value
    if scope == "user":
        return actor.subject
    raise ValueError(f"subject is required for {scope}-scoped memory")


def compact_session_notes(text: str, max_chars: int = 4000) -> str:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 17].rstrip() + "\n[truncated]"


def write_memory(
    *,
    actor: GatewayActor,
    tier: str,
    scope: str,
    subject: str,
    kind: str,
    content: str,
    source_type: str,
    source_uri: str,
    source_title: str,
    sensitivity: str,
    confidence: float,
    tags_json: str,
    metadata_json: str,
    ttl_days: int | None,
) -> dict[str, Any]:
    normalized_tier = normalize_tier(tier)
    normalized_scope = validate_scope(scope)
    normalized_subject = resolve_subject(actor, normalized_scope, subject)
    normalized_sensitivity = validate_sensitivity(sensitivity)
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("content is required")
    if normalized_sensitivity == "secret" and not has_scope(actor, "memory:admin"):
        raise PermissionError("secret memory writes require memory:admin")

    return insert_memory_entry(
        tier=normalized_tier,
        scope=normalized_scope,
        subject=normalized_subject,
        kind=kind.strip() or "fact",
        content=normalized_content,
        source_type=source_type.strip() or "manual",
        source_uri=source_uri.strip(),
        source_title=source_title.strip(),
        sensitivity=normalized_sensitivity,
        confidence=max(0.0, min(float(confidence), 1.0)),
        tags=parse_tags(tags_json),
        metadata=parse_metadata(metadata_json),
        created_by=actor.subject,
        ttl_days=normalize_ttl(normalized_tier, ttl_days),
    )


def search_memory(
    *,
    actor: GatewayActor,
    query: str,
    tiers_json: str,
    scope: str,
    subject: str,
    limit: int,
) -> list[dict[str, Any]]:
    normalized_scope = validate_scope(scope) if scope.strip() else ""
    normalized_subject = subject.strip()
    if normalized_scope == "user":
        normalized_subject = resolve_subject(actor, normalized_scope, normalized_subject)
    elif normalized_subject and normalized_scope == "":
        raise ValueError("scope is required when subject is provided")
    return search_memory_entries(
        query=query.strip(),
        tiers=parse_tiers(tiers_json),
        scope=normalized_scope,
        subject=normalized_subject,
        actor_subject=actor.subject,
        is_admin=has_scope(actor, "memory:admin"),
        limit=max(1, min(int(limit), 50)),
    )


def forget_memory(entry_id: int, actor: GatewayActor) -> dict[str, Any] | None:
    return delete_memory_entry(
        int(entry_id),
        actor_subject=actor.subject,
        is_admin=has_scope(actor, "memory:admin"),
    )


def configured_source_roots() -> list[Path]:
    raw = os.getenv("GATEWAY_MEMORY_SOURCE_DIRS", "docs;templates;adr;ADRs")
    roots: list[Path] = []
    base = root()
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        path = Path(item)
        if not path.is_absolute():
            path = (base / path).resolve()
        if path.exists() and path.is_dir():
            roots.append(path)
    return roots


def search_local_sources(query: str, limit: int) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    results: list[dict[str, Any]] = []
    for root in configured_source_roots():
        for path in sorted(root.rglob("*")):
            if len(results) >= limit:
                return results
            if not path.is_file() or path.suffix.casefold() not in SOURCE_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            haystack = f"{path.name}\n{text}".casefold()
            if needle and needle not in haystack:
                continue
            results.append(
                {
                    "provider": "local",
                    "source_type": "file",
                    "uri": str(path),
                    "title": path.name,
                    "snippet": _snippet(text, needle),
                }
            )
    return results


def obsidian_enabled() -> bool:
    raw = os.getenv("GATEWAY_OBSIDIAN_ENABLED")
    if raw is None:
        return bool(os.getenv("GATEWAY_OBSIDIAN_VAULT_PATH") or os.getenv("GATEWAY_OBSIDIAN_VAULT_DIRS"))
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def configured_obsidian_roots() -> list[Path]:
    if not obsidian_enabled():
        return []
    raw_items = []
    single = os.getenv("GATEWAY_OBSIDIAN_VAULT_PATH", "").strip()
    if single:
        raw_items.append(single)
    raw_items.extend(item.strip() for item in os.getenv("GATEWAY_OBSIDIAN_VAULT_DIRS", "").split(";") if item.strip())

    roots: list[Path] = []
    base = root()
    for item in raw_items:
        path = Path(item)
        if not path.is_absolute():
            path = (base / path).resolve()
        if path.exists() and path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def search_obsidian_sources(query: str, limit: int, actor: GatewayActor | None = None) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    results: list[dict[str, Any]] = []
    for vault_root in configured_obsidian_roots():
        for path in sorted(vault_root.rglob("*")):
            if len(results) >= limit:
                return results
            if not path.is_file() or path.suffix.casefold() not in MARKDOWN_SUFFIXES:
                continue
            try:
                raw_text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            metadata, body = _split_markdown_frontmatter(raw_text)
            title = str(metadata.get("title") or _markdown_title(body) or path.stem)
            tags = _as_list(metadata.get("tags"))
            haystack = f"{path.name}\n{title}\n{' '.join(tags)}\n{body}".casefold()
            if needle and needle not in haystack:
                continue
            sensitivity = validate_sensitivity(str(metadata.get("sensitivity") or "internal"))
            if not _source_visible_to_actor(sensitivity, actor):
                continue
            relative_path = path.relative_to(vault_root).as_posix()
            results.append(
                {
                    "provider": "obsidian",
                    "source_type": "obsidian_note",
                    "uri": _obsidian_uri(relative_path),
                    "title": title,
                    "snippet": _snippet(body, needle),
                    "metadata": {
                        "vault": os.getenv("GATEWAY_OBSIDIAN_VAULT_NAME", "company-knowledge-vault"),
                        "path": relative_path,
                        "scope": str(metadata.get("scope") or "company"),
                        "sensitivity": sensitivity,
                        "owners": _as_list(metadata.get("owners")),
                        "tags": tags,
                        "source_status": str(metadata.get("source_status") or "editorial"),
                    },
                }
            )
    return results


async def search_source_backed_memory(
    *,
    query: str,
    limit: int,
    tools_registry: dict[str, Any],
    include_yonote: bool,
    actor: GatewayActor | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 25))
    results = search_local_sources(query, limit)
    if len(results) < limit:
        results.extend(search_obsidian_sources(query, limit - len(results), actor))
    if actor and len(results) < limit:
        try:
            from gateway_mcp.services.knowledge import search_as_sources

            results.extend(search_as_sources(actor=actor, query=query, limit=limit - len(results)))
        except Exception:
            pass
    if include_yonote and len(results) < limit:
        route = next(
            (item for item in tools_registry.get("tools", []) if item.get("name") == "yonote.documents.search"),
            None,
        )
        if route:
            try:
                response = await call_backend(route, {"query": query, "limit": limit - len(results)})
                results.append(
                    {
                        "provider": "yonote",
                        "source_type": "yonote",
                        "uri": "yonote.documents.search",
                        "title": "Yonote search results",
                        "data": response,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "provider": "yonote",
                        "source_type": "yonote",
                        "uri": "yonote.documents.search",
                        "title": "Yonote search failed",
                        "error": exc.__class__.__name__,
                    }
                )
    return results[:limit]


def _split_markdown_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    closing_index = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if closing_index is None:
        return {}, text
    return _parse_simple_frontmatter(lines[1:closing_index]), "\n".join(lines[closing_index + 1 :]).strip()


def _parse_simple_frontmatter(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_key = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            metadata.setdefault(current_key, []).append(stripped[2:].strip().strip('"\''))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        cleaned = value.strip()
        if not cleaned:
            metadata[current_key] = []
        elif cleaned.startswith("[") and cleaned.endswith("]"):
            metadata[current_key] = [item.strip().strip('"\'') for item in cleaned[1:-1].split(",") if item.strip()]
        else:
            metadata[current_key] = cleaned.strip('"\'')
    return metadata


def _markdown_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _source_visible_to_actor(sensitivity: str, actor: GatewayActor | None) -> bool:
    if sensitivity in {"public", "internal"}:
        return True
    return bool(actor and has_scope(actor, "memory:admin"))


def _obsidian_uri(relative_path: str) -> str:
    base_url = os.getenv("GATEWAY_OBSIDIAN_BASE_URL", "").rstrip("/")
    if base_url:
        return f"{base_url}/{quote(relative_path)}"
    vault = quote(os.getenv("GATEWAY_OBSIDIAN_VAULT_NAME", "company-knowledge-vault"))
    return f"obsidian://open?vault={vault}&file={quote(relative_path)}"


def _snippet(text: str, needle: str, size: int = 500) -> str:
    if not text:
        return ""
    if not needle:
        return text[:size].strip()
    index = text.casefold().find(needle)
    if index == -1:
        return text[:size].strip()
    start = max(0, index - size // 3)
    return text[start : start + size].strip()

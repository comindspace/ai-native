import json
import os
from pathlib import Path
from typing import Any

from gateway_mcp.backends import call_backend
from gateway_mcp.config import resolve_configured_path
from gateway_mcp.services.company_common import (
    SOURCE_OF_TRUTH_ITEMS,
    company_yonote_index_id,
    company_yonote_index_query,
    _domains_for_kind,
    _missing_yonote_route,
    _normalized_kind,
    _remote_error,
    _route_by_name,
)

async def source_of_truth(tools_registry: dict[str, Any]) -> dict[str, Any]:
    indexes = await load_company_yonote_indexes(tools_registry)
    return {
        "items": _source_of_truth_items_with_index_refs(),
        "canonical_index": await load_company_yonote_index(tools_registry),
        "indexes": indexes,
    }


async def load_company_yonote_index(tools_registry: dict[str, Any]) -> dict[str, Any]:
    document_id = company_yonote_index_id()
    if document_id:
        route = _route_by_name(tools_registry, "yonote.documents.get")
        if route is None:
            return _missing_yonote_route("yonote.documents.get")
        try:
            data = await call_backend(route, {"document_id": document_id})
            return {
                "provider": "yonote",
                "mode": "document_id",
                "document_id": document_id,
                "data": data,
            }
        except Exception as exc:
            return _remote_error("yonote", "yonote.documents.get", exc)

    query = company_yonote_index_query()
    route = _route_by_name(tools_registry, "yonote.documents.search")
    if route is None:
        return _missing_yonote_route("yonote.documents.search")
    try:
        data = await call_backend(route, {"query": query, "limit": 5})
        return {
            "provider": "yonote",
            "mode": "search",
            "query": query,
            "data": data,
        }
    except Exception as exc:
        return _remote_error("yonote", "yonote.documents.search", exc)


async def load_company_yonote_indexes(
    tools_registry: dict[str, Any],
    kind: str = "",
) -> list[dict[str, Any]]:
    domains = _domains_for_kind(_normalized_kind(kind))
    registry = _company_index_registry()
    indexes = [item for item in registry if not domains or item["domain"] in domains]
    results = []
    for index in indexes:
        results.append(await _load_one_yonote_index(tools_registry, index))
    return results


def _company_indexes_file() -> Path:
    return resolve_configured_path("GATEWAY_COMPANY_INDEXES_FILE", "gateway-company-indexes.json")


def _company_index_registry() -> list[dict[str, Any]]:
    path = _company_indexes_file()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    indexes = data.get("indexes", []) if isinstance(data, dict) else []
    normalized = []
    for item in indexes:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").strip()
        if not domain:
            continue
        env_id = str(item.get("env_id") or "").strip()
        configured_id = os.getenv(env_id, "").strip() if env_id else ""
        configured_id = configured_id or str(item.get("document_id") or "").strip()
        normalized.append(
            {
                "domain": domain,
                "title": str(item.get("title") or domain).strip(),
                "query": str(item.get("query") or domain).strip(),
                "env_id": env_id,
                "document_id": configured_id,
                "sources": item.get("sources") if isinstance(item.get("sources"), list) else [],
            }
        )
    return normalized


def _source_of_truth_items_with_index_refs() -> list[dict[str, Any]]:
    index_by_domain = {item["domain"]: item for item in _company_index_registry()}
    result = []
    for item in SOURCE_OF_TRUTH_ITEMS:
        enriched = dict(item)
        index = index_by_domain.get(item["domain"])
        if index:
            enriched["yonote_index"] = {
                "title": index["title"],
                "query": index["query"],
                "env_id": index["env_id"],
                "document_id_configured": bool(index["document_id"]),
            }
        result.append(enriched)
    return result


def _source_domains_for_kind(kind: str) -> list[dict[str, Any]]:
    if not kind:
        return _source_of_truth_items_with_index_refs()
    domains = _domains_for_kind(kind)
    items = _source_of_truth_items_with_index_refs()
    return [item for item in items if item["domain"] in domains] if domains else items


def _index_refs_for_kind(kind: str) -> list[dict[str, Any]]:
    domains = _domains_for_kind(kind)
    refs = []
    for index in _company_index_registry():
        if domains and index["domain"] not in domains:
            continue
        refs.append(
            {
                "domain": index["domain"],
                "title": index["title"],
                "query": index["query"],
                "document_id": index["document_id"] or None,
                "env_id": index["env_id"],
            }
        )
    return refs


async def _load_one_yonote_index(tools_registry: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    document_id = str(index.get("document_id") or "").strip()
    if document_id:
        route = _route_by_name(tools_registry, "yonote.documents.get")
        if route is None:
            return _missing_yonote_route("yonote.documents.get")
        try:
            data = await call_backend(route, {"document_id": document_id})
            return {
                "kind": "company_context_index",
                "provider": "yonote",
                "domain": index["domain"],
                "title": index["title"],
                "mode": "document_id",
                "document_id": document_id,
                "sources": index["sources"],
                "data": data,
            }
        except Exception as exc:
            return _remote_error("yonote", "yonote.documents.get", exc)

    route = _route_by_name(tools_registry, "yonote.documents.search")
    if route is None:
        return _missing_yonote_route("yonote.documents.search")
    try:
        data = await call_backend(route, {"query": index["query"], "limit": 5})
        return {
            "kind": "company_context_index",
            "provider": "yonote",
            "domain": index["domain"],
            "title": index["title"],
            "mode": "search",
            "query": index["query"],
            "sources": index["sources"],
            "data": data,
        }
    except Exception as exc:
        return _remote_error("yonote", "yonote.documents.search", exc)

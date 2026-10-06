from typing import Any

from gateway_mcp.backends import call_backend
from gateway_mcp.services.company_common import (
    company_yonote_index_id,
    company_yonote_index_query,
    _domains_for_kind,
    _missing_yonote_route,
    _normalized_kind,
    _remote_error,
    _route_by_name,
    _typed_query,
)
from gateway_mcp.services.company_indexes import (
    _index_refs_for_kind,
    _source_domains_for_kind,
    load_company_yonote_index,
    load_company_yonote_indexes,
)

async def search_company_index(
    query: str,
    kind: str,
    limit: int,
    tools_registry: dict[str, Any],
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 25))
    search_query = _typed_query(query, kind)
    if not search_query:
        indexes = await load_company_yonote_indexes(tools_registry, kind)
        return indexes or [
            {
                "kind": "company_context_index",
                "source": "yonote",
                "query": company_yonote_index_query(),
                "document_id": company_yonote_index_id() or None,
                "data": await load_company_yonote_index(tools_registry),
            }
        ]

    route = _route_by_name(tools_registry, "yonote.documents.search")
    if route is None:
        return [_missing_yonote_route("yonote.documents.search")]
    try:
        data = await call_backend(route, {"query": search_query, "limit": limit})
        return [
            {
                "kind": _normalized_kind(kind) or "company_context",
                "source": "yonote",
                "query": search_query,
                "source_of_truth": _source_domains_for_kind(_normalized_kind(kind)),
                "indexes": _index_refs_for_kind(_normalized_kind(kind)),
                "data": data,
            }
        ]
    except Exception as exc:
        return [_remote_error("yonote", "yonote.documents.search", exc)]


async def get_company_item(kind: str, item_id: str, tools_registry: dict[str, Any]) -> dict[str, Any] | None:
    normalized = _normalized_kind(kind)
    target = str(item_id or "").strip()
    if not target:
        return None

    if normalized in {"document", "page", "yonote"}:
        route = _route_by_name(tools_registry, "yonote.documents.get")
        if route is None:
            return _missing_yonote_route("yonote.documents.get")
        try:
            data = await call_backend(route, {"document_id": target})
            return {"kind": normalized, "source": "yonote", "id": target, "data": data}
        except Exception as exc:
            return _remote_error("yonote", "yonote.documents.get", exc)

    matches = await search_company_index(target, kind, 5, tools_registry)
    return {
        "kind": normalized or "company_context",
        "id": target,
        "source": "yonote",
        "matches": matches,
        "source_of_truth": _source_domains_for_kind(normalized),
    }


async def search_company_sources(
    *,
    query: str,
    limit: int,
    tools_registry: dict[str, Any],
    include_remote: bool,
) -> list[dict[str, Any]]:
    if not include_remote:
        return []
    return await _search_remote_sources(query, max(1, min(int(limit), 25)), tools_registry)


async def _search_remote_sources(query: str, limit: int, tools_registry: dict[str, Any]) -> list[dict[str, Any]]:
    query = str(query or "").strip()
    if not query:
        return await load_company_yonote_indexes(tools_registry)

    remote_specs = [
        ("yonote.documents.search", {"query": query, "limit": limit}, "yonote"),
        ("tracker.issues.search", {"body": {"query": query}, "perPage": limit}, "tracker"),
        ("bitrix24.leads.list", {"params": {"filter": {"%TITLE": query}, "select": ["ID", "TITLE"], "start": 0}}, "bitrix24"),
        ("gitlab.projects.search", {"search": query, "membership": True, "simple": True, "per_page": limit}, "gitlab"),
    ]
    results: list[dict[str, Any]] = []
    for route_name, args, provider in remote_specs:
        route = _route_by_name(tools_registry, route_name)
        if route is None:
            continue
        try:
            data = await call_backend(route, args)
            results.append(
                {
                    "provider": provider,
                    "source_type": "remote",
                    "uri": route_name,
                    "title": route_name,
                    "data": data,
                }
            )
        except Exception as exc:
            results.append(_remote_error(provider, route_name, exc))
        if len(results) >= limit:
            break
    return results

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gateway_mcp.config import root
from gateway_mcp.services.policy import GatewayActor, has_scope

MARKDOWN_SUFFIX = ".md"
INGEST_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}
ROLE_LEVELS = {"reader": 1, "writer": 2, "admin": 3}
ROLE_ALIASES = {
    "read": "reader",
    "reader": "reader",
    "viewer": "reader",
    "write": "writer",
    "writer": "writer",
    "editor": "writer",
    "admin": "admin",
    "owner": "admin",
}
SKIP_MARKDOWN_FILES = {"README.md", "index.md"}
HISTORY_DIR = ".gateway-history"
TRASH_DIR = ".gateway-trash"


def vault_root() -> Path:
    raw = (
        os.getenv("GATEWAY_KNOWLEDGE_VAULT_PATH", "").strip()
        or os.getenv("GATEWAY_OBSIDIAN_VAULT_PATH", "").strip()
        or "company-knowledge-vault"
    )
    path = Path(raw)
    if not path.is_absolute():
        cwd_path = (Path.cwd() / path).resolve()
        if cwd_path.exists():
            return cwd_path
        path = (root() / path).resolve()
    return path


def create_space(
    *,
    actor: GatewayActor,
    slug: str,
    title: str,
    description: str = "",
    members_json: str = "[]",
) -> dict[str, Any]:
    normalized_slug = _validate_slug(slug)
    normalized_title = title.strip() or normalized_slug
    space_path = _space_path(normalized_slug)
    if space_path.exists():
        raise FileExistsError(f"knowledge space already exists: {normalized_slug}")

    members = _parse_members_json(members_json)
    member_rows = [_member_row(_actor_member_key(actor), "admin")]
    for member in members:
        subject = str(member.get("subject") or "").strip()
        role = _normalize_role(str(member.get("role") or "reader"))
        if subject:
            member_rows.append(_member_row(subject, role))

    space_path.mkdir(parents=True, exist_ok=False)
    _write_members(space_path / "members.yaml", _dedupe_members(member_rows))
    _write_text(
        space_path / "README.md",
        _markdown_with_frontmatter(
            {
                "title": normalized_title,
                "space": f"space:{normalized_slug}",
                "kind": "knowledge_space",
                "owner": actor.subject,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "tags": ["knowledge-space"],
            },
            f"# {normalized_title}\n\n{description.strip()}\n".strip() + "\n",
        ),
    )
    _regenerate_space_index(space_path)
    _regenerate_global_indexes()
    return space_info(actor=actor, space=f"space:{normalized_slug}")


def list_spaces(
    *, actor: GatewayActor, include_personal: bool = True
) -> list[dict[str, Any]]:
    _ensure_vault()
    spaces: list[dict[str, Any]] = []
    if include_personal:
        personal = _ensure_personal_space(actor)
        spaces.append(
            _describe_space(
                actor=actor, space_type="personal", slug=personal.name, path=personal
            )
        )

    spaces_root = vault_root() / "spaces"
    if spaces_root.exists():
        for path in sorted(item for item in spaces_root.iterdir() if item.is_dir()):
            try:
                if _can_access_group(actor, path, "reader"):
                    spaces.append(
                        _describe_space(
                            actor=actor, space_type="space", slug=path.name, path=path
                        )
                    )
            except PermissionError:
                continue
    return spaces


def space_info(*, actor: GatewayActor, space: str = "") -> dict[str, Any]:
    resolved = _resolve_space(actor, space, required_role="reader")
    return _describe_space(
        actor=actor,
        space_type=resolved["type"],
        slug=resolved["slug"],
        path=resolved["path"],
    )


def add_member(
    *, actor: GatewayActor, space: str, subject: str, role: str = "reader"
) -> dict[str, Any]:
    resolved = _resolve_space(actor, space, required_role="admin")
    if resolved["type"] != "space":
        raise PermissionError("personal spaces do not support members")
    member_subject = subject.strip()
    if not member_subject:
        raise ValueError("subject is required")
    members_file = resolved["path"] / "members.yaml"
    members = _dedupe_members(
        _read_members(members_file)
        + [_member_row(member_subject, _normalize_role(role))]
    )
    _write_members(members_file, members)
    _touch_readme(resolved["path"])
    _regenerate_global_indexes()
    return space_info(actor=actor, space=f"space:{resolved['slug']}")


def remove_member(*, actor: GatewayActor, space: str, subject: str) -> dict[str, Any]:
    resolved = _resolve_space(actor, space, required_role="admin")
    if resolved["type"] != "space":
        raise PermissionError("personal spaces do not support members")
    member_subject = _normalize_member_subject(subject)
    if not member_subject:
        raise ValueError("subject is required")
    members_file = resolved["path"] / "members.yaml"
    members = [
        member
        for member in _read_members(members_file)
        if _normalize_member_subject(member["subject"]) != member_subject
    ]
    if not any(
        _normalize_member_subject(member["subject"])
        == _normalize_member_subject(_actor_member_key(actor))
        for member in members
    ):
        members.append(_member_row(_actor_member_key(actor), "admin"))
    _write_members(members_file, _dedupe_members(members))
    _touch_readme(resolved["path"])
    _regenerate_global_indexes()
    return space_info(actor=actor, space=f"space:{resolved['slug']}")


def put_document(
    *,
    actor: GatewayActor,
    space: str,
    title: str,
    content: str,
    kind: str = "note",
    tags_json: str = "[]",
    path: str = "",
    document_id: str = "",
    status: str = "draft",
) -> dict[str, Any]:
    resolved = _resolve_space(actor, space, required_role="writer")
    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("title is required")
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("content is required")
    tags = _parse_tags(tags_json)
    doc_id = _validate_doc_id(
        document_id.strip()
        or f"{datetime.now(timezone.utc).strftime('%Y%m%d')}-{_slugify(normalized_title)}-{uuid.uuid4().hex[:8]}"
    )
    relative = _document_relative_path(kind=kind, path=path, document_id=doc_id)
    doc_path = _safe_child(resolved["path"], relative)
    created_at = _now_iso()
    if doc_path.exists():
        _archive_document_version(
            space_path=resolved["path"],
            doc_path=doc_path,
            actor=actor,
            reason="update",
        )
        existing_meta, _ = _split_markdown_frontmatter(
            doc_path.read_text(encoding="utf-8")
        )
        created_at = str(existing_meta.get("created_at") or created_at)

    doc_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "id": doc_id,
        "title": normalized_title,
        "space": f"{resolved['type']}:{resolved['slug']}",
        "kind": _clean_token(kind, default="note"),
        "status": _clean_token(status, default="draft"),
        "owner": actor.subject,
        "created_at": created_at,
        "updated_at": _now_iso(),
        "tags": tags,
    }
    _write_text(
        doc_path,
        _markdown_with_frontmatter(
            metadata, _ensure_heading(normalized_title, normalized_content)
        ),
    )
    _regenerate_space_index(resolved["path"])
    _regenerate_global_indexes()
    return _document_payload(root_path=resolved["path"], doc_path=doc_path)


def get_document(*, actor: GatewayActor, space: str, document: str) -> dict[str, Any]:
    resolved = _resolve_space(actor, space, required_role="reader")
    doc_path = _find_document(resolved["path"], document)
    if not doc_path:
        raise FileNotFoundError(f"knowledge document not found: {document}")
    return _document_payload(
        root_path=resolved["path"], doc_path=doc_path, include_content=True
    )


def delete_document(
    *, actor: GatewayActor, space: str, document: str
) -> dict[str, Any]:
    resolved = _resolve_space(actor, space, required_role="writer")
    doc_path = _find_document(resolved["path"], document)
    if not doc_path:
        raise FileNotFoundError(f"knowledge document not found: {document}")
    payload = _document_payload(root_path=resolved["path"], doc_path=doc_path)
    version = _archive_document_version(
        space_path=resolved["path"],
        doc_path=doc_path,
        actor=actor,
        reason="delete",
    )
    deleted_at = _now_iso()
    trash_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    trash_root = resolved["path"] / TRASH_DIR
    trash_content = trash_root / f"{trash_id}.md"
    trash_metadata = trash_root / f"{trash_id}.json"
    original_path = doc_path.relative_to(resolved["path"]).as_posix()
    _write_text(trash_content, doc_path.read_text(encoding="utf-8"))
    _write_json(
        trash_metadata,
        {
            "trash_id": trash_id,
            "document_id": payload["id"],
            "document_path": original_path,
            "title": payload["title"],
            "deleted_at": deleted_at,
            "deleted_by": actor.subject,
            "checksum_sha256": version["checksum_sha256"],
        },
    )
    doc_path.unlink()
    _regenerate_space_index(resolved["path"])
    _regenerate_global_indexes()
    payload["trash_id"] = trash_id
    payload["deleted_at"] = deleted_at
    payload["soft_deleted"] = True
    return payload


def list_document_versions(
    *,
    actor: GatewayActor,
    space: str,
    document: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    resolved = _resolve_space(actor, space, required_role="reader")
    document_id, document_path = _resolve_document_identity(resolved["path"], document)
    entries = _history_entries(
        resolved["path"],
        document_id=document_id,
        document_path=document_path,
    )
    return entries[: max(1, min(int(limit), 100))]


def restore_document_version(
    *,
    actor: GatewayActor,
    space: str,
    document: str,
    version_id: str,
) -> dict[str, Any]:
    resolved = _resolve_space(actor, space, required_role="writer")
    document_id, document_path = _resolve_document_identity(resolved["path"], document)
    version = _find_history_entry(
        resolved["path"],
        version_id=version_id,
        document_id=document_id,
        document_path=document_path,
    )
    target = _safe_child(resolved["path"], str(version["document_path"]))
    if target.exists():
        _archive_document_version(
            space_path=resolved["path"],
            doc_path=target,
            actor=actor,
            reason="before_restore",
        )
    content_path = _safe_child(
        resolved["path"] / HISTORY_DIR, str(version["content_path"])
    )
    _write_text(target, content_path.read_text(encoding="utf-8"))
    _regenerate_space_index(resolved["path"])
    _regenerate_global_indexes()
    result = _document_payload(root_path=resolved["path"], doc_path=target)
    result["restored_version"] = version_id
    return result


def list_trash(
    *,
    actor: GatewayActor,
    space: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    resolved = _resolve_space(actor, space, required_role="reader")
    entries = _trash_entries(resolved["path"])
    return entries[: max(1, min(int(limit), 100))]


def restore_trash(
    *,
    actor: GatewayActor,
    space: str,
    trash_id: str,
) -> dict[str, Any]:
    resolved = _resolve_space(actor, space, required_role="writer")
    entry = _find_trash_entry(resolved["path"], trash_id)
    target = _safe_child(resolved["path"], str(entry["document_path"]))
    if target.exists():
        raise FileExistsError(
            f"knowledge document already exists: {entry['document_path']}"
        )
    content_path = _safe_child(resolved["path"] / TRASH_DIR, str(entry["content_path"]))
    _write_text(target, content_path.read_text(encoding="utf-8"))
    content_path.unlink()
    metadata_path = _safe_child(
        resolved["path"] / TRASH_DIR, f"{entry['trash_id']}.json"
    )
    metadata_path.unlink()
    _regenerate_space_index(resolved["path"])
    _regenerate_global_indexes()
    result = _document_payload(root_path=resolved["path"], doc_path=target)
    result["restored_from_trash"] = entry["trash_id"]
    return result


def ingest_file(
    *,
    actor: GatewayActor,
    source_path: str,
    space: str = "",
    title: str = "",
    kind: str = "source",
    tags_json: str = "[]",
    status: str = "source",
) -> dict[str, Any]:
    file_path = _resolve_ingest_source(source_path)
    if file_path.suffix.casefold() not in INGEST_SUFFIXES:
        raise ValueError(f"unsupported ingest file type: {file_path.suffix}")
    max_bytes = int(os.getenv("GATEWAY_KNOWLEDGE_INGEST_MAX_BYTES", "1048576"))
    if file_path.stat().st_size > max_bytes:
        raise ValueError("ingest file is too large")
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("ingest file must be UTF-8 text or markdown") from exc
    document_title = (
        title.strip()
        or file_path.stem.replace("-", " ").replace("_", " ").strip().title()
    )
    return put_document(
        actor=actor,
        space=space,
        title=document_title,
        content=content,
        kind=kind,
        tags_json=tags_json,
        document_id=f"{datetime.now(timezone.utc).strftime('%Y%m%d')}-{_slugify(file_path.stem)}-{uuid.uuid4().hex[:8]}",
        status=status,
    )


def search_documents(
    *,
    actor: GatewayActor,
    query: str = "",
    space: str = "",
    limit: int = 10,
    include_personal: bool = True,
    include_groups: bool = True,
) -> list[dict[str, Any]]:
    _ensure_vault()
    paths: list[dict[str, Any]] = []
    if space.strip():
        paths.append(_resolve_space(actor, space, required_role="reader"))
    else:
        if include_personal:
            personal = _ensure_personal_space(actor)
            paths.append({"type": "personal", "slug": personal.name, "path": personal})
        if include_groups:
            spaces_root = vault_root() / "spaces"
            if spaces_root.exists():
                for path in sorted(
                    item for item in spaces_root.iterdir() if item.is_dir()
                ):
                    if _can_access_group(actor, path, "reader"):
                        paths.append({"type": "space", "slug": path.name, "path": path})

    needle = query.casefold().strip()
    results: list[dict[str, Any]] = []
    for resolved in paths:
        for doc_path in _iter_documents(resolved["path"]):
            raw = doc_path.read_text(encoding="utf-8")
            metadata, body = _split_markdown_frontmatter(raw)
            title = str(metadata.get("title") or _markdown_title(body) or doc_path.stem)
            tags = _as_list(metadata.get("tags"))
            haystack = f"{doc_path.name}\n{title}\n{' '.join(tags)}\n{body}".casefold()
            if needle and needle not in haystack:
                continue
            score = haystack.count(needle) if needle else 1
            payload = _document_payload(root_path=resolved["path"], doc_path=doc_path)
            payload["score"] = score
            payload["snippet"] = _snippet(body, needle)
            results.append(payload)
    results.sort(
        key=lambda item: (
            int(item.get("score") or 0),
            str(item.get("updated_at") or ""),
        ),
        reverse=True,
    )
    return results[: max(1, min(int(limit), 50))]


def search_as_sources(
    *, actor: GatewayActor, query: str = "", limit: int = 10
) -> list[dict[str, Any]]:
    results = []
    for item in search_documents(actor=actor, query=query, limit=limit):
        results.append(
            {
                "provider": "knowledge",
                "source_type": "markdown_knowledge",
                "uri": f"knowledge://{item.get('space')}/{item.get('path')}",
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "metadata": {
                    "space": item.get("space", ""),
                    "path": item.get("path", ""),
                    "kind": item.get("kind", ""),
                    "status": item.get("status", ""),
                    "tags": item.get("tags", []),
                    "updated_at": item.get("updated_at", ""),
                },
            }
        )
    return results


def reindex(*, actor: GatewayActor, space: str = "") -> dict[str, Any]:
    _ensure_vault()
    targets: list[dict[str, Any]]
    if space.strip():
        targets = [_resolve_space(actor, space, required_role="reader")]
    else:
        targets = []
        personal = _ensure_personal_space(actor)
        targets.append({"type": "personal", "slug": personal.name, "path": personal})
        spaces_root = vault_root() / "spaces"
        if spaces_root.exists():
            for path in sorted(item for item in spaces_root.iterdir() if item.is_dir()):
                if _can_access_group(actor, path, "reader"):
                    targets.append({"type": "space", "slug": path.name, "path": path})

    counts = []
    for target in targets:
        counts.append(
            {
                "space": f"{target['type']}:{target['slug']}",
                "documents": _regenerate_space_index(target["path"]),
            }
        )
    _regenerate_global_indexes()
    return {"spaces": counts, "root": str(vault_root())}


def audit_access(*, actor: GatewayActor, space: str = "") -> dict[str, Any]:
    if not space.strip():
        return {
            "actor": _actor_payload(actor),
            "scopes": list(actor.scopes),
            "spaces": list_spaces(actor=actor),
        }
    resolved = _resolve_space(actor, space, required_role="reader")
    role = (
        "admin"
        if resolved["type"] == "personal"
        else _actor_group_role(actor, resolved["path"])
    )
    return {
        "actor": _actor_payload(actor),
        "space": f"{resolved['type']}:{resolved['slug']}",
        "role": role,
        "can_read": _role_allows(role, "reader") or has_scope(actor, "memory:admin"),
        "can_write": _role_allows(role, "writer") or has_scope(actor, "memory:admin"),
        "can_admin": _role_allows(role, "admin") or has_scope(actor, "memory:admin"),
        "members": []
        if resolved["type"] == "personal"
        else _read_members(resolved["path"] / "members.yaml"),
    }


def _ensure_vault() -> Path:
    path = vault_root()
    path.mkdir(parents=True, exist_ok=True)
    (path / "personal").mkdir(exist_ok=True)
    (path / "spaces").mkdir(exist_ok=True)
    (path / "indexes").mkdir(exist_ok=True)
    return path


def _ensure_personal_space(actor: GatewayActor) -> Path:
    _ensure_vault()
    path = vault_root() / "personal" / _personal_slug(actor)
    path.mkdir(parents=True, exist_ok=True)
    profile = path / "profile.yaml"
    if not profile.exists():
        _write_text(
            profile,
            "\n".join(
                [
                    f"subject: {_yaml_scalar(actor.subject)}",
                    f"email: {_yaml_scalar(actor.email)}",
                    f"login: {_yaml_scalar(actor.login)}",
                    f"created_at: {_yaml_scalar(_now_iso())}",
                    "",
                ]
            ),
        )
    readme = path / "README.md"
    if not readme.exists():
        _write_text(
            readme,
            _markdown_with_frontmatter(
                {
                    "title": f"Personal knowledge: {actor.display}",
                    "space": f"personal:{path.name}",
                    "kind": "personal_knowledge_space",
                    "owner": actor.subject,
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                    "tags": ["personal-knowledge"],
                },
                f"# Personal knowledge: {actor.display}\n\nPrivate assistant knowledge space.\n",
            ),
        )
    _regenerate_space_index(path)
    return path


def _resolve_space(
    actor: GatewayActor, space: str, required_role: str
) -> dict[str, Any]:
    _ensure_vault()
    raw = space.strip()
    if not raw or raw == "personal":
        path = _ensure_personal_space(actor)
        return {"type": "personal", "slug": path.name, "path": path}
    if raw.startswith("personal:"):
        slug = _validate_slug(raw.split(":", 1)[1])
        path = vault_root() / "personal" / slug
        if slug != _personal_slug(actor) and not has_scope(actor, "memory:admin"):
            raise PermissionError("personal space is private")
        if not path.exists():
            if slug == _personal_slug(actor):
                path = _ensure_personal_space(actor)
            else:
                raise FileNotFoundError(f"personal knowledge space not found: {slug}")
        return {"type": "personal", "slug": slug, "path": path}

    slug = raw.split(":", 1)[1] if raw.startswith(("space:", "group:")) else raw
    normalized_slug = _validate_slug(slug)
    path = _space_path(normalized_slug)
    if not path.exists():
        raise FileNotFoundError(f"knowledge space not found: {normalized_slug}")
    if not _can_access_group(actor, path, required_role):
        raise PermissionError(
            f"missing {required_role} access for knowledge space: {normalized_slug}"
        )
    return {"type": "space", "slug": normalized_slug, "path": path}


def _space_path(slug: str) -> Path:
    return vault_root() / "spaces" / slug


def _can_access_group(actor: GatewayActor, path: Path, required_role: str) -> bool:
    if has_scope(actor, "memory:admin"):
        return True
    role = _actor_group_role(actor, path)
    return _role_allows(role, required_role)


def _actor_group_role(actor: GatewayActor, path: Path) -> str:
    subjects = {
        _normalize_member_subject(actor.subject),
        _normalize_member_subject(actor.email),
        _normalize_member_subject(actor.login),
        _normalize_member_subject(actor.yandex_id),
    }
    subjects.update(
        _normalize_member_subject(f"group:{group}") for group in actor.groups
    )
    subjects.discard("")
    best = ""
    for member in _read_members(path / "members.yaml"):
        if _normalize_member_subject(member["subject"]) in subjects and ROLE_LEVELS.get(
            member["role"], 0
        ) > ROLE_LEVELS.get(best, 0):
            best = member["role"]
    return best


def _role_allows(actual: str, required: str) -> bool:
    actual_level = ROLE_LEVELS.get(
        ROLE_ALIASES.get(str(actual or "").strip().casefold(), ""), 0
    )
    return actual_level >= ROLE_LEVELS.get(_normalize_role(required), 0)


def _describe_space(
    *, actor: GatewayActor, space_type: str, slug: str, path: Path
) -> dict[str, Any]:
    readme = path / "README.md"
    metadata: dict[str, Any] = {}
    body = ""
    if readme.exists():
        metadata, body = _split_markdown_frontmatter(readme.read_text(encoding="utf-8"))
    title = str(metadata.get("title") or _markdown_title(body) or slug)
    documents = list(_iter_documents(path))
    role = "admin" if space_type == "personal" else _actor_group_role(actor, path)
    return {
        "space": f"{space_type}:{slug}",
        "type": space_type,
        "slug": slug,
        "title": title,
        "description": _first_paragraph(body),
        "role": role or ("admin" if has_scope(actor, "memory:admin") else ""),
        "documents": len(documents),
        "path": path.relative_to(vault_root()).as_posix(),
        "members": []
        if space_type == "personal"
        else _read_members(path / "members.yaml"),
    }


def _regenerate_space_index(space_path: Path) -> int:
    docs = [
        _document_payload(root_path=space_path, doc_path=doc_path)
        for doc_path in _iter_documents(space_path)
    ]
    lines = ["# Index", ""]
    for doc in docs:
        lines.append(f"- [{doc['title']}]({doc['path']}) - {doc.get('kind', 'note')}")
    _write_text(space_path / "index.md", "\n".join(lines).rstrip() + "\n")
    return len(docs)


def _regenerate_global_indexes() -> None:
    path = _ensure_vault()
    spaces = []
    for space_root in (path / "spaces").iterdir():
        if space_root.is_dir():
            readme = space_root / "README.md"
            metadata, body = ({}, "")
            if readme.exists():
                metadata, body = _split_markdown_frontmatter(
                    readme.read_text(encoding="utf-8")
                )
            spaces.append(
                {
                    "space": f"space:{space_root.name}",
                    "title": str(
                        metadata.get("title")
                        or _markdown_title(body)
                        or space_root.name
                    ),
                    "path": space_root.relative_to(path).as_posix(),
                    "documents": len(list(_iter_documents(space_root))),
                }
            )
    _write_json(path / "indexes" / "spaces.json", spaces)

    tags: dict[str, list[str]] = {}
    for doc_path in _iter_documents(path):
        metadata, _ = _split_markdown_frontmatter(doc_path.read_text(encoding="utf-8"))
        for tag in _as_list(metadata.get("tags")):
            tags.setdefault(tag, []).append(doc_path.relative_to(path).as_posix())
    _write_json(
        path / "indexes" / "tags.json",
        {key: sorted(value) for key, value in sorted(tags.items())},
    )


def _iter_documents(path: Path):
    if not path.exists():
        return
    for doc_path in sorted(path.rglob(f"*{MARKDOWN_SUFFIX}")):
        if doc_path.name in SKIP_MARKDOWN_FILES:
            continue
        if any(part.startswith(".") for part in doc_path.relative_to(path).parts):
            continue
        yield doc_path


def _find_document(space_path: Path, document: str) -> Path | None:
    raw = document.strip()
    if not raw:
        raise ValueError("document is required")
    candidate = _safe_child(space_path, raw)
    if (
        candidate.exists()
        and candidate.is_file()
        and candidate.suffix == MARKDOWN_SUFFIX
    ):
        return candidate
    doc_id = _validate_doc_id(raw)
    for doc_path in _iter_documents(space_path):
        metadata, _ = _split_markdown_frontmatter(doc_path.read_text(encoding="utf-8"))
        if metadata.get("id") == doc_id or doc_path.stem == doc_id:
            return doc_path
    return None


def _document_payload(
    *, root_path: Path, doc_path: Path, include_content: bool = False
) -> dict[str, Any]:
    raw = doc_path.read_text(encoding="utf-8")
    metadata, body = _split_markdown_frontmatter(raw)
    payload = {
        "id": str(metadata.get("id") or doc_path.stem),
        "title": str(metadata.get("title") or _markdown_title(body) or doc_path.stem),
        "space": str(metadata.get("space") or ""),
        "kind": str(metadata.get("kind") or "note"),
        "status": str(metadata.get("status") or ""),
        "tags": _as_list(metadata.get("tags")),
        "created_at": str(metadata.get("created_at") or ""),
        "updated_at": str(metadata.get("updated_at") or ""),
        "path": doc_path.relative_to(root_path).as_posix(),
    }
    if include_content:
        payload["content"] = body
    return payload


def _archive_document_version(
    *,
    space_path: Path,
    doc_path: Path,
    actor: GatewayActor,
    reason: str,
) -> dict[str, Any]:
    raw = doc_path.read_text(encoding="utf-8")
    payload = _document_payload(root_path=space_path, doc_path=doc_path)
    archived_at = _now_iso()
    checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    version_id = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{checksum[:12]}"
    )
    history_key = _validate_doc_id(str(payload["id"]))
    history_root = space_path / HISTORY_DIR
    version_root = history_root / history_key
    content_relative = f"{history_key}/{version_id}.md"
    metadata_path = version_root / f"{version_id}.json"
    entry = {
        "version_id": version_id,
        "document_id": payload["id"],
        "document_path": doc_path.relative_to(space_path).as_posix(),
        "title": payload["title"],
        "archived_at": archived_at,
        "archived_by": actor.subject,
        "reason": _clean_token(reason, default="update"),
        "checksum_sha256": checksum,
        "content_path": content_relative,
    }
    _write_text(history_root / content_relative, raw)
    _write_json(metadata_path, entry)
    _prune_document_history(version_root)
    return entry


def _resolve_document_identity(space_path: Path, document: str) -> tuple[str, str]:
    doc_path = _find_document(space_path, document)
    if doc_path:
        payload = _document_payload(root_path=space_path, doc_path=doc_path)
        return str(payload["id"]), doc_path.relative_to(space_path).as_posix()
    raw = document.strip()
    if not raw:
        raise ValueError("document is required")
    return _validate_doc_id(raw), ""


def _history_entries(
    space_path: Path,
    *,
    document_id: str = "",
    document_path: str = "",
) -> list[dict[str, Any]]:
    history_root = space_path / HISTORY_DIR
    if not history_root.exists():
        return []
    results: list[dict[str, Any]] = []
    for metadata_path in history_root.glob("*/*.json"):
        try:
            entry = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if document_id and str(entry.get("document_id") or "") != document_id:
            continue
        if document_path and str(entry.get("document_path") or "") != document_path:
            continue
        results.append(entry)
    results.sort(
        key=lambda item: (
            str(item.get("archived_at") or ""),
            str(item.get("version_id") or ""),
        ),
        reverse=True,
    )
    return results


def _find_history_entry(
    space_path: Path,
    *,
    version_id: str,
    document_id: str,
    document_path: str,
) -> dict[str, Any]:
    normalized_version = _validate_version_id(version_id)
    for entry in _history_entries(
        space_path, document_id=document_id, document_path=document_path
    ):
        if entry.get("version_id") == normalized_version:
            return entry
    raise FileNotFoundError(f"knowledge document version not found: {version_id}")


def _prune_document_history(version_root: Path) -> None:
    limit = max(1, min(int(os.getenv("GATEWAY_KNOWLEDGE_HISTORY_LIMIT", "50")), 500))
    metadata_paths = sorted(
        version_root.glob("*.json"), key=lambda path: path.name, reverse=True
    )
    for metadata_path in metadata_paths[limit:]:
        try:
            entry = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entry = {}
        content_name = Path(str(entry.get("content_path") or "")).name
        if content_name:
            (version_root / content_name).unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)


def _trash_entries(space_path: Path) -> list[dict[str, Any]]:
    trash_root = space_path / TRASH_DIR
    if not trash_root.exists():
        return []
    results: list[dict[str, Any]] = []
    for metadata_path in trash_root.glob("*.json"):
        try:
            entry = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entry["content_path"] = f"{entry.get('trash_id', '')}.md"
        results.append(entry)
    results.sort(
        key=lambda item: (
            str(item.get("deleted_at") or ""),
            str(item.get("trash_id") or ""),
        ),
        reverse=True,
    )
    return results


def _find_trash_entry(space_path: Path, trash_id: str) -> dict[str, Any]:
    normalized = _validate_version_id(trash_id)
    metadata_path = _safe_child(space_path / TRASH_DIR, f"{normalized}.json")
    if not metadata_path.exists():
        raise FileNotFoundError(f"knowledge trash entry not found: {trash_id}")
    try:
        entry = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"knowledge trash metadata is invalid: {trash_id}") from exc
    entry["content_path"] = f"{normalized}.md"
    return entry


def _document_relative_path(*, kind: str, path: str, document_id: str) -> str:
    if path.strip():
        relative = path.strip().replace("\\", "/")
        if not relative.endswith(MARKDOWN_SUFFIX):
            relative = f"{relative}{MARKDOWN_SUFFIX}"
        return relative
    folder = _clean_token(kind, default="notes")
    folder = {
        "decision": "decisions",
        "adr": "decisions",
        "link": "links",
        "source": "sources",
        "document": "documents",
        "note": "notes",
    }.get(folder, folder)
    return f"{folder}/{document_id}{MARKDOWN_SUFFIX}"


def _safe_child(parent: Path, relative: str) -> Path:
    clean = relative.strip().replace("\\", "/").lstrip("/")
    if not clean:
        raise ValueError("path is required")
    path = (parent / clean).resolve()
    parent_resolved = parent.resolve()
    try:
        path.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError("path must stay inside knowledge space") from exc
    return path


def _resolve_ingest_source(source_path: str) -> Path:
    raw = source_path.strip()
    if not raw:
        raise ValueError("source_path is required")
    roots = _configured_ingest_roots()
    if not roots:
        raise ValueError(
            "GATEWAY_KNOWLEDGE_INGEST_DIRS must be configured before ingesting server files"
        )
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if (
            any(_is_relative_to(resolved, root_path) for root_path in roots)
            and resolved.is_file()
        ):
            return resolved
    else:
        for root_path in roots:
            resolved = (root_path / raw).resolve()
            if _is_relative_to(resolved, root_path) and resolved.is_file():
                return resolved
    raise FileNotFoundError("source file is not inside an allowed ingest directory")


def _configured_ingest_roots() -> list[Path]:
    raw = os.getenv("GATEWAY_KNOWLEDGE_INGEST_DIRS", "").strip()
    roots: list[Path] = []
    for item in raw.split(";"):
        value = item.strip()
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = (root() / path).resolve()
        if path.exists() and path.is_dir():
            roots.append(path)
    return roots


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _parse_members_json(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise TypeError("members_json must be a JSON array")
    return [item for item in parsed if isinstance(item, dict)]


def _parse_tags(raw: str) -> list[str]:
    if not raw.strip():
        return []
    parsed = json.loads(raw)
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise TypeError("tags_json must be a JSON array")
    return [_clean_tag(str(item)) for item in parsed if _clean_tag(str(item))]


def _read_members(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    members: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- subject:"):
            if current:
                members.append(current)
            current = {
                "subject": stripped.split(":", 1)[1].strip().strip('"'),
                "role": "reader",
            }
        elif current and stripped.startswith("role:"):
            current["role"] = _normalize_role(
                stripped.split(":", 1)[1].strip().strip('"')
            )
    if current:
        members.append(current)
    return _dedupe_members(members)


def _write_members(path: Path, members: list[dict[str, str]]) -> None:
    lines = ["members:"]
    for member in _dedupe_members(members):
        lines.append(f"  - subject: {_yaml_scalar(member['subject'])}")
        lines.append(f"    role: {_yaml_scalar(member['role'])}")
    _write_text(path, "\n".join(lines) + "\n")


def _member_row(subject: str, role: str) -> dict[str, str]:
    return {"subject": subject.strip(), "role": _normalize_role(role)}


def _dedupe_members(members: list[dict[str, str]]) -> list[dict[str, str]]:
    by_subject: dict[str, dict[str, str]] = {}
    for member in members:
        subject = str(member.get("subject") or "").strip()
        if not subject:
            continue
        role = _normalize_role(str(member.get("role") or "reader"))
        key = _normalize_member_subject(subject)
        existing = by_subject.get(key)
        if not existing or ROLE_LEVELS[role] >= ROLE_LEVELS[existing["role"]]:
            by_subject[key] = {"subject": subject, "role": role}
    return sorted(by_subject.values(), key=lambda item: item["subject"].casefold())


def _split_markdown_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing_index is None:
        return {}, text
    return _parse_simple_frontmatter(lines[1:closing_index]), "\n".join(
        lines[closing_index + 1 :]
    ).strip()


def _parse_simple_frontmatter(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_key = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            metadata.setdefault(current_key, []).append(stripped[2:].strip().strip('"'))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        cleaned = value.strip()
        if not cleaned:
            metadata[current_key] = []
        elif cleaned.startswith("[") and cleaned.endswith("]"):
            metadata[current_key] = [
                item.strip().strip('"')
                for item in cleaned[1:-1].split(",")
                if item.strip()
            ]
        else:
            metadata[current_key] = cleaned.strip('"')
    return metadata


def _markdown_with_frontmatter(metadata: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(str(item))}")
        else:
            lines.append(f"{key}: {_yaml_scalar(str(value))}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip())
    lines.append("")
    return "\n".join(lines)


def _yaml_scalar(value: str) -> str:
    clean = str(value or "").replace("\n", " ").strip()
    if not clean:
        return '""'
    escaped = clean.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _touch_readme(path: Path) -> None:
    readme = path / "README.md"
    if not readme.exists():
        return
    metadata, body = _split_markdown_frontmatter(readme.read_text(encoding="utf-8"))
    metadata["updated_at"] = _now_iso()
    _write_text(readme, _markdown_with_frontmatter(metadata, body))


def _actor_payload(actor: GatewayActor) -> dict[str, Any]:
    return {
        "subject": actor.subject,
        "email": actor.email,
        "login": actor.login,
        "yandex_id": actor.yandex_id,
        "groups": list(actor.groups),
    }


def _actor_member_key(actor: GatewayActor) -> str:
    return actor.email or actor.login or actor.subject


def _personal_slug(actor: GatewayActor) -> str:
    value = actor.email or actor.login or actor.subject or "anonymous"
    return _slugify(value)


def _normalize_member_subject(value: str) -> str:
    return str(value or "").strip().casefold()


def _normalize_role(value: str) -> str:
    role = ROLE_ALIASES.get(str(value or "").strip().casefold())
    if not role:
        raise ValueError("role must be reader, writer, or admin")
    return role


def _validate_slug(value: str) -> str:
    slug = _slugify(value)
    if not slug or len(slug) > 100:
        raise ValueError("slug is required and must be shorter than 100 characters")
    return slug


def _validate_doc_id(value: str) -> str:
    doc_id = _slugify(value)
    if not doc_id or len(doc_id) > 160:
        raise ValueError(
            "document id is required and must be shorter than 160 characters"
        )
    return doc_id


def _validate_version_id(value: str) -> str:
    version_id = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,180}", version_id):
        raise ValueError("version id is invalid")
    return version_id


def _slugify(value: str) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text[:180]


def _clean_tag(value: str) -> str:
    return re.sub(r"\s+", "-", value.strip().casefold())[:80].strip("-")


def _clean_token(value: str, *, default: str) -> str:
    token = _slugify(value)
    return token or default


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _markdown_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _first_paragraph(text: str) -> str:
    paragraphs = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return paragraphs[0] if paragraphs else ""


def _ensure_heading(title: str, content: str) -> str:
    if content.lstrip().startswith("#"):
        return content.rstrip() + "\n"
    return f"# {title}\n\n{content.rstrip()}\n"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


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

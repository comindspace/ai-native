import json

from mcp.types import ToolAnnotations

from gateway_mcp.services.knowledge import (
    add_member,
    audit_access,
    create_space,
    delete_document,
    get_document,
    ingest_file,
    list_document_versions,
    list_spaces,
    list_trash,
    put_document,
    reindex,
    remove_member,
    restore_document_version,
    restore_trash,
    search_documents,
    space_info,
)
from gateway_mcp.tools.runtime import ToolRun


def register_knowledge_tools(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Knowledge Spaces", readOnlyHint=True)
    )
    async def gateway_knowledge_spaces(include_personal: bool = True) -> str:
        """List personal and group markdown knowledge spaces visible to the current actor."""
        tool = "gateway_knowledge_spaces"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={"include_personal": include_personal},
        )
        try:
            actor = run.require_scope()
            spaces = list_spaces(actor=actor, include_personal=include_personal)
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(spaces), "spaces": spaces},
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Knowledge Space List", readOnlyHint=True
        )
    )
    async def gateway_knowledge_space_list(include_personal: bool = True) -> str:
        """Compatibility alias for gateway_knowledge_spaces."""
        tool = "gateway_knowledge_space_list"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={"include_personal": include_personal},
        )
        try:
            actor = run.require_scope()
            spaces = list_spaces(actor=actor, include_personal=include_personal)
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(spaces), "spaces": spaces},
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Knowledge Space Get", readOnlyHint=True
        )
    )
    async def gateway_knowledge_space_get(space: str = "") -> str:
        """Get metadata, members, and document count for a personal or group knowledge space."""
        tool = "gateway_knowledge_space_get"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={"space": space},
        )
        try:
            actor = run.require_scope()
            result = space_info(actor=actor, space=space)
            run.finish()
            return json.dumps(
                {"ok": True, "space": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Space Add Member"))
    async def gateway_knowledge_space_add_member(
        space: str, subject: str, role: str = "reader"
    ) -> str:
        """Compatibility alias for gateway_knowledge_member_add."""
        tool = "gateway_knowledge_space_add_member"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={"space": space, "subject": subject, "role": role},
        )
        try:
            actor = run.require_scope()
            result = add_member(actor=actor, space=space, subject=subject, role=role)
            run.finish()
            return json.dumps(
                {"ok": True, "space": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Space Create"))
    async def gateway_knowledge_space_create(
        slug: str,
        title: str,
        description: str = "",
        members_json: str = "[]",
    ) -> str:
        """Create a group markdown knowledge space. The creator becomes admin."""
        tool = "gateway_knowledge_space_create"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={
                "slug": slug,
                "title": title,
                "description": description,
                "members_json": members_json,
            },
        )
        try:
            actor = run.require_scope()
            result = create_space(
                actor=actor,
                slug=slug,
                title=title,
                description=description,
                members_json=members_json,
            )
            run.finish()
            return json.dumps(
                {"ok": True, "space": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Knowledge Space Remove Member")
    )
    async def gateway_knowledge_space_remove_member(space: str, subject: str) -> str:
        """Compatibility alias for gateway_knowledge_member_remove."""
        tool = "gateway_knowledge_space_remove_member"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={"space": space, "subject": subject},
        )
        try:
            actor = run.require_scope()
            result = remove_member(actor=actor, space=space, subject=subject)
            run.finish()
            return json.dumps(
                {"ok": True, "space": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Knowledge Space Set Permission")
    )
    async def gateway_knowledge_space_set_permission(
        space: str, subject: str, role: str = "reader"
    ) -> str:
        """Set a member role in a group knowledge space. Requires space admin access."""
        tool = "gateway_knowledge_space_set_permission"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={"space": space, "subject": subject, "role": role},
        )
        try:
            actor = run.require_scope()
            result = add_member(actor=actor, space=space, subject=subject, role=role)
            run.finish()
            return json.dumps(
                {"ok": True, "space": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Member Add"))
    async def gateway_knowledge_member_add(
        space: str, subject: str, role: str = "reader"
    ) -> str:
        """Add or update a member in a group knowledge space. Requires space admin access."""
        tool = "gateway_knowledge_member_add"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={"space": space, "subject": subject, "role": role},
        )
        try:
            actor = run.require_scope()
            result = add_member(actor=actor, space=space, subject=subject, role=role)
            run.finish()
            return json.dumps(
                {"ok": True, "space": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Knowledge Document Search", readOnlyHint=True
        )
    )
    async def gateway_knowledge_document_search(
        query: str = "",
        space: str = "",
        limit: int = 10,
        include_personal: bool = True,
        include_groups: bool = True,
    ) -> str:
        """Compatibility alias for gateway_knowledge_search."""
        tool = "gateway_knowledge_document_search"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={
                "query": query,
                "space": space,
                "limit": limit,
                "include_personal": include_personal,
                "include_groups": include_groups,
            },
        )
        try:
            actor = run.require_scope()
            results = search_documents(
                actor=actor,
                query=query,
                space=space,
                limit=limit,
                include_personal=include_personal,
                include_groups=include_groups,
            )
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(results), "documents": results},
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Member Remove"))
    async def gateway_knowledge_member_remove(space: str, subject: str) -> str:
        """Remove a member from a group knowledge space. Requires space admin access."""
        tool = "gateway_knowledge_member_remove"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={"space": space, "subject": subject},
        )
        try:
            actor = run.require_scope()
            result = remove_member(actor=actor, space=space, subject=subject)
            run.finish()
            return json.dumps(
                {"ok": True, "space": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Knowledge Audit Access", readOnlyHint=True
        )
    )
    async def gateway_knowledge_audit_access(space: str = "") -> str:
        """Compatibility alias for gateway_knowledge_access_audit."""
        tool = "gateway_knowledge_audit_access"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={"space": space},
        )
        try:
            actor = run.require_scope()
            result = audit_access(actor=actor, space=space)
            run.finish()
            return json.dumps(
                {"ok": True, "access": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Document Put"))
    async def gateway_knowledge_document_put(
        title: str,
        content: str,
        space: str = "",
        kind: str = "note",
        tags_json: str = "[]",
        path: str = "",
        document_id: str = "",
        status: str = "draft",
    ) -> str:
        """Create or update a markdown document in a personal or group knowledge space."""
        tool = "gateway_knowledge_document_put"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={
                "title": title,
                "space": space,
                "kind": kind,
                "tags_json": tags_json,
                "path": path,
                "document_id": document_id,
                "status": status,
            },
        )
        try:
            actor = run.require_scope()
            result = put_document(
                actor=actor,
                space=space,
                title=title,
                content=content,
                kind=kind,
                tags_json=tags_json,
                path=path,
                document_id=document_id,
                status=status,
            )
            run.finish()
            return json.dumps(
                {"ok": True, "document": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Knowledge Document Get", readOnlyHint=True
        )
    )
    async def gateway_knowledge_document_get(document: str, space: str = "") -> str:
        """Read a markdown document from a personal or group knowledge space."""
        tool = "gateway_knowledge_document_get"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={"document": document, "space": space},
        )
        try:
            actor = run.require_scope()
            result = get_document(actor=actor, space=space, document=document)
            run.finish()
            return json.dumps(
                {"ok": True, "document": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Knowledge Search", readOnlyHint=True)
    )
    async def gateway_knowledge_search(
        query: str = "",
        space: str = "",
        limit: int = 10,
        include_personal: bool = True,
        include_groups: bool = True,
    ) -> str:
        """Search accessible markdown knowledge spaces and return citations."""
        tool = "gateway_knowledge_search"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={
                "query": query,
                "space": space,
                "limit": limit,
                "include_personal": include_personal,
                "include_groups": include_groups,
            },
        )
        try:
            actor = run.require_scope()
            results = search_documents(
                actor=actor,
                query=query,
                space=space,
                limit=limit,
                include_personal=include_personal,
                include_groups=include_groups,
            )
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(results), "documents": results},
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Document Delete"))
    async def gateway_knowledge_document_delete(document: str, space: str = "") -> str:
        """Soft-delete a markdown document and keep it in the space trash."""
        tool = "gateway_knowledge_document_delete"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={"document": document, "space": space},
        )
        try:
            actor = run.require_scope()
            result = delete_document(actor=actor, space=space, document=document)
            run.finish()
            return json.dumps(
                {"ok": True, "document": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Knowledge Document Versions", readOnlyHint=True
        )
    )
    async def gateway_knowledge_document_versions(
        document: str, space: str = "", limit: int = 50
    ) -> str:
        """List retained versions of a markdown document."""
        tool = "gateway_knowledge_document_versions"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={"document": document, "space": space, "limit": limit},
        )
        try:
            actor = run.require_scope()
            versions = list_document_versions(
                actor=actor, space=space, document=document, limit=limit
            )
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(versions), "versions": versions},
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Document Restore"))
    async def gateway_knowledge_document_restore(
        document: str, version_id: str, space: str = ""
    ) -> str:
        """Restore a retained document version and archive the current version first."""
        tool = "gateway_knowledge_document_restore"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={"document": document, "version_id": version_id, "space": space},
        )
        try:
            actor = run.require_scope()
            result = restore_document_version(
                actor=actor,
                space=space,
                document=document,
                version_id=version_id,
            )
            run.finish()
            return json.dumps(
                {"ok": True, "document": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(title="Gateway Knowledge Trash", readOnlyHint=True)
    )
    async def gateway_knowledge_trash_list(space: str = "", limit: int = 50) -> str:
        """List soft-deleted documents in an accessible knowledge space."""
        tool = "gateway_knowledge_trash_list"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={"space": space, "limit": limit},
        )
        try:
            actor = run.require_scope()
            entries = list_trash(actor=actor, space=space, limit=limit)
            run.finish()
            return json.dumps(
                {"ok": True, "count": len(entries), "trash": entries},
                ensure_ascii=False,
                indent=2,
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Trash Restore"))
    async def gateway_knowledge_trash_restore(trash_id: str, space: str = "") -> str:
        """Restore a soft-deleted document to its original path."""
        tool = "gateway_knowledge_trash_restore"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={"trash_id": trash_id, "space": space},
        )
        try:
            actor = run.require_scope()
            result = restore_trash(actor=actor, space=space, trash_id=trash_id)
            run.finish()
            return json.dumps(
                {"ok": True, "document": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Ingest File"))
    async def gateway_knowledge_ingest_file(
        source_path: str,
        space: str = "",
        title: str = "",
        kind: str = "source",
        tags_json: str = "[]",
        status: str = "source",
    ) -> str:
        """Import a server-side UTF-8 text/markdown file from an allowed ingest directory into a knowledge space."""
        tool = "gateway_knowledge_ingest_file"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={
                "source_path": source_path,
                "space": space,
                "title": title,
                "kind": kind,
                "tags_json": tags_json,
                "status": status,
            },
        )
        try:
            actor = run.require_scope()
            result = ingest_file(
                actor=actor,
                source_path=source_path,
                space=space,
                title=title,
                kind=kind,
                tags_json=tags_json,
                status=status,
            )
            run.finish()
            return json.dumps(
                {"ok": True, "document": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Knowledge Reindex"))
    async def gateway_knowledge_reindex(space: str = "") -> str:
        """Rebuild markdown indexes for accessible knowledge spaces."""
        tool = "gateway_knowledge_reindex"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:write",
            arguments={"space": space},
        )
        try:
            actor = run.require_scope()
            result = reindex(actor=actor, space=space)
            run.finish()
            return json.dumps(
                {"ok": True, "index": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Gateway Knowledge Access Audit", readOnlyHint=True
        )
    )
    async def gateway_knowledge_access_audit(space: str = "") -> str:
        """Show current actor permissions for knowledge spaces."""
        tool = "gateway_knowledge_access_audit"
        run = ToolRun.start(
            tool=tool,
            system="knowledge",
            scope="memory:read",
            arguments={"space": space},
        )
        try:
            actor = run.require_scope()
            result = audit_access(actor=actor, space=space)
            run.finish()
            return json.dumps(
                {"ok": True, "access": result}, ensure_ascii=False, indent=2
            )
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

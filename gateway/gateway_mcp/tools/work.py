import json

from mcp.types import ToolAnnotations

from gateway_mcp.config import read_json, tools_file
from gateway_mcp.services.factory_preflight import claim_with_preflight
from gateway_mcp.services.work import (
    accept_work,
    complete_work,
    get_work,
    intake_work,
    metrics,
    record_artifact_manifest,
    record_event,
    resolve_project_scope,
    search_work,
    set_tracker_completion_policy,
)
from gateway_mcp.tools.runtime import ToolRun


def register_work_tools(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Gateway Project Scope Resolve", readOnlyHint=True))
    async def gateway_project_scope_resolve(
        project_id: str,
        signal_summary: str,
        scope_id: str = "",
        limit: int = 5,
    ) -> str:
        run = ToolRun.start(
            tool="gateway_project_scope_resolve",
            system="work",
            scope="factory:read",
            arguments={"project_id": project_id, "scope_id": scope_id, "limit": limit},
        )
        try:
            run.require_scope()
            result = await resolve_project_scope(
                project_id=project_id,
                signal_summary=signal_summary,
                scope_id=scope_id,
                tools_registry=read_json(tools_file(), {"tools": []}),
                limit=limit,
            )
            run.finish()
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Intake"))
    async def gateway_work_intake(
        project_id: str,
        source_type: str,
        intent_summary: str,
        execution_mode: str,
        sdd_level: str,
        scope_decision: str,
        project_path: str = "",
        scope_id: str = "",
        source_ref: str = "",
        source_refs_json: str = "[]",
        acceptance_criteria_json: str = "[]",
        quality_gates_json: str = "[]",
        risk_level: str = "normal",
        work_kind: str = "code_change",
        priority: int = 0,
        idempotency_key: str = "",
        contract_metadata_json: str = "{}",
        tracker_completion_policy_json: str = "{}",
    ) -> str:
        run = ToolRun.start(
            tool="gateway_work_intake",
            system="work",
            scope="factory:write",
            arguments={
                "project_id": project_id,
                "execution_mode": execution_mode,
                "sdd_level": sdd_level,
            },
        )
        try:
            actor = run.require_scope()
            result = intake_work(
                actor=actor,
                project_id=project_id,
                project_path=project_path,
                scope_id=scope_id,
                scope_decision=scope_decision,
                source_type=source_type,
                source_ref=source_ref,
                source_refs=_list_of_objects(source_refs_json),
                intent_summary=intent_summary,
                acceptance_criteria=_list_of_strings(acceptance_criteria_json),
                quality_gates=_list_of_strings(quality_gates_json),
                execution_mode=execution_mode,
                sdd_level=sdd_level,
                risk_level=risk_level,
                work_kind=work_kind,
                priority=priority,
                idempotency_key=idempotency_key,
                contract_metadata=_object(contract_metadata_json),
                tracker_completion_policy=_object(tracker_completion_policy_json),
            )
            run.finish()
            return _json({"ok": True, "work": result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Get", readOnlyHint=True))
    async def gateway_work_get(work_id: str, include_events: bool = True) -> str:
        return await _read_tool(
            "gateway_work_get",
            {"work_id": work_id},
            lambda actor: {"work": get_work(actor, work_id, include_events=include_events)},
        )

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Search", readOnlyHint=True))
    async def gateway_work_search(
        project_id: str = "",
        status: str = "",
        execution_mode: str = "",
        actor_subject: str = "",
        limit: int = 25,
    ) -> str:
        return await _read_tool(
            "gateway_work_search",
            {
                "project_id": project_id,
                "status": status,
                "execution_mode": execution_mode,
                "limit": limit,
            },
            lambda actor: {
                "work": search_work(
                    actor=actor,
                    project_id=project_id,
                    status=status,
                    execution_mode=execution_mode,
                    actor_subject=actor_subject,
                    limit=limit,
                )
            },
        )

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Claim"))
    async def gateway_work_claim(work_id: str = "", project_id: str = "", lease_seconds: int = 1800) -> str:
        run = ToolRun.start(
            tool="gateway_work_claim",
            system="work",
            scope="factory:claim",
            arguments={
                "work_id": work_id,
                "project_id": project_id,
                "lease_seconds": lease_seconds,
            },
        )
        try:
            actor = run.require_scope()
            result = await claim_with_preflight(
                actor=actor,
                work_id=work_id,
                project_id=project_id,
                lease_seconds=lease_seconds,
            )
            run.finish()
            return _json({
                "ok": True,
                "claimed": bool(result and result.get("status") == "running"),
                "work": result,
            })
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Event"))
    async def gateway_work_event(work_id: str, event_type: str, payload_json: str = "{}") -> str:
        run = ToolRun.start(
            tool="gateway_work_event",
            system="work",
            scope="factory:write",
            arguments={"work_id": work_id, "event_type": event_type},
        )
        try:
            actor = run.require_scope()
            result = record_event(
                actor=actor,
                work_id=work_id,
                event_type=event_type,
                payload=_object(payload_json),
            )
            run.finish()
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Artifact Record"))
    async def gateway_work_artifact_record(
        work_id: str,
        phase: str,
        refs_json: str,
        producer: str,
        checks_json: str = "[]",
        previous_digest: str = "",
    ) -> str:
        """Append one hash-linked, metadata-only artifact phase to a Work Contract."""
        run = ToolRun.start(
            tool="gateway_work_artifact_record",
            system="work",
            scope="factory:write",
            arguments={"work_id": work_id, "phase": phase},
        )
        try:
            actor = run.require_scope()
            result = record_artifact_manifest(
                actor=actor,
                work_id=work_id,
                phase=phase,
                refs=_list_of_objects(refs_json),
                checks=_list_of_objects(checks_json),
                producer=producer,
                previous_digest=previous_digest,
            )
            run.finish()
            return _json({"ok": True, **result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Tracker Completion Policy Set"))
    async def gateway_work_tracker_policy_set(work_id: str, policy_json: str) -> str:
        """Set the Tracker lifecycle policy without transitioning the issue."""
        run = ToolRun.start(
            tool="gateway_work_tracker_policy_set",
            system="work",
            scope="factory:write",
            arguments={"work_id": work_id},
        )
        try:
            actor = run.require_scope()
            result = set_tracker_completion_policy(
                actor=actor,
                work_id=work_id,
                policy=_object(policy_json),
            )
            run.finish()
            return _json({"ok": True, "work": result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Complete"))
    async def gateway_work_complete(
        work_id: str,
        success: bool,
        result_refs_json: str,
        evidence_state: str,
        admin_actions: int = 0,
        metrics_json: str = "{}",
    ) -> str:
        """Finish execution and record evidence.

        result_refs_json must be a JSON array of objects with `type`, `uri`,
        and optional `title`, for example an MR, commit, branch, or document.
        Call this before gateway_work_accept. Acceptance is rejected until
        successful completion has recorded verification evidence.
        """
        run = ToolRun.start(
            tool="gateway_work_complete",
            system="work",
            scope="factory:write",
            arguments={
                "work_id": work_id,
                "success": success,
                "evidence_state": evidence_state,
            },
        )
        try:
            actor = run.require_scope()
            result = complete_work(
                actor=actor,
                work_id=work_id,
                success=success,
                result_refs=_list_of_objects(result_refs_json),
                evidence_state=evidence_state,
                admin_actions=admin_actions,
                metrics=_object(metrics_json),
            )
            run.finish()
            return _json({"ok": True, "work": result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Accept"))
    async def gateway_work_accept(work_id: str, accepted: bool, decision_ref: str = "") -> str:
        """Record the independent review decision after execution evidence exists."""
        run = ToolRun.start(
            tool="gateway_work_accept",
            system="work",
            scope="factory:write",
            arguments={"work_id": work_id, "accepted": accepted},
        )
        try:
            actor = run.require_scope()
            result = accept_work(
                actor=actor,
                work_id=work_id,
                accepted=accepted,
                decision_ref=decision_ref,
            )
            run.finish()
            return _json({"ok": True, "work": result})
        except PermissionError as exc:
            run.denied(exc)
            raise
        except Exception as exc:
            run.error(exc)
            raise

    @mcp.tool(annotations=ToolAnnotations(title="Gateway Work Metrics", readOnlyHint=True))
    async def gateway_work_metrics(project_id: str = "", days: int = 30) -> str:
        return await _read_tool(
            "gateway_work_metrics",
            {"project_id": project_id, "days": days},
            lambda actor: {"metrics": metrics(actor=actor, project_id=project_id, days=days)},
        )


async def _read_tool(name: str, arguments: dict, call) -> str:
    run = ToolRun.start(tool=name, system="work", scope="factory:read", arguments=arguments)
    try:
        actor = run.require_scope()
        result = call(actor)
        run.finish()
        return _json({"ok": True, **result})
    except PermissionError as exc:
        run.denied(exc)
        raise
    except Exception as exc:
        run.error(exc)
        raise


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _decoded(raw: str):
    try:
        return json.loads(raw or "null")
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON") from exc


def _object(raw: str) -> dict:
    value = _decoded(raw)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _list_of_objects(raw: str) -> list[dict]:
    value = _decoded(raw)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("expected a JSON array of objects")
    return value


def _list_of_strings(raw: str) -> list[str]:
    value = _decoded(raw)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("expected a JSON array of strings")
    return value

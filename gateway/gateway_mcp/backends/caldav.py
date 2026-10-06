import asyncio
import json
import os
from datetime import datetime, time, timedelta, timezone
from typing import Any

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError, _caldav_user_credentials

def _parse_datetime(value: Any, default: datetime) -> datetime:
    if not value:
        return default
    text = str(value).strip().replace("Z", "+00:00")
    if len(text) == 10:
        return datetime.combine(datetime.fromisoformat(text).date(), time.min)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _serialize_calendar_event(event: Any) -> dict[str, Any]:
    raw = getattr(event, "data", "") or ""
    result: dict[str, Any] = {"url": str(getattr(event, "url", "")), "raw": raw}
    try:
        from icalendar import Calendar

        calendar = Calendar.from_ical(raw)
        for component in calendar.walk("VEVENT"):
            def decoded(name: str) -> Any:
                try:
                    value = component.decoded(name)
                    return value.isoformat() if hasattr(value, "isoformat") else value
                except Exception:
                    return str(component.get(name, "") or "")

            result.update(
                {
                    "uid": str(component.get("uid", "") or ""),
                    "summary": str(component.get("summary", "") or ""),
                    "description": str(component.get("description", "") or ""),
                    "location": str(component.get("location", "") or ""),
                    "start": decoded("dtstart"),
                    "end": decoded("dtend"),
                }
            )
            break
    except Exception:
        pass
    return result


def _caldav_sync(operation: str, arguments: dict[str, Any], username: str, password: str) -> dict[str, Any]:
    try:
        import caldav
    except ImportError as exc:
        raise BackendConfigError("Install caldav dependency to use calendar routes") from exc

    if not username:
        raise BackendConfigError("Missing Yandex user email/login for CalDAV")

    client = caldav.DAVClient(
        url=os.getenv("CALDAV_URL", "https://caldav.yandex.ru"),
        username=username,
        password=password,
    )

    principal = client.principal()
    calendars = principal.calendars()

    if operation == "list_calendars":
        return {
            "ok": True,
            "backend": "caldav",
            "data": {
                "calendars": [
                    {"index": index, "name": getattr(calendar, "name", ""), "url": str(calendar.url)}
                    for index, calendar in enumerate(calendars)
                ]
            },
        }

    if operation == "create_event":
        calendar_index = int(arguments.get("calendar_index") or 0)
        if calendar_index < 0 or calendar_index >= len(calendars):
            raise BackendRouteError(f"Calendar index out of range: {calendar_index}")
        summary = str(arguments.get("summary") or "").strip()
        if not summary:
            raise BackendRouteError("calendar.events.create requires summary")
        start = _parse_datetime(arguments.get("start"), datetime.now() + timedelta(hours=1))
        end = _parse_datetime(arguments.get("end"), start + timedelta(hours=1))
        if end <= start:
            raise BackendRouteError("calendar.events.create requires end after start")
        description = str(arguments.get("description") or "")
        location = str(arguments.get("location") or "")
        attendee = str(arguments.get("attendee") or "").strip()
        extra: dict[str, Any] = {}
        if attendee:
            extra["attendee"] = [attendee]
        event = calendars[calendar_index].save_event(
            dtstart=start,
            dtend=end,
            summary=summary,
            description=description,
            location=location,
            **extra,
        )
        return {
            "ok": True,
            "backend": "caldav",
            "data": {"event": _serialize_calendar_event(event)},
        }

    if operation != "search_events":
        raise BackendRouteError(f"Unsupported CalDAV operation: {operation or '<missing>'}")

    calendar_index = int(arguments.get("calendar_index") or 0)
    if calendar_index < 0 or calendar_index >= len(calendars):
        raise BackendRouteError(f"Calendar index out of range: {calendar_index}")

    now = datetime.now()
    start = _parse_datetime(arguments.get("start_date"), now - timedelta(days=7))
    end = _parse_datetime(arguments.get("end_date"), now + timedelta(days=30))
    limit = max(1, int(arguments.get("limit") or 50))
    query = str(arguments.get("query") or "").lower()

    events = calendars[calendar_index].date_search(start=start, end=end, expand=True)
    serialized = [_serialize_calendar_event(event) for event in events]
    if query:
        serialized = [
            event
            for event in serialized
            if query in json.dumps(event, ensure_ascii=False).lower()
        ]

    return {
        "ok": True,
        "backend": "caldav",
        "data": {
            "calendar_index": calendar_index,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "events": serialized[:limit],
        },
    }


async def _call_caldav(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    operation = str(route.get("operation", ""))
    try:
        username, password = _caldav_user_credentials()
    except BackendConfigError as exc:
        return {
            "ok": False,
            "status": "credential_missing",
            "backend": "caldav",
            "error": str(exc),
            "credential_provider": "yandex-caldav",
            "credentials_url": "/credentials",
        }
    return await asyncio.to_thread(_caldav_sync, operation, arguments, username, password)

from html import escape
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from gateway_mcp.routes.admin_ui import admin_shell, empty_row, fmt_time
from gateway_mcp.services.policy import has_scope
from gateway_mcp.services.storage import list_audit_events
from gateway_mcp.web import login_redirect, web_actor


PAGE_SIZE = 50
DECISIONS = (
    ("", "Все решения"),
    ("allow", "Разрешено"),
    ("deny", "Отказано"),
)
STATUSES = (
    ("", "Все статусы"),
    ("ok", "Успешно"),
    ("allowed", "Разрешено"),
    ("denied", "Отказано"),
    ("blocked", "Заблокировано"),
    ("failed", "Не выполнено"),
    ("error", "Ошибка"),
    ("shadow_denied", "Теневой запрет"),
)


def register_admin_audit_routes(mcp) -> None:
    @mcp.custom_route("/admin/audit", methods=["GET"], include_in_schema=False)
    async def admin_audit_page(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/admin/audit")
        if not has_scope(actor, "access:admin"):
            return PlainTextResponse("access:admin is required.", status_code=403)

        filters = _filters(request)
        page = _page(request.query_params.get("page"))
        try:
            rows = list_audit_events(
                days=filters["days"],
                actor_subject=filters["actor_subject"],
                event=filters["event"],
                tool=filters["tool"],
                system=filters["system"],
                decision=filters["decision"],
                status=filters["status"],
                gateway_request_id=filters["gateway_request_id"],
                limit=PAGE_SIZE + 1,
                offset=(page - 1) * PAGE_SIZE,
                include_payload=False,
            )
            error = ""
        except Exception as exc:
            rows = []
            error = f"{exc.__class__.__name__}: {exc}"

        has_next = len(rows) > PAGE_SIZE
        visible_rows = rows[:PAGE_SIZE]
        body = f"""
        <div class="page-head">
          <div>
            <h1>Журнал событий</h1>
            <p class="lead muted">Действия шлюза, решения доступа и технические результаты без содержимого запросов и чувствительных данных.</p>
          </div>
          <span class="status ok">{len(visible_rows)} событий</span>
        </div>
        {_error_banner(error)}
        {_filter_form(filters)}

        <section class="panel wide">
          <div class="panel-header">
            <div><h2>События</h2><p class="description">Новые события показаны первыми. Для сквозного расследования используйте идентификатор запроса.</p></div>
            <span class="status ok">страница {page}</span>
          </div>
          <div class="table-wrap"><table>
            <thead><tr><th>Время</th><th>Пользователь</th><th>Система</th><th>Событие</th><th>Решение</th><th>Scope</th><th>Запрос</th></tr></thead>
            <tbody>{_event_rows(visible_rows)}</tbody>
          </table></div>
          {_pager(filters, page=page, has_next=has_next)}
        </section>
        """
        return HTMLResponse(
            admin_shell(
                title="Журнал событий",
                active="audit",
                actor=actor,
                body=body,
                shell_width="1440px",
            )
        )


def _filters(request: Request) -> dict[str, Any]:
    params = request.query_params
    return {
        "days": _days(params.get("days")),
        "actor_subject": _text(params.get("actor_subject"), 200),
        "system": _text(params.get("system"), 100),
        "event": _text(params.get("event"), 120),
        "tool": _text(params.get("tool"), 160),
        "decision": _choice(params.get("decision"), DECISIONS),
        "status": _choice(params.get("status"), STATUSES),
        "gateway_request_id": _text(params.get("gateway_request_id"), 64),
    }


def _filter_form(filters: dict[str, Any]) -> str:
    return f"""
    <form class="audit-filter-grid" method="get" action="/admin/audit">
      <label>Период
        <select name="days">{_period_options(int(filters["days"]))}</select>
      </label>
      {_text_field("Пользователь", "actor_subject", filters["actor_subject"], "yandex:...")}
      {_text_field("Система", "system", filters["system"], "1c, gitlab, gateway")}
      {_text_field("Событие", "event", filters["event"], "resource_access")}
      {_text_field("Инструмент", "tool", filters["tool"], "1c.odata.query")}
      <label>Решение
        <select name="decision">{_select_options(DECISIONS, str(filters["decision"]))}</select>
      </label>
      <label>Статус
        <select name="status">{_select_options(STATUSES, str(filters["status"]))}</select>
      </label>
      {_text_field("Идентификатор запроса", "gateway_request_id", filters["gateway_request_id"], "0123456789abcdef")}
      <div class="audit-filter-actions">
        <button type="submit">Найти</button>
        <a class="button secondary" href="/admin/audit">Сбросить</a>
      </div>
    </form>
    """


def _event_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return empty_row(7, "События по выбранным условиям не найдены")
    return "".join(
        f"""
        <tr>
          <td>{escape(fmt_time(row.get("created_at")))}</td>
          <td>{escape(str(row.get("actor_subject") or "—"))}</td>
          <td>{escape(str(row.get("system") or "—"))}</td>
          <td><strong>{escape(str(row.get("event") or "—"))}</strong>{_subvalue(row.get("tool"))}</td>
          <td>{_decision_badges(row.get("decision"), row.get("status"))}</td>
          <td>{_code(row.get("scope"))}</td>
          <td>{_request_link(row.get("gateway_request_id"))}</td>
        </tr>
        """
        for row in rows
    )


def _decision_badges(decision: object, status: object) -> str:
    decision_value = str(decision or "").strip()
    status_value = str(status or "").strip()
    parts = []
    if decision_value:
        css = "missing" if decision_value == "deny" else "ok"
        parts.append(
            f'<span class="status {css}">{escape(_label(DECISIONS, decision_value))}</span>'
        )
    if status_value and status_value != decision_value:
        css = (
            "missing"
            if status_value in {"denied", "blocked", "failed", "error", "shadow_denied"}
            else "ok"
        )
        parts.append(
            f'<span class="status {css}">{escape(_label(STATUSES, status_value))}</span>'
        )
    return '<span class="audit-badges">' + "".join(parts or ["—"]) + "</span>"


def _request_link(value: object) -> str:
    request_id = str(value or "").strip()
    if not request_id:
        return "—"
    href = "/admin/audit?" + urlencode({"gateway_request_id": request_id})
    return f'<a href="{escape(href)}"><code>{escape(request_id)}</code></a>'


def _pager(filters: dict[str, Any], *, page: int, has_next: bool) -> str:
    if page == 1 and not has_next:
        return ""
    links = []
    if page > 1:
        links.append(
            f'<a class="button secondary compact" href="{escape(_page_url(filters, page - 1))}">Назад</a>'
        )
    links.append(f'<span class="muted small">Страница {page}</span>')
    if has_next:
        links.append(
            f'<a class="button secondary compact" href="{escape(_page_url(filters, page + 1))}">Далее</a>'
        )
    return (
        '<nav class="audit-pager" aria-label="Страницы журнала">'
        + "".join(links)
        + "</nav>"
    )


def _page_url(filters: dict[str, Any], page: int) -> str:
    params = {
        key: value
        for key, value in filters.items()
        if value not in {"", None} and not (key == "days" and value == 7)
    }
    if page > 1:
        params["page"] = page
    query = urlencode(params)
    return "/admin/audit" + (f"?{query}" if query else "")


def _text_field(label: str, name: str, value: object, placeholder: str) -> str:
    return f"""
    <label>{escape(label)}
      <input type="text" name="{escape(name)}" value="{escape(str(value or ""))}" placeholder="{escape(placeholder)}">
    </label>
    """


def _period_options(selected: int) -> str:
    return _select_options(
        (
            (1, "24 часа"),
            (7, "7 дней"),
            (30, "30 дней"),
            (90, "90 дней"),
            (365, "365 дней"),
        ),
        str(selected),
    )


def _select_options(options: tuple[tuple[Any, str], ...], selected: str) -> str:
    return "".join(
        f'<option value="{escape(str(value))}"{" selected" if str(value) == selected else ""}>{escape(label)}</option>'
        for value, label in options
    )


def _label(options: tuple[tuple[Any, str], ...], value: str) -> str:
    return next((label for key, label in options if str(key) == value), value)


def _subvalue(value: object) -> str:
    clean = str(value or "").strip()
    return f'<span class="table-sub">{escape(clean)}</span>' if clean else ""


def _code(value: object) -> str:
    clean = str(value or "").strip()
    return f"<code>{escape(clean)}</code>" if clean else "—"


def _error_banner(message: str) -> str:
    if not message:
        return ""
    return f'<div class="banner error">Не удалось прочитать журнал: {escape(message)}</div>'


def _days(value: object) -> int:
    try:
        days = int(str(value or "7"))
    except ValueError:
        return 7
    return days if days in {1, 7, 30, 90, 365} else 7


def _page(value: object) -> int:
    try:
        return max(1, min(int(str(value or "1")), 10_000))
    except ValueError:
        return 1


def _text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _choice(value: object, options: tuple[tuple[Any, str], ...]) -> str:
    clean = str(value or "").strip()
    return clean if any(str(key) == clean for key, _ in options) else ""

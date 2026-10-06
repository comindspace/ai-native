from html import escape
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from gateway_mcp.routes.admin_ui import admin_shell, empty_row, fmt_time
from gateway_mcp.services.policy import has_scope
from gateway_mcp.services.telemetry import skill_stats
from gateway_mcp.web import login_redirect, web_actor


PERIODS = (
    (1, "24 часа"),
    (7, "7 дней"),
    (30, "30 дней"),
    (90, "90 дней"),
    (365, "365 дней"),
)


def register_admin_telemetry_routes(mcp) -> None:
    @mcp.custom_route("/admin/telemetry/skills", methods=["GET"], include_in_schema=False)
    async def admin_skill_telemetry_page(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/admin/telemetry/skills")
        if not has_scope(actor, "access:admin"):
            return PlainTextResponse("access:admin is required.", status_code=403)

        filters = _filters(request)
        try:
            result = skill_stats(limit=250, **filters)
            rows = result.get("skills", [])
            error = ""
        except Exception as exc:
            rows = []
            error = f"{exc.__class__.__name__}: {exc}"

        totals = _totals(rows)
        body = f"""
        <div class="page-head">
          <div>
            <h1>Метрики навыков</h1>
            <p class="lead muted">Какие навыки запускают сотрудники, в каких клиентах и чем заканчивается выполнение. Тексты запросов и результаты здесь не сохраняются.</p>
          </div>
          <span class="status ok">{int(filters["days"])} дней</span>
        </div>
        {_error_banner(error)}
        {_filter_form(filters)}

        <section class="stat-grid" aria-label="Сводка по навыкам">
          {_stat("Запуски", totals["started"], "за выбранный период")}
          {_stat("Завершено", totals["completed"], f'{totals["success_rate"]}% успешных завершений')}
          {_stat("Ошибки", totals["failed"], "явно завершены с ошибкой", bad=totals["failed"] > 0)}
          {_stat("Прервано", totals["abandoned"], "нет результата более 30 минут", bad=totals["abandoned"] > 0)}
          {_stat("В работе", totals["running"], "запущены менее 30 минут назад")}
        </section>

        <section class="panel wide">
          <div class="panel-header">
            <div><h2>Использование навыков</h2><p class="description">Одна строка соответствует навыку, его версии, агенту и проекту.</p></div>
            <span class="status ok">{len(rows)} строк</span>
          </div>
          <div class="table-wrap"><table>
            <thead><tr><th>Навык</th><th>Пакет</th><th>Версия</th><th>Агент</th><th>Проект</th><th>Запуски</th><th>Завершено</th><th>Ошибки</th><th>Прервано</th><th>Успешность</th><th>Пользователи</th><th>Медиана</th><th>95%</th><th>Последний запуск</th></tr></thead>
            <tbody>{_skill_rows(rows)}</tbody>
          </table></div>
        </section>
        """
        return HTMLResponse(
            admin_shell(
                title="Метрики навыков",
                active="telemetry",
                actor=actor,
                body=body,
                shell_width="1560px",
            )
        )


def _filters(request: Request) -> dict[str, Any]:
    params = request.query_params
    return {
        "days": _days(params.get("days")),
        "agent": _text(params.get("agent")),
        "skill_id": _text(params.get("skill_id")),
        "skill_pack": _text(params.get("skill_pack")),
        "skill_version": _text(params.get("skill_version")),
        "project": _text(params.get("project")),
        "actor_subject": _text(params.get("actor_subject"), 200),
    }


def _filter_form(filters: dict[str, Any]) -> str:
    fields = (
        ("Навык", "skill_id", "treasury-payments"),
        ("Пакет", "skill_pack", "acme-core"),
        ("Версия", "skill_version", "0.16.0"),
        ("Агент", "agent", "claude, codex"),
        ("Проект", "project", "acme"),
        ("Пользователь", "actor_subject", "yandex:..."),
    )
    inputs = "".join(
        f'<label>{escape(label)}<input type="text" name="{name}" value="{escape(str(filters[name]))}" placeholder="{escape(placeholder)}"></label>'
        for label, name, placeholder in fields
    )
    options = "".join(
        f'<option value="{days}"{" selected" if days == filters["days"] else ""}>{label}</option>'
        for days, label in PERIODS
    )
    return f"""
    <form class="audit-filter-grid" method="get" action="/admin/telemetry/skills">
      <label>Период<select name="days">{options}</select></label>
      {inputs}
      <div class="audit-filter-actions">
        <button type="submit">Показать</button>
        <a class="button secondary" href="/admin/telemetry/skills">Сбросить</a>
      </div>
    </form>
    """


def _skill_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return empty_row(14, "За выбранный период запуски навыков не зафиксированы")
    return "".join(
        "<tr>"
        f'<td><strong>{escape(str(row.get("skill_id") or "—"))}</strong></td>'
        f'<td>{escape(str(row.get("skill_pack") or "—"))}</td>'
        f'<td>{escape(str(row.get("skill_version") or "—"))}</td>'
        f'<td>{escape(str(row.get("agent") or "—"))}</td>'
        f'<td>{escape(str(row.get("project") or "—"))}</td>'
        f'<td>{_number(row.get("started_count"))}</td>'
        f'<td>{_number(row.get("completed_count"))}</td>'
        f'<td>{_number(row.get("failed_count"))}</td>'
        f'<td>{_number(row.get("abandoned_count"))}</td>'
        f'<td>{_rate(row.get("success_rate"))}</td>'
        f'<td>{_number(row.get("active_users"))}</td>'
        f'<td>{_duration(row.get("p50_duration_ms"))}</td>'
        f'<td>{_duration(row.get("p95_duration_ms"))}</td>'
        f'<td style="white-space:nowrap">{escape(fmt_time(row.get("last_seen_at")))}</td>'
        "</tr>"
        for row in rows
    )


def _totals(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "started": sum(_int(row.get("started_count")) for row in rows),
        "completed": sum(_int(row.get("completed_count")) for row in rows),
        "failed": sum(_int(row.get("failed_count")) for row in rows),
        "abandoned": sum(_int(row.get("abandoned_count")) for row in rows),
        "running": sum(_int(row.get("running_count")) for row in rows),
    }
    terminal = int(totals["completed"]) + int(totals["failed"])
    totals["success_rate"] = round(100 * totals["completed"] / terminal, 1) if terminal else 0
    return totals


def _stat(label: str, value: int | float, description: str, *, bad: bool = False) -> str:
    badge = '<span class="status missing">требует внимания</span>' if bad else ""
    return f'<div class="stat"><div class="k">{escape(label)}</div><div class="v">{value}{badge}</div><div class="s">{escape(description)}</div></div>'


def _rate(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(str(value)):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _duration(value: object) -> str:
    try:
        milliseconds = max(0, float(str(value or 0)))
    except (TypeError, ValueError):
        return "—"
    if not milliseconds:
        return "—"
    seconds = milliseconds / 1000
    return f"{seconds:.1f} с" if seconds < 60 else f"{seconds / 60:.1f} мин"


def _number(value: object) -> str:
    return f"{_int(value):,}".replace(",", " ")


def _int(value: object) -> int:
    try:
        return int(str(value or 0))
    except (TypeError, ValueError):
        return 0


def _days(value: object) -> int:
    try:
        days = int(str(value or "30"))
    except ValueError:
        return 30
    return days if days in {1, 7, 30, 90, 365} else 30


def _text(value: object, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _error_banner(message: str) -> str:
    if not message:
        return ""
    return f'<div class="banner error">Не удалось прочитать метрики: {escape(message)}</div>'

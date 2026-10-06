from html import escape
from typing import Any

from gateway_mcp.services.policy import GatewayActor, has_scope


def fmt_time(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) >= 16 and raw[4] == "-" and raw[7] == "-":
        return f"{raw[8:10]}.{raw[5:7]} {raw[11:16]}"
    return raw or "—"


def empty_row(columns: int, text: str = "Нет данных") -> str:
    return f'<tr><td colspan="{columns}"><div class="empty-note">{escape(text)}</div></td></tr>'


def admin_shell(
    *,
    title: str,
    active: str,
    actor: GatewayActor,
    body: str,
    shell_width: str = "1120px",
    extra_head: str = "",
) -> str:
    is_admin = has_scope(actor, "access:admin")
    nav = _navigation(active=active, is_admin=is_admin)
    home_url = "/admin" if is_admin else "/notifications"
    return f"""
    <!doctype html>
    <html lang="ru">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{escape(title)} · Comind AI Native Auth</title>
      <style>
        /* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4
         * genre: modern-minimal · theme: coMind workbench · macrostructure: operational dashboard
         */
        :root {{
          color-scheme: light;
          --color-canvas: oklch(97.8% 0.003 280);
          --color-surface: oklch(100% 0 0);
          --color-surface-muted: oklch(96.6% 0.004 280);
          --color-sidebar: oklch(20% 0.012 280);
          --color-sidebar-hover: oklch(27% 0.017 280);
          --color-sidebar-active: oklch(31% 0.035 290);
          --color-sidebar-muted: oklch(77% 0.01 280);
          --color-ink: oklch(19% 0.013 280);
          --color-ink-soft: oklch(39% 0.012 280);
          --color-muted: oklch(52% 0.01 280);
          --color-border: oklch(91% 0.006 280);
          --color-border-strong: oklch(82% 0.011 280);
          --color-accent: oklch(54% 0.24 295);
          --color-accent-ink: oklch(100% 0 0);
          --color-accent-hover: oklch(47% 0.23 295);
          --color-accent-soft: oklch(95% 0.025 295);
          --color-focus: oklch(54% 0.24 295);
          --color-focus-on-dark: oklch(79% 0.13 295);
          --color-success: oklch(43% 0.12 160);
          --color-success-soft: oklch(96% 0.028 160);
          --color-danger: oklch(48% 0.17 23);
          --color-danger-soft: oklch(97% 0.023 23);
          --color-warning: oklch(49% 0.11 70);
          --color-warning-soft: oklch(97% 0.035 83);
          --font-sans: Manrope, "Segoe UI Variable Text", "Segoe UI", ui-sans-serif, system-ui, sans-serif;
          --font-display: Manrope, "Segoe UI Variable Display", var(--font-sans);
          --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          --space-1: 4px;
          --space-2: 8px;
          --space-3: 12px;
          --space-4: 16px;
          --space-5: 20px;
          --space-6: 24px;
          --space-8: 32px;
          --space-10: 40px;
          --space-12: 48px;
          --radius-control: 6px;
          --radius-panel: 8px;
          --dur-micro: 120ms;
          --dur-short: 220ms;
          --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
          --z-sticky: 200;
          font-family: var(--font-sans);
          color: var(--color-ink);
          background: var(--color-canvas);
        }}
        * {{ box-sizing: border-box; }}
        [hidden] {{ display: none !important; }}
        html, body {{ min-width: 0; overflow-x: clip; }}
        body {{ margin: 0; background: var(--color-canvas); color: var(--color-ink); -webkit-font-smoothing: antialiased; }}
        a {{ color: var(--color-accent); }}
        a:focus-visible, summary:focus-visible {{ outline: 2px solid var(--color-focus); outline-offset: 3px; }}
        button, input, select {{ font: inherit; }}
        .app-shell {{ min-height: 100vh; display: grid; grid-template-columns: 228px minmax(0, 1fr); }}
        .sidebar {{
          position: sticky;
          top: 0;
          z-index: var(--z-sticky);
          height: 100vh;
          display: flex;
          flex-direction: column;
          padding: var(--space-8) var(--space-4) var(--space-5);
          background: var(--color-sidebar);
          color: var(--color-surface);
        }}
        .sidebar-top {{ display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }}
        .brand {{ display: grid; gap: 1px; padding: 0 var(--space-3); color: var(--color-surface); text-decoration: none; }}
        .brand-name {{ font-family: var(--font-display); font-size: 21px; font-weight: 750; line-height: 1.2; }}
        .brand-product {{ color: var(--color-sidebar-muted); font-size: 11px; }}
        .nav {{ display: grid; gap: var(--space-6); margin-top: var(--space-10); }}
        .desktop-nav {{ overflow-y: auto; min-height: 0; padding-bottom: var(--space-5); }}
        .sidebar-top, .identity {{ flex-shrink: 0; }}
        .nav-group {{ display: grid; gap: var(--space-1); }}
        .nav-label {{ padding: 0 var(--space-3) var(--space-1); color: var(--color-sidebar-muted); font-size: 10px; font-weight: 700; text-transform: uppercase; }}
        .nav-link {{
          display: flex;
          min-height: 36px;
          align-items: center;
          border-radius: var(--radius-control);
          color: var(--color-sidebar-muted);
          padding: 0 var(--space-3);
          font-size: 13px;
          text-decoration: none;
          transition: background var(--dur-micro) var(--ease-out), color var(--dur-micro) var(--ease-out);
        }}
        .nav-link:hover {{ background: var(--color-sidebar-hover); color: var(--color-surface); }}
        .nav-link:focus-visible {{ outline: 2px solid var(--color-focus-on-dark); outline-offset: 2px; }}
        .nav-link.active {{ background: var(--color-sidebar-active); color: var(--color-surface); font-weight: 650; box-shadow: inset 2px 0 var(--color-focus-on-dark); }}
        .mobile-menu {{ display: none; }}
        .identity {{ display: grid; gap: var(--space-1); margin-top: auto; padding: var(--space-4) var(--space-3) 0; border-top: 1px solid var(--color-sidebar-hover); }}
        .identity-label {{ color: var(--color-sidebar-muted); font-size: 11px; }}
        .identity-user {{ min-width: 0; overflow-wrap: anywhere; font-size: 12px; font-weight: 600; }}
        .mobile-identity {{ display: none; }}
        .workspace {{ min-width: 0; }}
        .content {{ max-width: {shell_width}; margin: 0 auto; padding: var(--space-10) var(--space-8) 64px; }}
        .stack {{ display: grid; gap: var(--space-6); }}
        .page-head, .panel-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-5); }}
        .page-head {{ padding-bottom: var(--space-2); }}
        h1, h2 {{ margin: 0; min-width: 0; overflow-wrap: anywhere; font-family: var(--font-display); letter-spacing: 0; }}
        h1 {{ font-size: 30px; line-height: 1.18; font-weight: 700; }}
        h2 {{ font-size: 18px; line-height: 1.3; font-weight: 650; }}
        p {{ line-height: 1.55; }}
        .lead {{ max-width: 760px; margin: var(--space-2) 0 0; color: var(--color-ink-soft); }}
        .muted, .description {{ color: var(--color-muted); }}
        .description {{ margin: var(--space-2) 0 0; }}
        .small {{ font-size: 13px; }}
        .panel, .stat, form.audit-filter-grid {{ background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-panel); }}
        .panel {{ padding: var(--space-6); }}
        .wide {{ overflow: hidden; }}
        .stat-grid {{ display: grid; grid-template-columns: repeat(5, minmax(140px, 1fr)); gap: var(--space-3); }}
        .stat {{ padding: var(--space-4); }}
        .stat .k {{ color: var(--color-muted); font-size: 12px; }}
        .stat .v {{ margin: var(--space-2) 0; font-size: 26px; font-weight: 650; }}
        .stat .s {{ color: var(--color-muted); font-size: 12px; }}
        .status {{ display: inline-flex; align-items: center; min-height: 24px; padding: 0 var(--space-2); border-radius: var(--radius-control); font-size: 12px; font-weight: 600; white-space: nowrap; }}
        .status.ok {{ background: var(--color-success-soft); color: var(--color-success); }}
        .status.neutral {{ background: var(--color-surface-muted); color: var(--color-muted); }}
        .status.missing {{ background: var(--color-danger-soft); color: var(--color-danger); }}
        .status.warning {{ background: var(--color-warning-soft); color: var(--color-warning); }}
        form {{ margin: 0; }}
        form.audit-filter-grid {{ padding: var(--space-5); display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: var(--space-4); }}
        label {{ display: grid; gap: var(--space-2); color: var(--color-ink-soft); font-size: 13px; font-weight: 600; }}
        input, select {{ width: 100%; min-height: 44px; padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-ink); }}
        input:hover, select:hover {{ border-color: var(--color-muted); }}
        input:focus-visible, select:focus-visible {{ border-color: var(--color-accent); outline: 2px solid var(--color-focus); outline-offset: 1px; }}
        input:disabled, select:disabled {{ background: var(--color-surface-muted); opacity: .55; cursor: not-allowed; }}
        input::placeholder {{ color: var(--color-muted); }}
        .audit-filter-actions {{ display: flex; gap: var(--space-2); align-items: end; }}
        button, .button {{
          display: inline-flex;
          min-height: 44px;
          align-items: center;
          justify-content: center;
          border: 1px solid transparent;
          border-radius: var(--radius-control);
          background: var(--color-accent);
          color: var(--color-accent-ink);
          padding: var(--space-2) var(--space-3);
          font: inherit;
          font-size: 14px;
          font-weight: 600;
          line-height: 1;
          text-decoration: none;
          white-space: nowrap;
          cursor: pointer;
          transition: background var(--dur-micro) var(--ease-out), border-color var(--dur-micro) var(--ease-out), color var(--dur-micro) var(--ease-out);
        }}
        button:hover, .button:hover {{ background: var(--color-accent-hover); }}
        button:active, .button:active {{ background: var(--color-accent-hover); }}
        button:focus-visible, .button:focus-visible {{ outline: 2px solid var(--color-focus); outline-offset: 2px; }}
        button:disabled, .button.disabled {{ opacity: .55; cursor: not-allowed; }}
        button.secondary, .button.secondary {{ border-color: var(--color-border-strong); background: var(--color-surface); color: var(--color-ink-soft); }}
        button.secondary:hover, .button.secondary:hover {{ border-color: var(--color-muted); background: var(--color-surface-muted); color: var(--color-ink); }}
        button.danger, .button.danger {{ border-color: var(--color-danger-soft); background: var(--color-surface); color: var(--color-danger); }}
        button.danger:hover, .button.danger:hover {{ border-color: var(--color-danger); background: var(--color-danger-soft); }}
        .table-wrap {{ overflow-x: auto; margin-top: var(--space-4); }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ padding: 12px 10px; border-bottom: 1px solid var(--color-border); text-align: left; vertical-align: top; }}
        th {{ color: var(--color-muted); font-size: 11px; font-weight: 650; text-transform: uppercase; }}
        tbody tr:last-child td {{ border-bottom: 0; }}
        code {{ font-family: var(--font-mono); font-size: 12px; }}
        .table-sub {{ display: block; color: var(--color-muted); margin-top: var(--space-1); }}
        .audit-badges {{ display: flex; gap: var(--space-1); flex-wrap: wrap; }}
        .audit-pager {{ display: flex; align-items: center; justify-content: flex-end; gap: var(--space-3); margin-top: var(--space-4); }}
        .empty-note {{ padding: var(--space-6); color: var(--color-muted); text-align: center; }}
        .banner {{ padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-control); }}
        .banner.error, .errorbox {{ border-color: var(--color-danger); background: var(--color-danger-soft); color: var(--color-danger); }}
        .banner.ok, .okbox {{ border-color: var(--color-success); background: var(--color-success-soft); color: var(--color-success); }}
        @media (max-width: 1040px) {{ .stat-grid, form.audit-filter-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
        @media (max-width: 900px) {{
          .app-shell {{ display: block; }}
          .sidebar {{ position: relative; width: 100%; height: auto; padding: var(--space-3) var(--space-4); }}
          .brand {{ padding: 0; }}
          .desktop-nav, .identity {{ display: none; }}
          .mobile-menu {{ display: block; }}
          .mobile-menu summary {{ display: flex; align-items: center; gap: var(--space-2); min-height: 38px; padding: 0 var(--space-3); border: 1px solid var(--color-sidebar-hover); border-radius: var(--radius-control); color: var(--color-surface); font-size: 13px; cursor: pointer; list-style: none; }}
          .mobile-menu summary::-webkit-details-marker {{ display: none; }}
          .mobile-menu summary::after {{ content: ''; width: 6px; height: 6px; border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor; transform: rotate(45deg); margin-left: 3px; }}
          .mobile-menu[open] summary::after {{ transform: rotate(225deg); }}
          .mobile-menu .nav {{ position: absolute; top: 100%; left: 0; right: 0; z-index: var(--z-sticky); display: grid; gap: var(--space-5); max-height: min(72vh, 600px); overflow-y: auto; margin: 0; padding: var(--space-5) var(--space-4); background: var(--color-sidebar); box-shadow: 0 16px 24px color-mix(in oklch, var(--color-sidebar) 30%, transparent); }}
          .mobile-identity {{ display: grid; gap: var(--space-1); padding: var(--space-4) var(--space-3) 0; border-top: 1px solid var(--color-sidebar-hover); color: var(--color-sidebar-muted); font-size: 12px; overflow-wrap: anywhere; }}
          .content {{ padding-top: var(--space-8); }}
        }}
        @media (max-width: 560px) {{
          .content {{ padding: var(--space-6) var(--space-4) var(--space-10); }}
          .stack {{ gap: var(--space-5); }}
          .page-head {{ display: grid; grid-template-columns: minmax(0, 1fr); }}
          .page-head > button, .page-head > .button {{ width: 100%; }}
          h1 {{ font-size: 26px; }}
          .panel {{ padding: var(--space-5); }}
          .stat-grid, form.audit-filter-grid {{ grid-template-columns: minmax(0, 1fr); }}
          .audit-filter-actions {{ display: grid; grid-template-columns: minmax(0, 1fr); }}
          .audit-filter-actions > * {{ width: 100%; }}
        }}
        @media (prefers-reduced-motion: reduce) {{
          *, *::before, *::after {{ animation-duration: 150ms !important; transition-duration: 150ms !important; }}
        }}
      </style>
      {extra_head}
    </head>
    <body>
      <div class="app-shell">
        <aside class="sidebar">
          <div class="sidebar-top">
            <a class="brand" href="{home_url}"><span class="brand-name">coMind</span><span class="brand-product">AI Native Gateway</span></a>
            <details class="mobile-menu"><summary>Разделы</summary><nav class="nav" aria-label="Мобильная навигация">{nav}<div class="mobile-identity">Вы вошли как <strong>{escape(actor.display)}</strong></div></nav></details>
          </div>
          <nav class="nav desktop-nav" aria-label="Основная навигация">{nav}</nav>
          <div class="identity"><span class="identity-label">Текущая учётная запись</span><span class="identity-user">{escape(actor.display)}</span></div>
        </aside>
        <div class="workspace"><main class="content"><div class="stack">{body}</div></main></div>
      </div>
    </body>
    </html>
    """


def _navigation(*, active: str, is_admin: bool) -> str:
    groups = []
    if is_admin:
        groups.append(
            (
                "Метрики",
                (
                    ("overview", "Обзор", "/admin"),
                    ("showcase", "Использование AI", "/admin/showcase"),
                    ("people", "Люди и AI", "/admin/people"),
                    ("agents", "Автономные агенты", "/admin/agents"),
                    ("audit", "Журнал событий", "/admin/audit"),
                    ("telemetry", "Навыки", "/admin/telemetry/skills"),
                ),
            )
        )
        groups.append(
            (
                "Управление",
                (
                    ("access-requests", "Заявки на доступ", "/admin/access-requests"),
                    ("users", "Доступ пользователей", "/admin/users"),
                    ("metrics", "Состояние шлюза", "/admin/metrics"),
                    ("integrations", "Интеграции", "/admin/integrations"),
                    (
                        "factory-connections",
                        "GitLab для фабрики",
                        "/admin/factory/connections",
                    ),
                ),
            )
        )
    groups.append(
        (
            "Рабочее место",
            (
                ("my-skills", "Мои навыки", "/my/skills"),
                ("notifications", "Уведомления", "/notifications"),
                ("credentials", "Мои подключения", "/credentials"),
            ),
        )
    )
    return "".join(
        '<div class="nav-group">'
        f'<div class="nav-label">{escape(label)}</div>'
        + "".join(
            _nav_link(key, item_label, href, active) for key, item_label, href in items
        )
        + "</div>"
        for label, items in groups
    )


def _nav_link(key: str, label: str, href: str, active: str) -> str:
    selected = key == active
    current = ' aria-current="page"' if selected else ""
    return f'<a class="nav-link{" active" if selected else ""}" href="{href}"{current}>{escape(label)}</a>'

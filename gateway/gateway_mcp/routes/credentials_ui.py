from __future__ import annotations

from gateway_mcp.routes.admin_ui import admin_shell
from gateway_mcp.services.policy import GatewayActor

_CREDENTIALS_CSS = """
<style>
  .page-actions { display: flex; gap: var(--space-2); }
  .credential-note {
    display: flex;
    gap: var(--space-3);
    align-items: flex-start;
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-panel);
    background: var(--color-surface-muted);
    color: var(--color-ink-soft);
    font-size: 13px;
  }
  .credential-note-mark {
    flex: 0 0 auto;
    width: 8px;
    height: 8px;
    margin-top: 6px;
    border-radius: 999px;
    background: var(--color-success);
  }
  .credential-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-4);
  }
  .credential-card { display: flex; flex-direction: column; min-height: 290px; }
  .credential-card .panel-header { align-items: center; }
  .credential-card .description { min-height: 62px; }
  .credential-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: auto;
  }
  .credential-actions form { min-width: 0; }
  .credential-form {
    display: grid;
    gap: var(--space-3);
    margin-top: var(--space-5);
    padding-top: var(--space-5);
    border-top: 1px solid var(--color-border);
  }
  .credential-form-hint { margin: 0; color: var(--color-muted); font-size: 13px; }
  .updated { margin: var(--space-1) 0 0; color: var(--color-muted); font-size: 12px; }
  .okbox, .errorbox { padding: 13px 15px; border: 1px solid; border-radius: var(--radius-control); font-size: 13px; }
  .wide { grid-column: 1 / -1; }
  .service-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
  .service-bind-form { display: flex; flex-wrap: wrap; gap: var(--space-2); }
  .compact-input { width: 190px; min-height: 38px; }
  .code-input { width: 140px; font-family: var(--font-mono); }
  button.compact { min-height: 38px; padding: 8px 12px; font-size: 13px; }
  @media (max-width: 760px) {
    .credential-grid { grid-template-columns: minmax(0, 1fr); }
    .credential-card { min-height: auto; }
    .credential-card .description { min-height: auto; }
    .wide { grid-column: auto; }
    .credential-actions { display: grid; grid-template-columns: minmax(0, 1fr); }
    .credential-actions button, .credential-actions form { width: 100%; }
    .service-bind-form { display: grid; grid-template-columns: minmax(0, 1fr); width: 100%; }
    .compact-input, .code-input, .service-bind-form button { width: 100%; }
  }
  @media (max-width: 560px) {
    .page-actions, .page-actions button { width: 100%; }
  }
</style>
"""


def render_credentials_page(
    *,
    actor: GatewayActor,
    banner: str,
    service_panel: str,
    yandex_connected: bool,
    yandex_state: str,
    yandex_disk_connected: bool,
    yandex_disk_state: str,
    yandex_disk_updated: str,
    google_connected: bool,
    google_state: str,
    google_updated: str,
    gitlab_connected: bool,
    gitlab_state: str,
    gitlab_updated: str,
    calendar_connected: bool,
    calendar_state: str,
    calendar_updated: str,
) -> str:
    body = f"""
    <div class="page-head">
      <div>
        <h1>Мои подключения</h1>
        <p class="lead">Личные доступы к корпоративным системам, которые GatewayMCP использует от вашего имени.</p>
      </div>
      <form class="page-actions" method="post" action="/auth/logout"><button class="secondary" type="submit">Выйти</button></form>
    </div>
    {banner}
    <div class="credential-note"><span class="credential-note-mark" aria-hidden="true"></span><span>Секреты хранятся зашифрованно. GatewayMCP не показывает их повторно и не передаёт агентам.</span></div>
    <div class="credential-grid">
      {_oauth_card(yandex_connected, yandex_state)}
      {_google_card(google_connected, google_state, google_updated)}
      {_disk_card(yandex_disk_connected, yandex_disk_state, yandex_disk_updated)}
      {_gitlab_card(gitlab_connected, gitlab_state, gitlab_updated)}
      {_calendar_card(calendar_connected, calendar_state, calendar_updated)}
      {service_panel}
    </div>
    """
    return admin_shell(
        title="Мои подключения",
        active="credentials",
        actor=actor,
        body=body,
        shell_width="1180px",
        extra_head=_CREDENTIALS_CSS,
    )


def _state(connected: bool, label: str) -> str:
    return f'<span class="status {"ok" if connected else "neutral"}">{label}</span>'


def _updated(value: str) -> str:
    return f'<p class="updated">Обновлено: {value}</p>' if value else ""


def _oauth_card(connected: bool, label: str) -> str:
    return f"""
    <section class="panel credential-card">
      <div class="panel-header"><h2>Yandex OAuth</h2>{_state(connected, label)}</div>
      <p class="description">Авторизация для Yandex Tracker и почтовых маршрутов. Диск подключается отдельно.</p>
      <div class="credential-actions">
        <form method="get" action="/credentials/check/yandex"><button class="secondary" type="submit">Проверить Yandex OAuth</button></form>
        <form method="get" action="/credentials/check/tracker"><button class="secondary" type="submit">Проверить Tracker</button></form>
        <form method="get" action="/credentials/check/mail"><button class="secondary" type="submit">Проверить почту</button></form>
      </div>
    </section>
    """


def _disk_card(connected: bool, label: str, updated: str) -> str:
    return f"""
    <section class="panel credential-card">
      <div class="panel-header"><div><h2>Yandex Disk</h2>{_updated(updated)}</div>{_state(connected, label)}</div>
      <p class="description">Отдельный OAuth-доступ к файлам и общим папкам Яндекс.Диска.</p>
      <div class="credential-actions">
        <form method="get" action="/auth/yandex/disk-login"><input type="hidden" name="manual" value="1"><button type="submit">Получить код Yandex Disk</button></form>
        <form method="get" action="/credentials/check/yandex-disk"><button class="secondary" type="submit">Проверить Yandex Disk</button></form>
        <form method="post" action="/credentials/yandex-disk/delete" onsubmit="return confirm('Удалить сохранённый токен Диска?')"><button class="danger" type="submit">Удалить Disk токен</button></form>
      </div>
      <form class="credential-form" method="post" action="/credentials/yandex-disk/manual">
        <p class="credential-form-hint">После разрешения доступа вставьте код подтверждения Яндекса.</p>
        <label for="yandex_disk_code">Код подтверждения<input id="yandex_disk_code" name="code" autocomplete="one-time-code" required></label>
        <div><button type="submit">Сохранить Yandex Disk</button></div>
      </form>
    </section>
    """


def _google_card(connected: bool, label: str, updated: str) -> str:
    return f"""
    <section class="panel credential-card">
      <div class="panel-header"><div><h2>Google Drive и Sheets</h2>{_updated(updated)}</div>{_state(connected, label)}</div>
      <p class="description">Личный OAuth-доступ к документам и таблицам Google.</p>
      <div class="credential-actions">
        <form method="get" action="/auth/google/login"><button type="submit">Подключить Google</button></form>
        <form method="get" action="/credentials/check/google"><button class="secondary" type="submit">Проверить Google</button></form>
        <form method="post" action="/credentials/google/delete" onsubmit="return confirm('Удалить сохранённый токен Google?')"><button class="danger" type="submit">Удалить Google токен</button></form>
      </div>
    </section>
    """


def _gitlab_card(connected: bool, label: str, updated: str) -> str:
    return f"""
    <section class="panel credential-card">
      <div class="panel-header"><div><h2>GitLab</h2>{_updated(updated)}</div>{_state(connected, label)}</div>
      <p class="description">Персональный токен: read_api для чтения, api для веток, коммитов и MR.</p>
      <div class="credential-actions">
        <form method="get" action="/credentials/check/gitlab"><button class="secondary" type="submit">Проверить GitLab</button></form>
        <form method="post" action="/credentials/gitlab/delete" onsubmit="return confirm('Удалить сохранённый токен GitLab?')"><button class="danger" type="submit">Удалить токен</button></form>
      </div>
      <form class="credential-form" method="post" action="/credentials/gitlab">
        <label for="gitlab_token">GitLab personal access token<input id="gitlab_token" name="gitlab_token" type="password" autocomplete="new-password" required></label>
        <div><button type="submit">Сохранить GitLab токен</button></div>
      </form>
    </section>
    """


def _calendar_card(connected: bool, label: str, updated: str) -> str:
    return f"""
    <section class="panel credential-card">
      <div class="panel-header"><div><h2>Yandex Calendar</h2>{_updated(updated)}</div>{_state(connected, label)}</div>
      <p class="description">Для CalDAV нужен отдельный пароль приложения из Yandex ID.</p>
      <div class="credential-actions">
        <form method="get" action="/credentials/check/calendar"><button class="secondary" type="submit">Проверить календарь</button></form>
        <form method="post" action="/credentials/calendar/delete" onsubmit="return confirm('Удалить сохранённый пароль календаря?')"><button class="danger" type="submit">Удалить пароль</button></form>
      </div>
      <form class="credential-form" method="post" action="/credentials/calendar">
        <label for="app_password">Пароль приложения<input id="app_password" name="app_password" type="password" autocomplete="new-password" required></label>
        <div><button type="submit">Сохранить пароль календаря</button></div>
      </form>
    </section>
    """

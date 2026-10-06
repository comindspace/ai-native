import json
from datetime import datetime
from html import escape
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from gateway_mcp.routes.admin_ui import admin_shell
from gateway_mcp.services.notifications import (
    acknowledge_all_notifications,
    acknowledge_notification,
    csrf_token,
    list_visible_notifications,
    push_enabled,
    push_public_key,
    register_push_subscription,
    topic_subscriptions,
    unregister_push_subscription,
    update_topic_subscription,
    verify_csrf,
)
from gateway_mcp.services.policy import GatewayActor, has_scope
from gateway_mcp.web import login_redirect, web_actor


def register_notification_routes(mcp):
    @mcp.custom_route("/notifications", methods=["GET"], include_in_schema=False)
    async def notifications_page(request: Request) -> Response:
        actor = web_actor(request)
        if actor is None:
            return login_redirect("/notifications")
        if not has_scope(actor, "notifications:read"):
            return HTMLResponse(
                "Недостаточно прав: notifications:read", status_code=403
            )
        data = list_visible_notifications(
            actor=actor,
            unread_only=False,
            event_type="",
            project_id="",
            limit=100,
        )
        return HTMLResponse(
            _page(
                actor=actor,
                notifications=data["notifications"],
                unread_count=data["unread_count"],
                csrf=csrf_token(actor),
                web_push_enabled=push_enabled(),
            )
        )

    @mcp.custom_route("/notifications/api", methods=["GET"], include_in_schema=False)
    async def notifications_api(request: Request) -> Response:
        actor, error = _api_actor(request)
        if error:
            return error
        unread_only = str(
            request.query_params.get("unread_only") or "false"
        ).casefold() in {
            "1",
            "true",
            "yes",
        }
        try:
            limit = int(request.query_params.get("limit") or 100)
            data = list_visible_notifications(
                actor=actor,
                unread_only=unread_only,
                event_type=str(request.query_params.get("event_type") or ""),
                project_id=str(request.query_params.get("project_id") or ""),
                limit=limit,
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        return JSONResponse({"ok": True, **data})

    @mcp.custom_route(
        "/notifications/{notification_id}/state",
        methods=["POST"],
        include_in_schema=False,
    )
    async def notification_state(request: Request) -> Response:
        actor, error = _api_actor(request)
        if error:
            return error
        payload = await _payload(request)
        if not verify_csrf(actor, _csrf_value(request, payload)):
            return JSONResponse({"ok": False, "error": "invalid_csrf"}, status_code=403)
        try:
            result = acknowledge_notification(
                actor=actor,
                notification_id=str(request.path_params.get("notification_id") or ""),
                state=str(payload.get("state") or "read"),
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        return JSONResponse({"ok": True, **result})

    @mcp.custom_route(
        "/notifications/read-all", methods=["POST"], include_in_schema=False
    )
    async def notifications_read_all(request: Request) -> Response:
        actor, error = _api_actor(request)
        if error:
            return error
        payload = await _payload(request)
        if not verify_csrf(actor, _csrf_value(request, payload)):
            return JSONResponse({"ok": False, "error": "invalid_csrf"}, status_code=403)
        count = acknowledge_all_notifications(actor)
        return JSONResponse({"ok": True, "updated": count})

    @mcp.custom_route(
        "/notifications/topics", methods=["POST"], include_in_schema=False
    )
    async def notification_topic(request: Request) -> Response:
        actor, error = _api_actor(request)
        if error:
            return error
        payload = await _payload(request)
        if not verify_csrf(actor, _csrf_value(request, payload)):
            return JSONResponse({"ok": False, "error": "invalid_csrf"}, status_code=403)
        try:
            topic = update_topic_subscription(
                actor=actor,
                topic_type=str(payload.get("topic_type") or "project"),
                topic_key=str(payload.get("topic_key") or ""),
                subscribed=bool(payload.get("subscribed", True)),
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except PermissionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        return JSONResponse(
            {
                "ok": True,
                "topic": topic,
                "subscriptions": topic_subscriptions(actor),
            }
        )

    @mcp.custom_route(
        "/notifications/push/public-key",
        methods=["GET"],
        include_in_schema=False,
    )
    async def notification_push_key(request: Request) -> Response:
        _actor, error = _api_actor(request)
        if error:
            return error
        key = push_public_key()
        if not key:
            return JSONResponse(
                {"ok": False, "error": "web_push_not_configured"},
                status_code=503,
            )
        return JSONResponse({"ok": True, "public_key": key})

    @mcp.custom_route(
        "/notifications/push/subscriptions",
        methods=["POST"],
        include_in_schema=False,
    )
    async def notification_push_subscribe(request: Request) -> Response:
        actor, error = _api_actor(request)
        if error:
            return error
        payload = await _payload(request)
        if not verify_csrf(actor, _csrf_value(request, payload)):
            return JSONResponse({"ok": False, "error": "invalid_csrf"}, status_code=403)
        try:
            subscription = register_push_subscription(
                actor=actor,
                subscription=payload.get("subscription") or {},
                user_agent=str(request.headers.get("user-agent") or ""),
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "subscription": subscription})

    @mcp.custom_route(
        "/notifications/push/subscriptions/delete",
        methods=["POST"],
        include_in_schema=False,
    )
    async def notification_push_unsubscribe(request: Request) -> Response:
        actor, error = _api_actor(request)
        if error:
            return error
        payload = await _payload(request)
        if not verify_csrf(actor, _csrf_value(request, payload)):
            return JSONResponse({"ok": False, "error": "invalid_csrf"}, status_code=403)
        removed = unregister_push_subscription(
            actor=actor,
            endpoint=str(payload.get("endpoint") or ""),
        )
        return JSONResponse({"ok": True, "removed": removed})

    @mcp.custom_route(
        "/notifications/manifest.webmanifest",
        methods=["GET"],
        include_in_schema=False,
    )
    async def notification_manifest(_: Request) -> Response:
        return Response(
            json.dumps(
                {
                    "name": "GatewayMCP Inbox",
                    "short_name": "AI Native Inbox",
                    "lang": "ru",
                    "start_url": "/notifications",
                    "scope": "/notifications",
                    "display": "standalone",
                    "background_color": "#f5f7fb",
                    "theme_color": "#172033",
                },
                ensure_ascii=False,
            ),
            media_type="application/manifest+json",
        )

    @mcp.custom_route("/notifications/sw.js", methods=["GET"], include_in_schema=False)
    async def notification_service_worker(_: Request) -> Response:
        return Response(
            _service_worker_script(),
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/notifications"},
        )


def _api_actor(request: Request) -> tuple[GatewayActor | None, Response | None]:
    actor = web_actor(request)
    if actor is None:
        return None, JSONResponse(
            {"ok": False, "error": "authentication_required"}, status_code=401
        )
    if not has_scope(actor, "notifications:read"):
        return None, JSONResponse(
            {"ok": False, "error": "missing_scope", "scope": "notifications:read"},
            status_code=403,
        )
    return actor, None


async def _payload(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except (AttributeError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        raw = await request.body()
        try:
            value = json.loads(raw.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            value = {}
    return value if isinstance(value, dict) else {}


def _csrf_value(request: Request, payload: dict[str, Any]) -> str:
    return str(request.headers.get("x-csrf-token") or payload.get("csrf") or "")


def _page(
    *,
    actor: GatewayActor,
    notifications: list[dict[str, Any]],
    unread_count: int,
    csrf: str,
    web_push_enabled: bool,
) -> str:
    rows = "".join(_notification_row(item) for item in notifications)
    if not rows:
        rows = '<div class="empty">Новых событий пока нет.</div>'
    push_label = "Включить" if web_push_enabled else "Недоступно"
    push_disabled = "" if web_push_enabled else " disabled"
    body = f"""
    <section class="page-head">
      <div>
        <div class="title-line"><h1>Уведомления</h1><span class="counter" id="unread-count">{unread_count}</span></div>
        <p class="lead">Результаты работы, запросы на действие и важные изменения.</p>
      </div>
      <button class="button secondary" id="read-all">Прочитать все</button>
    </section>
    <section class="panel push-settings">
      <div class="push-copy">
        <div class="panel-header-line">
          <h2>Системные уведомления</h2>
          <span class="status {"ok" if web_push_enabled else "missing"}">{"Доступны" if web_push_enabled else "Не настроены"}</span>
        </div>
        <p class="description">Получайте важные сообщения в браузере, даже когда эта страница закрыта.</p>
        <p class="status-line" id="status-line" aria-live="polite"></p>
      </div>
      <div class="push-actions">
        <button class="button secondary" id="push-test" hidden>Проверить</button>
        <button id="push-enable"{push_disabled}>{push_label}</button>
        <button class="button secondary" id="push-disable" hidden>Отключить</button>
      </div>
    </section>
    <section class="panel notification-list" id="notification-list">{rows}</section>
    <script>
      const csrf = {json.dumps(csrf)};
      const statusLine = document.getElementById('status-line');
      const setStatus = (text, kind = '') => {{ statusLine.textContent = text; statusLine.className = `status-line ${{kind}}`; }};
      async function post(url, payload = {{}}) {{
        const response = await fetch(url, {{
          method: 'POST', credentials: 'same-origin',
          headers: {{'Content-Type': 'application/json', 'X-CSRF-Token': csrf}},
          body: JSON.stringify(payload)
        }});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || 'request_failed');
        return data;
      }}
      document.querySelectorAll('[data-read]').forEach((button) => button.addEventListener('click', async () => {{
        await post(`/notifications/${{button.dataset.read}}/state`, {{state: 'read'}});
        button.closest('.notification').classList.add('read'); button.remove();
        const counter = document.getElementById('unread-count'); counter.textContent = Math.max(0, Number(counter.textContent) - 1);
      }}));
      document.getElementById('read-all').addEventListener('click', async () => {{
        await post('/notifications/read-all');
        document.querySelectorAll('.notification').forEach((row) => row.classList.add('read'));
        document.querySelectorAll('[data-read]').forEach((button) => button.remove());
        document.getElementById('unread-count').textContent = '0';
      }});
      function applicationServerKey(value) {{
        const padding = '='.repeat((4 - value.length % 4) % 4);
        const raw = atob((value + padding).replace(/-/g, '+').replace(/_/g, '/'));
        return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
      }}
      const pushEnable = document.getElementById('push-enable');
      const pushDisable = document.getElementById('push-disable');
      const pushTest = document.getElementById('push-test');
      const showPushState = (enabled) => {{
        pushEnable.hidden = enabled;
        pushDisable.hidden = !enabled;
        pushTest.hidden = !enabled;
      }};
      async function pushRegistration() {{
        return navigator.serviceWorker.register('/notifications/sw.js', {{scope: '/notifications'}});
      }}
      async function refreshPushState() {{
        if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {{
          pushEnable.disabled = true;
          pushEnable.textContent = 'Не поддерживаются';
          setStatus('Этот браузер не поддерживает системные уведомления.');
          return;
        }}
        if (Notification.permission === 'denied') {{
          pushEnable.disabled = true;
          pushEnable.textContent = 'Заблокированы';
          setStatus('Разрешите уведомления для этого сайта в настройках браузера.');
          return;
        }}
        if (pushEnable.disabled) return;
        try {{
          const registration = await pushRegistration();
          const subscription = await registration.pushManager.getSubscription();
          showPushState(Boolean(subscription));
          if (subscription) setStatus('Включены на этом устройстве.', 'success');
        }} catch (_) {{
          setStatus('Не удалось проверить состояние уведомлений.');
        }}
      }}
      refreshPushState();
      pushEnable.addEventListener('click', async () => {{
        try {{
          const permission = await Notification.requestPermission();
          if (permission !== 'granted') throw new Error('Разрешение на уведомления не выдано.');
          const registration = await pushRegistration();
          const keyResponse = await fetch('/notifications/push/public-key', {{credentials: 'same-origin'}});
          const keyData = await keyResponse.json();
          if (!keyResponse.ok) throw new Error('Системные уведомления пока не настроены на сервере.');
          let subscription = await registration.pushManager.getSubscription();
          if (!subscription) subscription = await registration.pushManager.subscribe({{userVisibleOnly: true, applicationServerKey: applicationServerKey(keyData.public_key)}});
          await post('/notifications/push/subscriptions', {{subscription: subscription.toJSON()}});
          showPushState(true);
          setStatus('Включены на этом устройстве.', 'success');
        }} catch (error) {{ setStatus(error.message || 'Не удалось включить уведомления.', 'error'); }}
      }});
      pushDisable.addEventListener('click', async () => {{
        try {{
          const registration = await pushRegistration();
          const subscription = await registration.pushManager.getSubscription();
          if (subscription) {{
            await post('/notifications/push/subscriptions/delete', {{endpoint: subscription.endpoint}});
            await subscription.unsubscribe();
          }}
          showPushState(false);
          setStatus('Отключены на этом устройстве.');
        }} catch (error) {{ setStatus(error.message || 'Не удалось отключить уведомления.', 'error'); }}
      }});
      pushTest.addEventListener('click', async () => {{
        try {{
          if (Notification.permission !== 'granted') throw new Error('Разрешение на уведомления не выдано.');
          const registration = await pushRegistration();
          await registration.showNotification('GatewayMCP', {{
            body: 'Локальная проверка системных уведомлений.',
            tag: `local-test-${{Date.now()}}`,
            data: {{url: '/notifications'}},
          }});
          setStatus('Проверочное уведомление передано браузеру.', 'success');
        }} catch (error) {{ setStatus(error.message || 'Не удалось показать уведомление.', 'error'); }}
      }});
    </script>
    """
    extra_head = """
    <meta name="theme-color" content="#172033">
    <link rel="manifest" href="/notifications/manifest.webmanifest">
    <style>
    button:disabled { opacity: .52; cursor: default; }
    .title-line { display: flex; align-items: center; gap: 10px; }
    .counter { display: inline-flex; min-width: 24px; height: 24px; align-items: center; justify-content: center; border-radius: 999px; background: var(--color-danger); color: var(--color-accent-ink); font-size: 13px; font-weight: 600; }
    .push-settings { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
    .push-copy { min-width: 0; }
    .panel-header-line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .push-settings .description { margin: 8px 0 0; }
    .push-actions { display: flex; gap: 8px; flex: 0 0 auto; }
    .status-line { min-height: 18px; margin: var(--space-2) 0 0; color: var(--color-muted); font-size: 13px; }
    .status-line.success { color: var(--color-success); } .status-line.error { color: var(--color-danger); }
    .notification-list { max-height: clamp(360px, 58vh, 720px); padding: 0; overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
    .notification { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; gap: var(--space-4); padding: var(--space-5) var(--space-6); border-bottom: 1px solid var(--color-border); }
    .notification:last-child { border-bottom: 0; }
    .notification.read { background: var(--color-surface-muted); }
    .marker { width: 8px; height: 8px; margin-top: var(--space-2); border-radius: 999px; background: var(--color-accent); }
    .read .marker { background: var(--color-border-strong); }
    .notification > div { min-width: 0; }
    .notification h2 { margin: 0; font-size: 17px; letter-spacing: 0; overflow-wrap: anywhere; }
    .meta { display: flex; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-2); color: var(--color-muted); font-size: 13px; }
    .body { margin: var(--space-2) 0 0; color: var(--color-ink-soft); line-height: 1.55; white-space: pre-line; }
    .notification-actions { display: flex; align-items: center; gap: 8px; }
    .notification-actions button, .notification-actions .button { padding: 8px 10px; font-size: 13px; }
    .priority-high, .priority-urgent { color: var(--color-danger); font-weight: 650; }
    .empty { padding: var(--space-12) var(--space-6); text-align: center; color: var(--color-muted); }
    @media (max-width: 720px) {
      .push-settings { align-items: flex-start; }
      .page-head, .notification, .push-settings { grid-template-columns: minmax(0, 1fr); display: grid; }
      .page-head > button, .push-actions, .push-actions button { width: 100%; }
      .notification-actions { margin-left: var(--space-6); }
      .meta span { overflow-wrap: anywhere; }
    }
    @media (max-width: 480px) {
      .notification-list { max-height: 68vh; }
      .notification { padding: var(--space-4); }
      .notification-actions { margin-left: var(--space-6); flex-wrap: wrap; }
    }
    </style>
    """
    return admin_shell(
        title="Уведомления",
        active="notifications",
        actor=actor,
        body=body,
        shell_width="960px",
        extra_head=extra_head,
    )


def _notification_row(item: dict[str, Any]) -> str:
    notification_id = escape(str(item.get("notification_id") or ""))
    title = escape(str(item.get("title") or ""))
    body = escape(str(item.get("body") or ""))
    event_type = escape(str(item.get("event_type") or ""))
    priority = escape(str(item.get("priority") or "normal"))
    project = escape(str(item.get("project_id") or ""))
    created_by = escape(str(item.get("created_by") or ""))
    created = escape(_format_time(item.get("created_at")))
    read = bool(item.get("read_at"))
    action_url = escape(str(item.get("action_url") or ""), quote=True)
    action = f'<a class="button" href="{action_url}">Открыть</a>' if action_url else ""
    read_button = (
        ""
        if read
        else f'<button class="secondary" data-read="{notification_id}">Прочитано</button>'
    )
    project_meta = f"<span>{project}</span>" if project else ""
    sender_meta = f"<span>от {created_by}</span>" if created_by else ""
    return f"""
    <article class="notification{" read" if read else ""}">
      <span class="marker"></span>
      <div><h2>{title}</h2><div class="meta"><span>{event_type}</span>{project_meta}{sender_meta}<span class="priority-{priority}">{priority}</span><span>{created}</span></div>{f'<p class="body">{body}</p>' if body else ""}</div>
      <div class="notification-actions">{action}{read_button}</div>
    </article>
    """


def _format_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    raw = str(value or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime(
            "%d.%m.%Y %H:%M"
        )
    except ValueError:
        return raw


def _service_worker_script() -> str:
    return """
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { data = {}; }
  const title = data.title || 'GatewayMCP';
  const options = {
    body: data.body || '',
    tag: data.tag || data.notification_id || data.event_type || 'gateway-notification',
    renotify: data.priority === 'urgent',
    data: {url: data.url || '/notifications'},
  };
  event.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = event.notification.data?.url || '/notifications';
  event.waitUntil(clients.matchAll({type: 'window', includeUncontrolled: true}).then((windows) => {
    for (const client of windows) {
      if ('focus' in client && client.url.includes('/notifications')) {
        client.navigate(target); return client.focus();
      }
    }
    return clients.openWindow ? clients.openWindow(target) : undefined;
  }));
});
""".strip()

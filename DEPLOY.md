# Развёртывание AI-Native

Этот репозиторий — полная поставка AI-Native: MCP-шлюз GatewayMCP (каталог `gateway/`), скиллы для ассистентов (`skills/`) и сборщик пакетов (`agent-platform/`). Один репозиторий, одна команда установки, один MCP-адрес для всех клиентов.

| Компонент | Что это |
|---|---|
| GatewayMCP (`gateway/`) | MCP-шлюз между агентами и корпоративными системами: вход через Яндекс, доступы, аудит, память |
| Скиллы (`skills/`) | Переносимые навыки агентов: контракт, справочный набор coMind |
| Сборщик (`agent-platform/`) | Превращает `skills/` в устанавливаемые пакеты для Claude Code, Codex, Cursor, OpenCode, OpenClaw, Hermes и ZCode |
| `bootstrap.sh` | Установщик: чистая VM с Ubuntu или Debian превращается в работающий шлюз с HTTPS одной командой |

## 1. Требования к серверу

- Linux x86_64: Ubuntu 22.04 и новее либо Debian 12 и новее.
- 2 vCPU, 4 ГБ RAM, 25 ГБ на диске, публичный IPv4.
- Открытые порты 80 и 443; порт 8000 наружу не открывать.
- Домен с A-записью на сервер. Если домена нет, установщик по умолчанию использует технический адрес вида `<ip>.sslip.io`; для постоянной работы заведите собственный домен.

## 2. Приложение Яндекса для входа

Шлюз использует Яндекс как стандартный провайдер входа. Зарегистрируйте OAuth-приложение на [oauth.yandex.ru](https://oauth.yandex.ru) от имени аккаунта компании:

- платформа: «Веб-сервисы»;
- Redirect URI: `https://<домен>/auth/yandex/callback`;
- права (Яндекс ID): `login:email`, `login:info`.

Сохраните ClientID и ClientSecret. Приложение Яндекс Диска, если диск понадобится позже, создают отдельно: у Яндекса есть ограничение на число прав одного приложения.

## 3. Установка одной командой

На чистой VM (git и Docker заранее не нужны — скрипт поставит сам):

```bash
curl -fsSL https://raw.githubusercontent.com/comindspace/ai-native/main/bootstrap.sh -o bootstrap.sh
sudo bash bootstrap.sh
```

Важно: скрипт скачивается в файл и запускается файлом. Вариант `curl ... | sudo bash` не работает: дочерние процессы (apt, docker compose) читают общий stdin и съедают остаток скрипта из канала, установка тихо обрывается.

Скрипт установит Docker, Docker Compose, Caddy и git, склонирует репозиторий в `/opt/ai-native`, определит публичный IP, предложит домен `<ip>.sslip.io` или возьмёт ваш (`--domain`), спросит email владельца и данные OAuth-приложения (ввод скрыт, секреты не печатаются), сгенерирует остальные секреты, запишет `gateway/.env`, назначит первого администратора, соберёт и запустит PostgreSQL, шлюз и воркер уведомлений, проверит `/healthz`, выпустит HTTPS-сертификат и напечатает готовый MCP URL.

Для собственного форка: `sudo bash bootstrap.sh --repo https://github.com/<ORG>/ai-native.git`.

Без интерактивных вопросов:

```bash
sudo bash bootstrap.sh --domain mcp.example.ru --email owner@example.ru \
  --oauth-id <ClientID> --oauth-secret <ClientSecret> --yes
```

Диагностика работающей установки:

```bash
sudo bash bootstrap.sh --doctor
```

Повторный запуск на установленной системе не перезаписывает `.env` и секреты: скрипт предложит диагностику. Ручная установка без скрипта — в разделе 5.

## 4. Первый вход

- Вход: `https://<домен>/auth/yandex/login` под аккаунтом владельца, указанным при установке. Этот аккаунт уже назначен администратором.
- Админка: `https://<домен>/admin`. Роли коллегам раздают в веб-интерфейсе.
- MCP-эндпоинт: `https://<домен>/mcp`.

Проверка безопасности после установки:

```bash
curl -fsS https://<домен>/healthz        # "ok": true и "auth_enabled": true
curl -m 5 http://<публичный-ip>:8000/healthz   # должен завершиться ошибкой: порт закрыт
```

## 5. Ручная установка (справка)

Те же шаги, что выполняет `bootstrap.sh`, вручную.

**5.1. Зависимости.**

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl docker.io docker-compose-v2 caddy
sudo systemctl enable --now docker caddy
```

**5.2. Конфигурация.** Скопируйте шаблон и заполните значения: `cp gateway/deploy.env.example gateway/.env`. Обязательный минимум:

| Переменная | Значение |
|---|---|
| `GATEWAY_AUTH_ENABLED` | `true`. Публичный шлюз без авторизации недопустим |
| `GATEWAY_PUBLIC_URL`, `GATEWAY_ISSUER_URL` | `https://<домен>` |
| `GATEWAY_RESOURCE_URL` | `https://<домен>/mcp` |
| `GATEWAY_ALLOWED_EMAIL_DOMAINS` | почтовый домен компании. Пустое значение пускает любые аккаунты Яндекса — не оставляйте пустым |
| `GATEWAY_PORT` | `127.0.0.1:8000` — шлюз слушает только localhost, наружу ведёт HTTPS-прокси |
| `POSTGRES_PASSWORD` | `openssl rand -hex 16` |
| `GATEWAY_JWT_SECRET` | `openssl rand -hex 32` |
| `GATEWAY_USER_TOKEN_ENCRYPTION_KEY` | ключ Fernet, не произвольная строка: `docker compose run --rm --no-deps gateway python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Пустое значение тоже валидно: ключ выведется из `GATEWAY_JWT_SECRET`, но тогда ротация JWT-секрета потребует перевыпуска всех пользовательских токенов |
| `YANDEX_OAUTH_CLIENT_ID`, `YANDEX_OAUTH_CLIENT_SECRET` | из раздела 2 |
| `YANDEX_OAUTH_SCOPES` | `login:email login:info` |

Файл `.env` содержит секреты: права 600, не коммитить.

**5.3. Первый администратор.** В `gateway/gateway-policy.json` впишите email владельца:

```json
"users": {
  "owner@example.ru": { "groups": ["admins"] }
}
```

Этот пользователь получит права администратора при первом входе. Дальше роли раздают в `/admin`, а запись из файла политик можно убрать. Изменение применяется при следующем входе, перезапуск не нужен.

**5.4. Запуск.**

```bash
cd gateway
sudo docker compose up -d --build
curl -fsS http://127.0.0.1:8000/healthz   # "ok": true
```

Миграции базы применяются автоматически при старте контейнера.

**5.5. HTTPS.** Caddy получает сертификаты сам:

```text
# /etc/caddy/Caddyfile
<домен> {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Для nginx: `proxy_pass http://127.0.0.1:8000` с `proxy_http_version 1.1`, `proxy_buffering off` (важно для стримингового `/mcp`) и `proxy_read_timeout 300s`; сертификат — certbot или свой.

## 6. Контрольный список приёмки

1. `curl https://<домен>/healthz` возвращает `"ok": true` и `"auth_enabled": true`.
2. `http://<публичный-ip>:8000/healthz` извне недоступен.
3. Вход через `https://<домен>/auth/yandex/login` проходит под адресом из разрешённого домена; посторонний адрес отклоняется.
4. Администратору открывается `https://<домен>/admin`.
5. Агент подключается к `https://<домен>/mcp`, проходит OAuth и видит маршруты через `gateway_search_tools`.

## 7. Подключение агентов

Шлюз работает с любым MCP-клиентом. Сервер: `https://<домен>/mcp`, аутентификация — Яндекс (MCP OAuth; не вставляйте bearer-токен вручную, если клиент умеет OAuth).

- **ZCode**: Settings → MCP → добавить сервер с этим URL, войти по Яндексу.
- **Claude Code**: команда `/mcp`, выбрать сервер, войти по Яндексу.
- **Cursor**: настройки MCP → добавить Streamable HTTP сервер.

Скиллы устанавливаются пакетами из этого же репозитория. Маркетплейсы в корне:

- Claude Code: `.claude-plugin/marketplace.json`;
- Cursor: `.cursor-plugin/marketplace.json`;
- Codex: `.agents/plugins/marketplace.json`;
- ZCode: `.zcode-plugin/marketplace.json`.

Например, для Claude Code: `/plugin marketplace add <путь-к-клону>`, затем установить пак `ai-native-core`. Свои скиллы добавляйте в `skills/` и пересобирайте паки (`README.md`, раздел Build tool).

## 8. Обновление

```bash
git pull
cd gateway
sudo docker compose up -d --build
```

Миграции применятся автоматически. Перед обновлением сделайте резервную копию базы. Никогда не выполняйте `docker compose down -v`: флаг `-v` удалит том PostgreSQL.

## 9. Если что-то не работает

- Диагностика одной командой: `sudo bash bootstrap.sh --doctor`.
- Логи шлюза: `cd gateway && docker compose logs --tail=100 gateway`.
- Caddy: `systemctl status caddy`, `journalctl -u caddy -n 100`.
- Вход циклически редиректит: проверьте, что `GATEWAY_PUBLIC_URL` совпадает с доменом из Redirect URI приложения Яндекса.
- Сертификат не выпускается для `<ip>.sslip.io`: у Let's Encrypt бывают лимиты на sslip.io, используйте собственный домен.
- Перед отправкой логов кому-либо исключите токены, cookie, OAuth-коды и персональные данные.

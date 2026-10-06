#!/usr/bin/env bash
# ai-native bootstrap: from a clean Ubuntu/Debian VM to a running GatewayMCP with HTTPS.
#
# Interactive (one command from the cloned repository):
#   sudo bash bootstrap.sh
# Unattended:
#   sudo bash bootstrap.sh --domain mcp.example.ru --email owner@example.ru \
#     --oauth-id <id> --oauth-secret <secret> --yes
# Diagnostics of an existing install:
#   sudo bash bootstrap.sh --doctor
#
# Steps: Docker + Compose + Caddy; clone (or reuse) the repository; public IP ->
# <ip>.sslip.io domain; secrets; gateway/.env; first admin in gateway-policy.json;
# PostgreSQL + Gateway + worker up; auth check on /healthz; HTTPS via Caddy;
# TCP 8000 stays closed; prints the MCP URL. Never prints or overwrites secrets.
#
# Run from a file, never from a pipe: children like `docker compose build` read
# stdin and would silently swallow the rest of a piped script.
#   curl -fsSL <repo>/bootstrap.sh -o bootstrap.sh && sudo bash bootstrap.sh
set -Eeuo pipefail

# ---------------------------------------------------------------- defaults ---

REPO_URL="${BOOTSTRAP_REPO:-https://github.com/comindspace/ai-native.git}"
BRANCH="${BOOTSTRAP_BRANCH:-main}"
INSTALL_DIR="/opt/ai-native"
DOMAIN="${DOMAIN:-}"
OWNER_EMAIL="${OWNER_EMAIL:-}"
OAUTH_ID="${YANDEX_OAUTH_CLIENT_ID:-}"
OAUTH_SECRET="${YANDEX_OAUTH_CLIENT_SECRET:-}"
ALLOWED_DOMAINS="${GATEWAY_ALLOWED_EMAIL_DOMAINS:-}"
ASSUME_YES=0
MODE="install"

GATEWAY_DIR=""    # <install>/gateway, set once the clone is located
PUBLIC_IP=""

# ----------------------------------------------------------------- helpers ---

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[X]\033[0m %s\n' "$*" >&2; exit 1; }

on_error() {
    local code=$?
    warn "Шаг упал (код $code). Диагностика:"
    warn "  journalctl -u caddy --no-pager -n 50"
    warn "  cd ${GATEWAY_DIR:-${INSTALL_DIR}/gateway} && docker compose logs --tail=80 gateway"
    warn "Секреты не печатаются. Исправь причину и запусти bootstrap.sh снова."
    exit "$code"
}
trap on_error ERR

usage() {
    cat <<'EOF'
ai-native bootstrap: чистая Ubuntu/Debian VM -> работающий GatewayMCP с HTTPS.

Запуск (скачай файл и запускай файлом, не через curl | bash):
  curl -fsSL https://raw.githubusercontent.com/comindspace/ai-native/main/bootstrap.sh -o bootstrap.sh
  sudo bash bootstrap.sh

Опции:
  [--doctor] [--repo URL] [--branch BRANCH] [--dir PATH]
  [--domain DOMAIN] [--email EMAIL] [--oauth-id ID]
  [--oauth-secret SECRET] [--allowed-domains LIST] [--yes]

Опции:
  --doctor                 только диагностика существующей установки
  --repo URL               репозиторий для клонирования (по умолчанию
                           https://github.com/comindspace/ai-native.git;
                           для форка: https://github.com/<ORG>/ai-native.git)
  --branch BRANCH          ветка (по умолчанию main)
  --dir PATH               каталог установки (по умолчанию /opt/ai-native)
  --domain DOMAIN          домен с A-записью на эту VM (по умолчанию <ip>.sslip.io)
  --email EMAIL            Yandex-почта владельца, становится первым администратором
  --oauth-id ID            Yandex OAuth ClientID
  --oauth-secret SECRET    Yandex OAuth ClientSecret (вводится скрыто)
  --allowed-domains LIST   домены входа через запятую (по умолчанию домен владельца)
  --yes                    без интерактивных вопросов (все значения заданы)

Переменные окружения: BOOTSTRAP_REPO, BOOTSTRAP_BRANCH, INSTALL_DIR, DOMAIN,
OWNER_EMAIL, YANDEX_OAUTH_CLIENT_ID, YANDEX_OAUTH_CLIENT_SECRET,
GATEWAY_ALLOWED_EMAIL_DOMAINS.

Перед запуском создай OAuth-приложение Яндекса (https://oauth.yandex.ru,
платформа «Веб-сервисы», Redirect URI https://<домен>/auth/yandex/callback,
права Яндекс ID: login:email, login:info). Подробности: DEPLOY.md.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --doctor) MODE="doctor"; shift ;;
        --repo) REPO_URL="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        --domain) DOMAIN="$2"; shift 2 ;;
        --email) OWNER_EMAIL="$2"; shift 2 ;;
        --oauth-id) OAUTH_ID="$2"; shift 2 ;;
        --oauth-secret) OAUTH_SECRET="$2"; shift 2 ;;
        --allowed-domains) ALLOWED_DOMAINS="$2"; shift 2 ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "неизвестная опция: $1 (см. --help)" ;;
    esac
done

[ "$(id -u)" -eq 0 ] || die "запусти от root: sudo bash bootstrap.sh"

# Refuse piped execution (`curl ... | bash`): apt/docker children consume stdin
# and would silently truncate this script mid-run with exit code 0.
# BASH_SOURCE is unset when bash reads the script from stdin.
if [ -p /dev/stdin ] && [ ! -f "${BASH_SOURCE[0]:-}" ]; then
    die "скрипт запущен из канала (curl | bash) — так нельзя: дочерние процессы
съедают скрипт из stdin. Скачай файл и запусти его:

  curl -fsSL https://raw.githubusercontent.com/comindspace/ai-native/main/bootstrap.sh -o bootstrap.sh
  sudo bash bootstrap.sh"
fi

have() { command -v "$1" >/dev/null 2>&1; }

# ------------------------------------------------------- system primitives ---

apt_supported() {
    have apt-get || die "apt-get не найден: поддерживаются Ubuntu/Debian."
    . /etc/os-release
    log "ОС: ${PRETTY_NAME:-unknown}"
}

ensure_compose_v2() {
    docker compose version >/dev/null 2>&1 && return 0
    warn "docker compose v2 нет в дистрибутиве — ставлю официальный плагин"
    local arch; case "$(dpkg --print-architecture)" in
        amd64) arch=x86_64 ;;
        arm64) arch=aarch64 ;;
        *) die "неподдерживаемая архитектура для compose-плагина" ;;
    esac
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${arch}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    docker compose version >/dev/null 2>&1
}

ensure_caddy() {
    have caddy && return 0
    warn "caddy нет в дистрибутиве — подключаю официальный репозиторий Caddy"
    apt-get install -y -q gnupg debian-keyring debian-archive-keyring apt-transport-https >/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y -q
    apt-get install -y -q caddy
    have caddy
}

install_packages() {
    log "Устанавливаю системные зависимости (Docker, Compose, Caddy)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y ca-certificates curl git openssl docker.io docker-compose-v2 \
        || apt-get install -y ca-certificates curl git openssl docker.io
    ensure_compose_v2 || die "docker compose v2 установить не удалось"
    apt-get install -y caddy || true
    ensure_caddy || die "caddy установить не удалось"
    systemctl enable --now docker
    systemctl enable --now caddy
    if ! docker version >/dev/null 2>&1; then
        # Reinstall-over-broken-state case: docker.service can come up without
        # its activation socket ("no sockets found via socket activation").
        warn "docker не поднялся с первого раза — перезапускаю docker.socket"
        systemctl restart docker.socket 2>/dev/null || true
        systemctl daemon-reload
        systemctl restart docker 2>/dev/null || true
        sleep 3
        docker version >/dev/null 2>&1 || die "docker не работает (systemctl status docker, journalctl -u docker)"
    fi
    if have ufw && ufw status 2>/dev/null | grep -q "Status: active"; then
        ufw allow 22/tcp >/dev/null
        ufw allow 80/tcp >/dev/null
        ufw allow 443/tcp >/dev/null
        info "ufw: открыты 22, 80, 443"
    fi
}

detect_public_ip() {
    local ip
    for url in https://api.ipify.org https://ifconfig.me https://ipinfo.io/ip; do
        ip="$(curl -fsS4 --max-time 10 "$url" 2>/dev/null || true)"
        ip="${ip%%[[:space:]]*}"
        if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            PUBLIC_IP="$ip"
            return 0
        fi
    done
    return 1
}

wait_http() {
    # wait_http <url> <max_seconds> <grep pattern>
    local url="$1" max="$2" pattern="$3" waited=0 body
    while [ "$waited" -lt "$max" ]; do
        body="$(curl -fsS --max-time 10 "$url" 2>/dev/null || true)"
        if [ -n "$body" ] && grep -q "$pattern" <<<"$body"; then
            return 0
        fi
        sleep 3
        waited=$((waited + 3))
    done
    return 1
}

healthz_check() {
    # healthz_check <url> -> 0 ok+auth, 1 reachable but auth off, 2 unreachable
    local body
    body="$(curl -fsS --max-time 10 "$1" 2>/dev/null || true)"
    [ -n "$body" ] || return 2
    grep -q '"ok": *true' <<<"$body" || return 2
    grep -q '"auth_enabled": *true' <<<"$body" || return 1
    return 0
}

# ------------------------------------------------------------ locate clone ---

locate_install_dir() {
    # Running from inside a repository clone with gateway/ -> reuse it.
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -d "${script_dir}/gateway" ] && [ -d "${script_dir}/.git" ]; then
        INSTALL_DIR="$script_dir"
        if [ -e "${INSTALL_DIR}/gateway/.env" ]; then
            die "${INSTALL_DIR}: установка уже есть (.env). Повторная установка перезаписала бы секреты
и отрезала бы шлюз от существующей базы. Диагностика: sudo bash ${INSTALL_DIR}/bootstrap.sh --doctor"
        fi
        log "Использую репозиторий, из которого запущен скрипт: ${INSTALL_DIR}"
    else
        if [ -e "${INSTALL_DIR}/gateway/.env" ]; then
            die "${INSTALL_DIR}: установка уже есть (.env). Диагностика: sudo bash bootstrap.sh --doctor"
        fi
        if [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
            die "${INSTALL_DIR} не пуст. Укажи --dir или очисти каталог."
        fi
        log "Клонирую ${REPO_URL} (ветка ${BRANCH}) в ${INSTALL_DIR}"
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    fi
    GATEWAY_DIR="${INSTALL_DIR}/gateway"
    [ -d "$GATEWAY_DIR" ] || die "в репозитории нет каталога gateway/ (ветка ${BRANCH}?)"
}

# ------------------------------------------------------------- user input ---

ask() {
    # ask <var> <prompt> [secret]; skipped in --yes mode
    local __var="$1" __prompt="$2" __secret="${3:-}" __value=""
    [ "$ASSUME_YES" -eq 1 ] && return 0
    if [ "$__secret" = "secret" ]; then
        read -rs -p "    ${__prompt}" __value; printf '\n'
    else
        read -r -p "    ${__prompt}" __value
    fi
    [ -n "$__value" ] && printf -v "$__var" '%s' "$__value"
    return 0
}

collect_input() {
    detect_public_ip || die "не удалось определить публичный IPv4 (нужен доступ в интернет)"
    info "Публичный IP: ${PUBLIC_IP}"
    if [ -z "$DOMAIN" ]; then
        DOMAIN="${PUBLIC_IP}.sslip.io"
        info "Домен по умолчанию: ${DOMAIN} (постоянный домен лучше: флаг --domain)"
    fi
    DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%/}"

    if [ -z "$OWNER_EMAIL" ] || [ -z "$OAUTH_ID" ] || [ -z "$OAUTH_SECRET" ]; then
        log "Данные Яндекс-приложения и владельца"
        info "1. Открой https://oauth.yandex.ru -> «Зарегистрировать приложение»"
        info "2. Платформа: Веб-сервисы. Redirect URI:"
        info "   https://${DOMAIN}/auth/yandex/callback"
        info "3. Права (Яндекс ID): login:email, login:info"
        info "4. ClientID и ClientSecret вводятся скрыто и не печатаются"
    fi

    [ -n "$OWNER_EMAIL" ] || ask OWNER_EMAIL "Email владельца (Yandex, первый администратор): "
    [[ "$OWNER_EMAIL" == *"@"* ]] || die "нужен email владельца (флаг --email или ввод по запросу)"

    [ -n "$OAUTH_ID" ] || ask OAUTH_ID "Yandex OAuth ClientID: "
    [ -n "$OAUTH_ID" ] || die "ClientID не задан: создай приложение (см. подсказку выше) и запусти снова"

    [ -n "$OAUTH_SECRET" ] || ask OAUTH_SECRET "Yandex OAuth ClientSecret: " secret
    [ -n "$OAUTH_SECRET" ] || die "ClientSecret не задан: запусти снова"

    if [ -z "$ALLOWED_DOMAINS" ]; then
        ALLOWED_DOMAINS="${OWNER_EMAIL##*@}"
        info "Домен входа по умолчанию: ${ALLOWED_DOMAINS} (изменить: --allowed-domains a.ru,b.ru)"
    fi
}

# ------------------------------------------------------------- configure ----

configure_gateway() {
    log "Генерирую секреты и пишу ${GATEWAY_DIR}/.env"
    local postgres_pw jwt_secret
    postgres_pw="$(openssl rand -hex 16)"
    jwt_secret="$(openssl rand -hex 32)"

    ( cd "$GATEWAY_DIR"
      umask 077
      cat > .env <<EOF
# Сгенерировано bootstrap.sh $(date -u +%Y-%m-%dT%H:%M:%SZ). Не коммитить и не публиковать.
GATEWAY_AUTH_ENABLED=true
GATEWAY_PUBLIC_URL=https://${DOMAIN}
GATEWAY_ISSUER_URL=https://${DOMAIN}
GATEWAY_RESOURCE_URL=https://${DOMAIN}/mcp
GATEWAY_ALLOWED_EMAIL_DOMAINS=${ALLOWED_DOMAINS}
GATEWAY_PORT=127.0.0.1:8000
POSTGRES_PASSWORD=${postgres_pw}
GATEWAY_JWT_SECRET=${jwt_secret}
GATEWAY_USER_TOKEN_ENCRYPTION_KEY=
YANDEX_OAUTH_CLIENT_ID=${OAUTH_ID}
YANDEX_OAUTH_CLIENT_SECRET=${OAUTH_SECRET}
YANDEX_OAUTH_SCOPES=login:email login:info
EOF
      chmod 600 .env
    )

    # Dedicated Fernet key generated inside the built image. Fallback (empty)
    # derives the key from the JWT secret: valid, but rotating the JWT secret
    # would invalidate every stored per-user token.
    log "Собираю образ шлюза и генерирую ключ шифрования пользовательских токенов"
    ( cd "$GATEWAY_DIR" && docker compose build )
    local fernet
    fernet="$( cd "$GATEWAY_DIR" && docker compose run --rm -T --no-deps gateway \
        python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' \
        2>/dev/null | tail -1 || true )"
    if [[ "$fernet" =~ ^[A-Za-z0-9_-]{43}=$ ]]; then
        ( cd "$GATEWAY_DIR" && sed -i "s|^GATEWAY_USER_TOKEN_ENCRYPTION_KEY=.*|GATEWAY_USER_TOKEN_ENCRYPTION_KEY=${fernet}|" .env )
        info "Ключ шифрования: сгенерирован (Fernet)"
    else
        warn "Fernet-ключ не получен: используется производный от JWT (валидно)"
    fi

    log "Назначаю первого администратора: ${OWNER_EMAIL}"
    python3 - "$GATEWAY_DIR/gateway-policy.json" "$OWNER_EMAIL" <<'PY'
import json, sys, pathlib
path, email = pathlib.Path(sys.argv[1]), sys.argv[2]
policy = json.loads(path.read_text(encoding="utf-8"))
backup = path.with_suffix(".json.orig")
if not backup.exists():
    backup.write_text(json.dumps(policy, ensure_ascii=False, indent=4), encoding="utf-8")
users = policy.setdefault("users", {})
if email not in users:
    users[email] = {"groups": ["admins"]}
path.write_text(json.dumps(policy, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
print(f"    ok: {email} -> groups: admins (копия до правки: {backup.name})")
PY
    info "gateway-policy.json изменён локально: не коммить этот файл вместе с секретами установки"
}

# ----------------------------------------------------------------- deploy ---

start_stack() {
    log "Запускаю PostgreSQL + Gateway + notification worker"
    ( cd "$GATEWAY_DIR" && docker compose up -d --build )
    info "Жду /healthz (миграции применяются при старте)..."
    if ! wait_http "http://127.0.0.1:8000/healthz" 240 '"ok": *true'; then
        ( cd "$GATEWAY_DIR" && docker compose logs --tail=80 gateway ) || true
        die "шлюз не поднялся за 240 секунд — логи выше"
    fi
    local hz=0
    healthz_check "http://127.0.0.1:8000/healthz" || hz=$?
    case "$hz" in
        0) info "healthz локально: ok, auth_enabled=true" ;;
        1) die "auth_enabled=false — останавливаюсь. Наружу не публиковать (SECURITY.md)" ;;
        *) die "healthz недоступен" ;;
    esac
}

publish_https() {
    log "Настраиваю HTTPS через Caddy: ${DOMAIN}"
    if [ -f /etc/caddy/Caddyfile ] && ! grep -q "bootstrap.sh managed" /etc/caddy/Caddyfile 2>/dev/null; then
        cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.backup-$(date +%Y%m%d%H%M%S)"
        warn "Существующий Caddyfile сохранён (Caddyfile.backup-*)"
    fi
    cat > /etc/caddy/Caddyfile <<EOF
# bootstrap.sh managed
${DOMAIN} {
    reverse_proxy 127.0.0.1:8000
}
EOF
    caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 \
        || die "Caddyfile не прошёл проверку (caddy validate --config /etc/caddy/Caddyfile)"
    systemctl reload caddy 2>/dev/null || systemctl restart caddy
    info "Жду сертификат и healthz по https://${DOMAIN} (до 240 секунд)..."
    if ! wait_http "https://${DOMAIN}/healthz" 240 '"ok": *true'; then
        warn "HTTPS healthz не отвечает. Частые причины:"
        warn "  - лимиты Let's Encrypt для *.sslip.io: запусти со своим доменом (--domain)"
        warn "  - порты 80/443 закрыты в облаке, или DNS не ведёт на ${PUBLIC_IP}"
        journalctl -u caddy --no-pager -n 30 || true
        die "после исправления: sudo bash ${INSTALL_DIR}/bootstrap.sh --doctor"
    fi
    info "healthz по HTTPS: ok"
}

verify_closed_port() {
    if curl -fsS -m 5 "http://${PUBLIC_IP}:8000/healthz" >/dev/null 2>&1; then
        warn "ПОРТ 8000 ОТКРЫТ ИЗ ИНТЕРНЕТА: проверь GATEWAY_PORT=127.0.0.1:8000 в .env"
        return 1
    fi
    info "Порт 8000 из интернета закрыт (шлюз доступен только через HTTPS)"
}

# ------------------------------------------------------------------ doctor ---

doctor() {
    local fails=0 domain=""
    log "Диагностика установки: ${INSTALL_DIR}"

    [ -d "$GATEWAY_DIR" ] || die "нет ${GATEWAY_DIR}: установка отсутствует. Запусти sudo bash bootstrap.sh"

    for svc in docker caddy; do
        if systemctl is-active --quiet "$svc"; then
            info "${svc}: работает"
        else
            warn "${svc}: НЕ работает (systemctl status ${svc})"
            fails=$((fails + 1))
        fi
    done

    if have docker; then
        ( cd "$GATEWAY_DIR" && docker compose ps ) || fails=$((fails + 1))
    else
        warn "docker не установлен"
        fails=$((fails + 1))
    fi

    if [ -f "${GATEWAY_DIR}/.env" ]; then
        local perms
        perms="$(stat -c '%a' "${GATEWAY_DIR}/.env")"
        if [ "$perms" = "600" ]; then
            info ".env: права 600"
        else
            warn ".env: права ${perms}, нужно 600 (chmod 600 ${GATEWAY_DIR}/.env)"
            fails=$((fails + 1))
        fi
        domain="$(grep -E '^GATEWAY_PUBLIC_URL=' "${GATEWAY_DIR}/.env" | head -1 | cut -d= -f2- | sed 's#https\?://##; s#/##')"
    else
        warn ".env отсутствует: шлюз не сконфигурирован"
        fails=$((fails + 1))
    fi

    local hz=0
    healthz_check "http://127.0.0.1:8000/healthz" || hz=$?
    case "$hz" in
        0) info "healthz (локально): ok, auth включён" ;;
        1) warn "healthz (локально): auth ВЫКЛЮЧЕН — наружу не публиковать"; fails=$((fails + 1)) ;;
        *) warn "healthz (локально): недоступен (docker compose logs gateway)"; fails=$((fails + 1)) ;;
    esac

    if [ -n "$domain" ]; then
        local hzs=0
        healthz_check "https://${domain}/healthz" || hzs=$?
        case "$hzs" in
            0) info "healthz (HTTPS ${domain}): ok, auth включён" ;;
            1) warn "healthz (HTTPS): auth выключен"; fails=$((fails + 1)) ;;
            *) warn "healthz (HTTPS ${domain}): недоступен (Caddy, сертификат или DNS)"; fails=$((fails + 1)) ;;
        esac
    fi

    if [ -n "$PUBLIC_IP" ]; then
        if curl -fsS -m 5 "http://${PUBLIC_IP}:8000/healthz" >/dev/null 2>&1; then
            warn "порт 8000 ОТКРЫТ из интернета: проверь GATEWAY_PORT=127.0.0.1:8000"
            fails=$((fails + 1))
        else
            info "порт 8000 из интернета закрыт"
        fi
    fi

    if [ "$fails" -eq 0 ]; then
        log "Диагностика: проблем не найдено"
        [ -n "$domain" ] && info "MCP URL: https://${domain}/mcp"
    else
        warn "Диагностика: проблем — ${fails}"
        exit 1
    fi
}

# ------------------------------------------------------------------- main ---

apt_supported

if [ "$MODE" = "doctor" ]; then
    GATEWAY_DIR="${INSTALL_DIR}/gateway"
    detect_public_ip || warn "публичный IP не определён: проверку порта 8000 пропускаю"
    doctor
    exit 0
fi

install_packages
locate_install_dir
collect_input
configure_gateway
start_stack
publish_https
verify_closed_port || true

cat <<EOF

============================================================
  AI-Native развёрнут

  MCP URL:        https://${DOMAIN}/mcp
  Вход:           https://${DOMAIN}/auth/yandex/login
  Админка:        https://${DOMAIN}/admin
  Healthz:        https://${DOMAIN}/healthz
  Установка:      ${INSTALL_DIR} (шлюз: ${GATEWAY_DIR})
  Администратор:  ${OWNER_EMAIL} (вход под этим Yandex-аккаунтом)

  Дальше:
  1. Войди по ссылке «Вход» под ${OWNER_EMAIL}.
  2. Подключи MCP-клиент к https://${DOMAIN}/mcp (OAuth).
  3. Установи пак скиллов (DEPLOY.md, раздел «Подключение агентов»).

  Обслуживание:
  - диагностика:  sudo bash ${INSTALL_DIR}/bootstrap.sh --doctor
  - обновление:   git -C ${INSTALL_DIR} pull && cd ${GATEWAY_DIR} && docker compose up -d --build
  - .env и gateway-policy.json содержат секреты установки: не коммитить.
  - Никогда не выполняй docker compose down -v: это удалит базу PostgreSQL.
============================================================
EOF

log "Готово."

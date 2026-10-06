# ai-native: платформа скиллов и шлюз

[Read in English](README.md)

Портативная система скиллов для ИИ-ассистентов — вместе с сервером GatewayMCP, с которым эти скиллы работают. Один репозиторий, одна команда развёртывания, один MCP-адрес для всех клиентов.

Две части:

- **Платформа скиллов.** Скилл — исполняемая инструкция: как выполнять работу по правилам компании. Скиллы живут в репозитории, версионируются, проходят ревью и собираются в устанавливаемые паки для разных агентов: Claude Code, Codex, Cursor, OpenCode, OpenClaw, Hermes, ZCode. Здесь лежит референсный набор AI-Native и сборщик, который превращает каноническое дерево `skills/` в паки.
- **GatewayMCP** (каталог `gateway/`). Одна MCP-граница между ассистентами и корпоративными системами: OAuth, права на действия и ресурсы, аудит, изоляция секретов, корпоративная память, адаптеры бэкендов. Агенты подключаются к шлюзу, проходят вход один раз и вызывают небольшой стабильный набор публичных MCP-инструментов — секреты бэкендов до агента не доходят. Тот же код сервера публикуется отдельно как [`comindspace/gateway-mcp`](https://github.com/comindspace/gateway-mcp).

## Развёртывание одной командой

На чистой VM с Ubuntu или Debian:

```bash
git clone https://github.com/comindspace/ai-native.git
cd ai-native
sudo bash bootstrap.sh
```

Скрипт установит Docker, Docker Compose и Caddy, сгенерирует секреты, назначит первого администратора, запустит PostgreSQL, шлюз и воркер уведомлений за HTTPS, проверит `/healthz` и напечатает готовый MCP-адрес. Единственное ручное условие — OAuth-приложение Яндекса для входа (точный Redirect URI скрипт печатает сам). Полный гайд, ручная установка и разбор ошибок: [DEPLOY.md](DEPLOY.md).

## Контракт скилла

`SKILL.md` (инструкция) + `skill.yaml` (манифест: версия, совместимые агенты, требования) + опциональные `references/`, `scripts/`, `assets/`, `evals/`. Каждый упакованный скилл несёт телеметрический контракт `gateway-skill-telemetry:v1`: агент отмечает запуск и завершение скилла, в телеметрию не попадают промпты, тексты документов и секреты.

## Опубликованные скиллы

- `ai-native-core-starter-kit` — операционная модель запуска AI-Native-ролей: интейк, модель работы, источник истины, ролевые карты, бриф пилота, ворота релиза.
- `ai-native-proposal` — подготовка клиентских КП на программы AI-Native.
- `architect` — архитектура GenAI: RAG, агенты, tool use, MCP, ADR, безопасность.
- `editorial-style` — общий слой финальной правки делового русского.
- `smd-drawio`, `func-arch-drawio`, `eepc-drawio` — методы схем в draw.io.
- `sequential-thinking` — структурированное пошаговое рассуждение.
- `document-templates` — шаблоны процессов и документов как переносимый скилл.

Реестр публичных паков: `agent-platform/skill-packs.json`.

## Сборка паков

```bash
python agent-platform/build_agent_plugins.py validate-skills
python agent-platform/build_agent_plugins.py build-plugins --clean
python agent-platform/build_agent_plugins.py validate-generated
```

Цели сборки: Claude Code (`.claude-plugin`), Codex (`.codex-plugin` и маркетплейс), Cursor (`.cursor-plugin`), OpenClaw (`openclaw.plugin.json`), Hermes (`plugin.yaml`), OpenCode и ZCode (переносимое дерево; ZCode читает маркетплейс `.zcode-plugin/` в корне репозитория).

## Структура репозитория

```text
gateway/           сервер GatewayMCP: код, compose-файлы, политики, тесты
skills/            каноническое дерево скиллов (источник для паков)
agent-platform/    сборщик паков и его тесты
plugins/           сгенерированные паки (не править руками)
.claude-plugin/ .cursor-plugin/ .zcode-plugin/ .agents/   маркетплейсы агентов
bootstrap.sh       установщик на одну команду
DEPLOY.md          гайд по развёртыванию
```

Каталог `gateway/` зеркалирует отдельный репозиторий `comindspace/gateway-mcp`; документация сервера лежит там (`gateway/README.md`, `gateway/SECURITY.md`, `gateway/docs/`). Обновление: `git subtree pull --prefix gateway <remote-gateway-mcp> main`.

Лицензия — Apache-2.0.

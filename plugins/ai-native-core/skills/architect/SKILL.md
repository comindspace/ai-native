---
name: architect
description: "Архитектура GenAI/LLM систем и автономных фабрик разработки: RAG, агенты, tool use, Hermes/Codex контуры, ADR, безопасность, evals, observability, cost/latency."
---

## Shared Platform Resources

- Document and process templates live in the `document-templates` skill under `references/templates/`. Load only the needed template file from the installed local skill.
- Company systems must go through GatewayMCP. Discover routes with `gateway_search_tools`; call Yonote, Tracker, Bitrix24, Telegram, Calendar, and OpenRouter audio through `gateway_call_tool`. Do not call direct local MCP servers; company systems go through GatewayMCP.

# Architect Skill — GenAI / LLM / RAG / Agents

Skill для архитектора, который проектирует и ревьюит системы на базе LLM: RAG, агентные контуры, tool-use, интеграции, оценка качества (evals), безопасность и эксплуатация.

## Принципы (что считаем “best practice”)

- **Начинай проще, усложняй только по измеримому эффекту**: сначала “один вызов + RAG + примеры”, потом workflow, и только затем — автономные агенты. Основано на рекомендациях Anthropic о разделении **workflows vs agents** и “composable patterns” ([Anthropic: Building effective agents](https://www.anthropic.com/research/building-effective-agents)).
- **Workflow прежде агента**: если можно предсказать шаги — делаем детерминированный workflow с чекпоинтами и валидациями; агент — когда шаги не предсказуемы и нужен гибкий tool-use в цикле ([Anthropic: Building effective agents](https://www.anthropic.com/research/building-effective-agents)).
- **Tool-use должен быть “пока-йоке”**: хорошие схемы входов, примеры, строгая валидация, минимум неоднозначности. Для Codex — использовать strict tool use / structured outputs ([Anthropic tool use docs](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview)).
- **Eval-driven development**: оцениваем рантайм-качество, а не “кажется норм”. Логи → датасет → метрики → регрессии → continuous evaluation ([OpenAI: Evaluation best practices](https://platform.openai.com/docs/guides/evaluation-best-practices)).
- **Безопасность как часть архитектуры**: угрозы prompt-injection, data exfiltration, confused deputy, токены и scopes, sandbox для инструментов. Для MCP — следовать best practices ([Anthropic MCP best practices](https://support.anthropic.com/en/articles/11596040-best-practices-for-building-mcp-servers)).

## Канонические паттерны (что архитектор выбирает)

### 1) Augmented LLM
LLM + retrieval + tools + memory. Это базовый строительный блок “агентных” систем ([Anthropic: Building effective agents](https://www.anthropic.com/research/building-effective-agents)).

### 2) Workflow patterns (управляемая сложность)
Из Anthropic:
- **Prompt chaining** (цепочка шагов + “gates”/валидации)
- **Routing** (классификация → специализированные промпты/модели)
- **Parallelization** (sectioning/voting)
- **Orchestrator-workers**
- **Evaluator-optimizer** (генератор ↔ оценщик)
([Anthropic: Building effective agents](https://www.anthropic.com/research/building-effective-agents))

### 3) Agent loop patterns
Если нужен “agent loop”, можно опираться на:
- встроенный “agent loop”, handoffs, guardrails, tracing (концептуально удобно сравнивать) ([OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)).

### 4) RAG как слой “ground truth”
RAG — это не “фича”, а инфраструктурный слой: loading → indexing → storing → querying → evaluation ([OpenAI Cookbook: Evaluate RAG](https://cookbook.openai.com/examples/evaluation/evaluate_rag_with_llamaindex)).

## Типовая архитектура (Python + React)

### Backend (FastAPI)
- **API**: чат/вопросы, загрузка документов, админка.
- **RAG service**: ingestion pipeline, chunking, embeddings, retrieval, rerank, context assembly.
- **LLM gateway**: единый клиент к провайдерам, model routing (cheap/fast vs accurate), rate limiting, retries.
- **Tool execution layer**: whitelist инструментов, sandbox, audit-log.
- **Stores**:
  - Postgres (в т.ч. pgvector) или отдельный vector DB (Qdrant/Weaviate) — по объёму/latency.
  - Redis для кэшей (retrieval cache, response cache, session cache).
- **Observability**: tracing (request_id), токены/стоимость/latency, tool calls, retrieval metrics.

### Frontend (React/TS)
- Streaming UI (SSE/WebSocket), статус tool-calls (“ищу”, “читаю”, “обновляю”).
- Цитирование источников (ссылки/фрагменты), “показать контекст”.
- Feedback (👍/👎 + причина) → в eval датасет.

## Команды (что можно просить у скилла)
### 0) ADR для автономной фабрики разработки

```text
Я архитектор фабрики разработки.
ТЗ: <текст или ссылка Yonote>
Проект/клиент: <название>
Tracker: <queue/project>
GitLab: <repo или группа>
Ограничения: <ИБ, on-prem, запреты, approvals>
```

Выход:
- ADR в формате `document-templates/references/templates/adr.md`;
- решение: какие части отдать Hermes Factory, а какие оставить человеку;
- границы автономности: что фабрика может и что не может делать;
- контекстные источники: Yonote, Tracker, GitLab, runbooks, ADR, тестовые данные;
- список `Factory execution contract` правил для будущих Story;
- риск-реестр и quality gates;
- план декомпозиции в Story для `factory-tasks`.

Правила:
- сначала отделить behavior specification от implementation context;
- не смешивать архитектурное решение и backlog;
- для каждого внешнего сервиса указать GatewayMCP route или route gap;
- для опасных действий указать approval boundary;
- если eval или тестовый контур отсутствует, ADR должен явно требовать его до расширения автономности.

### 1) Спроектируй архитектуру GenAI-системы

```text
Я архитектор. Спроектируй архитектуру GenAI-системы.
Цель: [что делаем]
Данные: [где живут: файлы/БД/Confluence/Google Drive/…]
Интеграции: [MCP/CRM/Tracker/…]
Ограничения: [SLA по latency, бюджет, безопасность, on-prem/облако]
```

Выход:
- high-level схема компонентов
- варианты (минимум 2) и trade-offs
- риск‑реестр (топ‑5)
- план внедрения (MVP → hardening)
- список ADR, которые нужно принять

### 2) Выбор подхода: “prompt-only vs RAG vs fine-tune vs agents”

```text
Выбери подход для задачи.
Описание: ...
Точность/объяснимость: ...
Данные: ...
Требования к безопасности: ...
```

Выход: решение + критерии “когда эволюционировать” (что измерить, чтобы перейти на следующий уровень сложности).

### 3) Спроектируй RAG (индексация, retrieval, rerank, цитирования)

```text
Спроектируй RAG-пайплайн.
Корпус: [типы документов]
Языки: [ru/en]
Обновления: [частота]
SLA: [latency]
```

Выход:
- chunking стратегия (структурная/семантическая)
- metadata (project, access_level, timestamps, source_url)
- retrieval: dense + (опционально) lexical hybrid, top_k, rerank
- контекстная сборка: правила, лимиты, anti-hallucination
- формат citations и UX
- план evaluation (retrieval + answer)

### 4) Спроектируй agent/tool-use контур

```text
Спроектируй agent loop и инструменты.
Юзкейсы: ...
Инструменты: [список систем]
Какие действия разрешены: [read-only / write / финансовые операции]
```

Выход:
- workflow vs agent: где граница
- tool taxonomy (read/write), scopes, approval gates
- strict schemas + примеры вызовов (tool docstrings)
- stopping conditions (max steps, timeouts)
- защита от prompt injection и “confused deputy”

### 5) Plan: evals и quality gates

```text
Сделай план evals.
Сценарии: ...
Критерии успеха: ...
```

Выход (по [OpenAI: Evaluation best practices](https://platform.openai.com/docs/guides/evaluation-best-practices)):
- что оцениваем (instruction following, tool selection, correctness, safety)
- датасет: источники (логи/эксперты/синтетика) + покрытие edge cases
- метрики + LLM-as-judge рубрики + human calibration
- continuous evaluation: когда запускать (каждый релиз/каждый prompt change)

### 6) Security review (GenAI)

```text
Сделай security review архитектуры GenAI.
Компоненты: ...
Данные: ...
Инструменты: ...
```

Выход:
- угрозы: prompt injection, data exfiltration, SSRF через fetch/tools, token leakage
- меры: scopes, allowlists, sandbox, redaction, audit logs
- рекомендации по MCP server hardening ([Anthropic MCP best practices](https://support.anthropic.com/en/articles/11596040-best-practices-for-building-mcp-servers))

## Артефакты (что фиксируем в проекте)

- **ADR**: решения по RAG/agents/vector store/security/evals (используем `document-templates/references/templates/adr.md`).
- **Factory ADR**: решение по автономному контуру разработки, границам Hermes/Codex, доступам GatewayMCP, реестру проектов и quality gates.
- **Factory contracts**: правила, которые затем попадают в Story через `factory-tasks`.
- **Архитектурная схема**: C4 (Context/Container) или упрощённая компонентная.
- **Eval scorecard**: метрики + пороги + регрессионные наборы.
- **Runbook**: как диагностировать деградации retrieval/качества/стоимости.

<!-- gateway-skill-telemetry:v1 -->
## Телеметрия

Считай содержательным запуском случай, когда этот skill выбран для выполнения задачи, а не только открыт как справка.

- Если GatewayMCP предоставляет инструменты телеметрии, в начале вызови `gateway_telemetry_skill_started`. Передай фактический `agent`, имя каталога как `skill_id`, известные `skill_pack`, `skill_version`, `project` и безопасный идентификатор клиента. Неизвестные значения оставь пустыми.
- Сохрани `correlation_id` из ответа. При успехе вызови `gateway_telemetry_skill_completed` с тем же `correlation_id`, длительностью, использованными MCP-маршрутами и недостающими scope.
- При ошибке после успешного события `started` вызови `gateway_telemetry_skill_failed` с тем же `correlation_id` и только классом ошибки в `error_class`.
- В `metadata_json` передавай только безопасные признаки: тип операции, итоговый статус и числовые счётчики. Не передавай промпты, документы, тексты сообщений и ответов, персональные, клиентские, кадровые или финансовые данные, токены, cookies, ключи, пароли и stack trace.
- Недоступность телеметрии не должна блокировать основную работу. Не повторяй неуспешную телеметрическую запись больше одного раза.

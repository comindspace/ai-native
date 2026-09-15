---
name: ai-native-core-starter-kit
description: "Навигатор по AI-Native Core Starter Kit. Используй, когда нужно запустить AI-Native Core у клиента, понять следующий шаг внедрения, собрать первую волну ролей и skills, оформить пилот, пройти discovery или pilot design после воркшопа. Ведёт от intake и operating model через source of truth, роли и skills к пилоту, baseline, weekly review и executive review."
---


## Shared Platform Resources

- Document and process templates live in the `document-templates` skill under `references/templates/`. Load only the needed template file from the installed local skill.
- Company systems must go through GatewayMCP. Discover routes with `gateway_search_tools`; call Yonote, Tracker, Bitrix24, Telegram, Calendar, and OpenRouter audio through `gateway_call_tool`. Do not call direct local MCP servers; company systems go through GatewayMCP.
# AI-Native Core Starter Kit

Skill-навигатор для запуска проектов `AI-Native Core`.

Он не заменяет сам `Starter Kit`, а помогает использовать его правильно и по шагам.

## Когда использовать

Используй skill, когда пользователь:

- запускает `AI-Native Core` у нового клиента;
- спрашивает, с чего начать после воркшопа;
- хочет определить следующую стадию проекта;
- хочет собрать первую волну ролей, навыков или пилота;
- просит пройти по `Starter Kit` как по рабочему маршруту;
- хочет подготовить pilot package, baseline или executive review.

## Что делает skill

1. Определяет текущую стадию проекта.
2. Выбирает ближайший обязательный шаг.
3. Открывает только нужные reference-файлы.
4. Направляет к конкретным документам `Starter Kit`.
5. Предупреждает о типовых ошибках.

## Быстрый маршрут

Главный путь всегда такой:

`intake -> operating model -> source of truth -> role cards -> skills -> pilot brief -> release gates -> baseline -> weekly review -> executive review`

Если пользователь пытается перепрыгнуть через этапы, сначала открой [references/anti-patterns.md](./references/anti-patterns.md).

## Как определить стадию

Сначала прочитай:

- [references/stage-detection.md](./references/stage-detection.md)

Если стадия уже понятна, открой соответствующий режим:

- discovery: [references/modes/discovery-mode.md](./references/modes/discovery-mode.md)
- pilot design: [references/modes/pilot-design-mode.md](./references/modes/pilot-design-mode.md)
- pilot execution: [references/modes/pilot-execution-mode.md](./references/modes/pilot-execution-mode.md)

Если нужен полный маршрут, открой:

- [references/workflow.md](./references/workflow.md)

Если нужно быстро понять, какой документ использовать, открой:

- [references/document-map.md](./references/document-map.md)

## Основные правила

- Не начинай с навыков до фиксации `Source of Truth`.
- Не запускай пилот без baseline.
- Не бери слишком широкий объём первой волны.
- Не путай использование нового контура с бизнес-эффектом.
- Не обещай автономию раньше, чем собраны качество, контроль и review.

## Как должен выглядеть хороший ответ

- Сначала назови текущую стадию.
- Потом назови следующий обязательный шаг.
- Потом дай 1-3 конкретных документа, которые нужно использовать.
- Потом коротко предупреди, чего делать не надо.

Не пересказывай весь `Starter Kit`, если можно дать следующий конкретный шаг.

<!-- gateway-skill-telemetry:v1 -->
## Телеметрия

Считай содержательным запуском случай, когда этот skill выбран для выполнения задачи, а не только открыт как справка.

- Если GatewayMCP предоставляет инструменты телеметрии, в начале вызови `gateway_telemetry_skill_started`. Передай фактический `agent`, имя каталога как `skill_id`, известные `skill_pack`, `skill_version`, `project` и безопасный идентификатор клиента. Неизвестные значения оставь пустыми.
- Сохрани `correlation_id` из ответа. При успехе вызови `gateway_telemetry_skill_completed` с тем же `correlation_id`, длительностью, использованными MCP-маршрутами и недостающими scope.
- При ошибке после успешного события `started` вызови `gateway_telemetry_skill_failed` с тем же `correlation_id` и только классом ошибки в `error_class`.
- В `metadata_json` передавай только безопасные признаки: тип операции, итоговый статус и числовые счётчики. Не передавай промпты, документы, тексты сообщений и ответов, персональные, клиентские, кадровые или финансовые данные, токены, cookies, ключи, пароли и stack trace.
- Недоступность телеметрии не должна блокировать основную работу. Не повторяй неуспешную телеметрическую запись больше одного раза.

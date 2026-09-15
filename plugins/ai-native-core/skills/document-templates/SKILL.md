---
name: document-templates
description: "Shared document and process templates for agent work: project context, meeting protocols, project health, ADR, UJM, test plans, user stories, proposals, reports, contracts, marketing briefs, and Yonote page conventions. Use when a skill needs a reusable template or when a user asks for a document or process template."
---


## Shared Platform Resources

- Document and process templates live in the `document-templates` skill under `references/templates/`. Load only the needed template file from the installed local skill.
- Company systems must go through GatewayMCP. Discover routes with `gateway_search_tools`; call Yonote, Tracker, GitLab, Yandex Disk, Bitrix24, Telegram, Calendar, Mail, and OpenRouter audio through `gateway_call_tool`.

# Document Templates

Use this skill when you need a reusable company template for a document, process artifact, Tracker description, Yonote page, proposal, report, or КП.

For rules about generating or checking `.docx` files in the coMind visual and language style, use the `comind-docx` skill. This skill provides the template files; `comind-docx` provides the rendering and quality rules.

## Where Templates Live

Templates are bundled in this skill under:

```text
references/templates/
```

Use the local plugin path installed with the `document-templates` plugin pack. GatewayMCP does not serve skill files; if this skill is missing, install or update the plugin pack before using templates.

Do not expect a repository-level `templates/` folder. Treat the bundled `document-templates` skill as the portable source for agents.

## GatewayMCP Rule

For company systems, use GatewayMCP instead of direct MCP servers:

- Discover available tools with `gateway_search_tools`.
- Call routed tools with `gateway_call_tool`.
- Use Gateway routes for Yonote, Tracker, GitLab, Yandex Disk, Bitrix24, Telegram, Calendar, Mail, and OpenRouter audio.

## Template Index

- `adr.md` - architecture decision record.
- `bug-report.md` - bug report.
- `contract.md` - contract card/content structure.
- `daily-plan.md` - daily plan.
- `definition-of-ready.md` - Definition of Ready.
- `discovery-questions.md` - discovery question set.
- `estimation.md` - estimation structure.
- `feature-list.md` - feature list.
- `handoff.md` - handoff note.
- `kickoff-protocol.md` - project kickoff protocol.
- `kp-blank-template.docx` - blank КП Word template.
- `kp-template-full-content.docx` - full-content КП Word template.
- `kp-template.docx` - КП Word template.
- `last-page-template.docx` - КП last-page Word template.
- `lead-card.md` - lead card.
- `marketing-content-plan.md` - marketing content plan.
- `marketing-experiment-brief.md` - marketing experiment brief.
- `marketing-icp-jtbd.md` - ICP/JTBD template.
- `marketing-messaging-house.md` - messaging house.
- `marketing-positioning.md` - positioning template.
- `milestone-plan.md` - milestone plan.
- `mr-description.md` - merge request description.
- `ops-unblock.md` - operational unblock template.
- `proposal.md` - proposal structure.
- `project-context-index.md` - canonical project index and source-of-truth map.
- `project-health.md` - project health report with evidence and trends.
- `project-meeting-protocol.md` - meeting protocol with decisions, commitments, risks, and client signals.
- `release-checklist.md` - release checklist.
- `release-notes.md` - release notes.
- `runbook.md` - runbook.
- `status-report.md` - status report.
- `test-plan.md` - test plan.
- `ticket.md` - task/ticket template.
- `ujm.md` - User Journey Map.
- `user-story.md` - user story.
- `weekly-focus.md` - weekly focus.
- `yonote-00-index.md` - Yonote project index.
- `yonote-page-conventions.md` - Yonote page conventions.

## How To Use

1. Choose the closest template from the index.
2. Load only the needed file from `references/templates/`.
3. Fill placeholders with project-specific content.
4. If saving to company systems, use GatewayMCP routed tools.
5. Keep secrets, tokens, internal webhook URLs, and credentials out of generated documents.

<!-- gateway-skill-telemetry:v1 -->
## Телеметрия

Считай содержательным запуском случай, когда этот skill выбран для выполнения задачи, а не только открыт как справка.

- Если GatewayMCP предоставляет инструменты телеметрии, в начале вызови `gateway_telemetry_skill_started`. Передай фактический `agent`, имя каталога как `skill_id`, известные `skill_pack`, `skill_version`, `project` и безопасный идентификатор клиента. Неизвестные значения оставь пустыми.
- Сохрани `correlation_id` из ответа. При успехе вызови `gateway_telemetry_skill_completed` с тем же `correlation_id`, длительностью, использованными MCP-маршрутами и недостающими scope.
- При ошибке после успешного события `started` вызови `gateway_telemetry_skill_failed` с тем же `correlation_id` и только классом ошибки в `error_class`.
- В `metadata_json` передавай только безопасные признаки: тип операции, итоговый статус и числовые счётчики. Не передавай промпты, документы, тексты сообщений и ответов, персональные, клиентские, кадровые или финансовые данные, токены, cookies, ключи, пароли и stack trace.
- Недоступность телеметрии не должна блокировать основную работу. Не повторяй неуспешную телеметрическую запись больше одного раза.

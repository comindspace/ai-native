---
name: sequential-thinking
description: Use when complex problems require systematic step-by-step reasoning with ability to revise thoughts, branch into alternative approaches, or dynamically adjust scope. Ideal for multi-stage analysis, design planning, problem decomposition, or tasks with initially unclear scope.
license: MIT
---

## Shared Platform Resources

- Document and process templates live in the `document-templates` skill under `references/templates/`. Load only the needed template file from the installed local skill.
- Company systems must go through GatewayMCP. Discover routes with `gateway_search_tools`; call Yonote, Tracker, Bitrix24, Telegram, Calendar, and OpenRouter audio through `gateway_call_tool`. Do not call direct local MCP servers; company systems go through GatewayMCP.

# Sequential Thinking

Enables structured problem-solving through iterative reasoning with revision and branching capabilities.

## Core Capabilities

- **Iterative reasoning**: Break complex problems into sequential thought steps
- **Dynamic scope**: Adjust total thought count as understanding evolves
- **Revision tracking**: Reconsider and modify previous conclusions
- **Branch exploration**: Explore alternative reasoning paths from any point
- **Maintained context**: Keep track of reasoning chain throughout analysis

## When to Use

Use this structured reasoning workflow when:
- Problem requires multiple interconnected reasoning steps
- Initial scope or approach is uncertain
- Need to filter through complexity to find core issues
- May need to backtrack or revise earlier conclusions
- Want to explore alternative solution paths

**Don't use for**: Simple queries, direct facts, or single-step tasks.

## Basic Usage

Track these fields while reasoning:

### Required Parameters

- `thought` (string): Current reasoning step
- `nextThoughtNeeded` (boolean): Whether more reasoning is needed
- `thoughtNumber` (integer): Current step number (starts at 1)
- `totalThoughts` (integer): Estimated total steps needed

### Optional Parameters

- `isRevision` (boolean): Indicates this revises previous thinking
- `revisesThought` (integer): Which thought number is being reconsidered
- `branchFromThought` (integer): Thought number to branch from
- `branchId` (string): Identifier for this reasoning branch

## Workflow Pattern

```
1. Start with initial thought (thoughtNumber: 1)
2. For each step:
   - Express current reasoning in `thought`
   - Estimate remaining work via `totalThoughts` (adjust dynamically)
   - Set `nextThoughtNeeded: true` to continue
3. When reaching conclusion, set `nextThoughtNeeded: false`
```

## Simple Example

```typescript
// First thought
{
  thought: "Problem involves optimizing database queries. Need to identify bottlenecks first.",
  thoughtNumber: 1,
  totalThoughts: 5,
  nextThoughtNeeded: true
}

// Second thought
{
  thought: "Analyzing query patterns reveals N+1 problem in user fetches.",
  thoughtNumber: 2,
  totalThoughts: 6, // Adjusted scope
  nextThoughtNeeded: true
}

// ... continue until done
```

## Advanced Features

For revision patterns, branching strategies, and complex workflows, see:
- [Advanced Usage](references/advanced.md) - Revision and branching patterns
- [Examples](references/examples.md) - Real-world use cases

## Tips

- Start with rough estimate for `totalThoughts`, refine as you progress
- Use revision when assumptions prove incorrect
- Branch when multiple approaches seem viable
- Express uncertainty explicitly in thoughts
- Adjust scope freely - accuracy matters less than progress visibility

<!-- gateway-skill-telemetry:v1 -->
## Телеметрия

Считай содержательным запуском случай, когда этот skill выбран для выполнения задачи, а не только открыт как справка.

- Если GatewayMCP предоставляет инструменты телеметрии, в начале вызови `gateway_telemetry_skill_started`. Передай фактический `agent`, имя каталога как `skill_id`, известные `skill_pack`, `skill_version`, `project` и безопасный идентификатор клиента. Неизвестные значения оставь пустыми.
- Сохрани `correlation_id` из ответа. При успехе вызови `gateway_telemetry_skill_completed` с тем же `correlation_id`, длительностью, использованными MCP-маршрутами и недостающими scope.
- При ошибке после успешного события `started` вызови `gateway_telemetry_skill_failed` с тем же `correlation_id` и только классом ошибки в `error_class`.
- В `metadata_json` передавай только безопасные признаки: тип операции, итоговый статус и числовые счётчики. Не передавай промпты, документы, тексты сообщений и ответов, персональные, клиентские, кадровые или финансовые данные, токены, cookies, ключи, пароли и stack trace.
- Недоступность телеметрии не должна блокировать основную работу. Не повторяй неуспешную телеметрическую запись больше одного раза.

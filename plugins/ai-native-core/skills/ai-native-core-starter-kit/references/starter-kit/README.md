# AI-Native Core Starter Kit

**Дата:** 2026-04-22  
**Статус:** `v0.2`  
**Назначение:** базовая внутренняя сборка coMind для запуска проектов `AI-Native Core`

---

## Статус пакета

Эта папка является каноническим reference-пакетом для skill `ai-native-core-starter-kit`.

Если где-то рядом существует копия `Starter Kit` в `docs/`, считай её внешней публикационной версией, а не основным источником для skill.

---

## Что это

`AI-Native Core Starter Kit` — это не внешний продукт и не “прототип”.

Это рабочая стартовая сборка, которую команда coMind адаптирует под конкретную компанию, чтобы:

- не начинать проекты с чистого листа;
- запускать discovery и scoping по единой логике;
- быстро собирать operating model;
- стандартизировать skills, quality gates и SoT;
- привязывать внедрение к бизнес-эффекту.

---

## Что входит в `v0.2`

### 0. How To

- [HOW-TO.md](./HOW-TO.md)

### 1. Positioning and operating model

- [operating-model.md](./01-positioning/operating-model.md)
- [delegate-review-own.md](./01-positioning/delegate-review-own.md)
- [decision-rights.md](./01-positioning/decision-rights.md)

### 2. Source of truth

- [source-of-truth-map.md](./02-source-of-truth/source-of-truth-map.md)

### 3. Skills

- [SKILL-template.md](./03-skills/SKILL-template.md)
- [role-card-template.md](./03-skills/role-card-template.md)
- [skill-spec-template.md](./03-skills/skill-spec-template.md)

### 4. Quality

- [release-gates.md](./04-quality/release-gates.md)
- [pilot-scorecard.md](./04-quality/pilot-scorecard.md)
- [eval-plan-template.md](./04-quality/eval-plan-template.md)

### 5. Delivery

- [client-intake-template.md](./05-delivery/client-intake-template.md)
- [pilot-brief-template.md](./05-delivery/pilot-brief-template.md)
- [executive-review-template.md](./05-delivery/executive-review-template.md)
- [weekly-review-agenda.md](./05-delivery/weekly-review-agenda.md)

### 6. Adoption

- [stakeholder-map-template.md](./06-adoption/stakeholder-map-template.md)
- [champion-model.md](./06-adoption/champion-model.md)
- [pilot-communication-template.md](./06-adoption/pilot-communication-template.md)
- [training-plan-template.md](./06-adoption/training-plan-template.md)

### 7. Metrics

- [metrics-shortlist.md](./07-metrics/metrics-shortlist.md)
- [baseline-template.md](./07-metrics/baseline-template.md)
- [before-after-template.md](./07-metrics/before-after-template.md)

### 8. Technical reference

- [assistant-skeleton.md](./08-technical-reference/assistant-skeleton.md)
- [integration-patterns.md](./08-technical-reference/integration-patterns.md)
- [naming-conventions.md](./08-technical-reference/naming-conventions.md)

### 9. Playbooks

- [project-kickoff-playbook.md](./10-playbooks/project-kickoff-playbook.md)
- [first-30-days-playbook.md](./10-playbooks/first-30-days-playbook.md)

---

## Как использовать

1. На старте проекта пройти `client intake`.
2. Зафиксировать target operating model и `Delegate / Review / Own`.
3. Построить `Source of Truth map`.
4. Выбрать первую волну ролей и skills.
5. Пропустить сценарии через `release gates`.
6. Снять baseline и завести pilot scorecard.
7. Развернуть базовый technical reference layer.

---

## Что пока не входит

В `v0.2` намеренно не включены:

- отраслевые версии;
- platform packs для `Claude / Codex / Cursor`;
- готовые интеграции под конкретные системы;
- расширенный observability layer;
- большая библиотека готовых skills.

Сначала нужен единый core layer. Потом platform adapters.

---

## Управленческий принцип

> Starter Kit должен ускорять `AI-Native Core`, а не превращаться в отдельный размытый продукт.

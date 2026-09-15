# Ticket Template (Yandex Tracker)

**Project / Queue:** [PROJECTKEY]
**ID:** [PROJECTKEY-XXX]
**Type:** Epic / Story / Task / Bug
**Epic:** [ссылка на Epic или N/A для Epic-задачи]
**Milestone:** [название milestone]
**Priority:** Critical / High / Medium / Low
**Assignee:** [login]

---

## Summary

[Короткое название задачи]

## Description

[Что нужно сделать, контекст, ограничения. Достаточно подробно, чтобы исполнитель не “догадывался”.]

## Acceptance Criteria

- [ ] **AC1:** ...
- [ ] **AC2:** ...
- [ ] **AC3:** ...

## Wiki (Source of Truth)

Вставьте ссылки на артефакты в Yonote:

```text
Wiki:
- Index: <link to 00-Index>
- Requirements: <link>
- UJM: <link or N/A>
- ADR: <link or N/A>
- Test Plan: <link or N/A>
```

## Dependencies / Links

- Depends on: [PROJ-...]
- Related: [PROJ-...]

## Notes

- [Технические детали / ссылки / договоренности]

---

## Definition of Ready (DoR) — быстрый чек

> Полный DoR: `document-templates/references/templates/definition-of-ready.md`

- [ ] Description понятно и достаточно подробно
- [ ] Есть Acceptance Criteria (чеклист)
- [ ] Есть `Wiki:` блок со ссылками (или `N/A`)
- [ ] Указаны Project/Queue и Epic (или `N/A` для Epic-задачи)
- [ ] Указаны Priority и Milestone (если применимо)
- [ ] Есть оценка (Story Points) или пометка “needs estimation”
- [ ] Зависимости указаны или явно “нет”

# Eval Plan Template

## 1. Scope

- `Scenario / skill`
- `Owner`
- `Reviewer`
- `Stage`: test / pilot / prod

## 2. What we are evaluating

- instruction following;
- correctness against source of truth;
- tool or system selection;
- output format compliance;
- escalation behavior;
- safety behavior.

## 3. Dataset

Источники кейсов:

- реальные обезличенные кейсы;
- экспертно составленные кейсы;
- edge cases;
- failure cases from pilot.

Для каждого набора фиксируем:

- объём;
- тип кейсов;
- источник;
- ограничения.

## 4. Metrics

### Quality metrics

- completeness;
- factual correctness;
- acceptance rate;
- correction rate;
- escalation precision;
- unsafe action rate.

### Business metrics

- cycle time delta;
- throughput delta;
- rework reduction;
- cost to serve delta;
- time saved per role.

## 5. Rubric

Для каждого кейса reviewer оценивает:

- `Pass`
- `Pass with corrections`
- `Fail`

Если нужен более детальный уровень:

- `0` unacceptable
- `1` weak
- `2` acceptable
- `3` strong

## 6. Pass criteria

- какой минимум качества нужен для перехода в пилот;
- какой максимум ошибок допустим;
- какой unsafe threshold является стоп-фактором;
- какой бизнес-эффект считаем достаточным.

## 7. Review cadence

- как часто пересматриваем результаты;
- кто участвует в review;
- где фиксируются выводы;
- кто принимает решение о переходе между стадиями.

## 8. Decision log

По итогам каждого review фиксируем:

- что оставляем;
- что меняем;
- что откатываем;
- что переносим в следующий релиз.

## 9. Rule

Eval plan нужен не для “галочки”. Если сценарий нельзя проверить на реальных кейсах и критериях, он ещё не готов к production discussion.


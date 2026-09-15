# How To Use AI-Native Core Starter Kit

## Для чего этот документ

Этот `How To` нужен, чтобы команда coMind не читала весь Starter Kit подряд, а использовала его как рабочий маршрут запуска проекта.

Главное правило:

> Starter Kit используется не “по вдохновению”, а по шагам.

---

## Когда использовать Starter Kit

Используйте его, когда:

- клиент уже созрел на `AI-Native Core`;
- после воркшопа нужно перейти к реальному scoping;
- нужно быстро собрать первую волну пилота;
- нужно стандартизировать запуск нового проекта внутри coMind.

Не используйте его как:

- публичный “коробочный продукт”;
- замену discovery;
- замену реального ownership со стороны клиента.

---

## Режим 1. Discovery Mode

Этот режим нужен, чтобы понять, что именно мы внедряем и с чего разумно стартовать.

### Шаг 1. Пройти intake

Документ:

- [client-intake-template.md](./05-delivery/client-intake-template.md)

Что делаем:

- фиксируем why now;
- фиксируем business goals;
- фиксируем operating pain;
- определяем sponsor, owner и champions;
- выбираем draft scope первой волны.

Результат:

- понятен контекст проекта;
- понятны бизнес-ожидания;
- понятны роли и входная готовность клиента.

### Шаг 2. Зафиксировать operating model

Документы:

- [operating-model.md](./01-positioning/operating-model.md)
- [delegate-review-own.md](./01-positioning/delegate-review-own.md)
- [decision-rights.md](./01-positioning/decision-rights.md)

Что делаем:

- объясняем клиенту целевую рамку AI-native;
- раскладываем работу на `Delegate / Review / Own`;
- фиксируем, что остаётся только за человеком.

Результат:

- у проекта есть operating logic;
- AI не обсуждается как “ещё один чатик”;
- появляются границы ответственности.

### Шаг 3. Собрать Source of Truth

Документ:

- [source-of-truth-map.md](./02-source-of-truth/source-of-truth-map.md)

Что делаем:

- определяем systems of record;
- фиксируем data ownership;
- разделяем источник истины и производные витрины;
- проговариваем правила конфликтов данных.

Результат:

- есть базовая data discipline;
- skills не проектируются на хаотичных источниках.

### Шаг 4. Выбрать роли первой волны

Документ:

- [role-card-template.md](./03-skills/role-card-template.md)

Что делаем:

- выбираем `2-3` роли;
- описываем pain points;
- выделяем AI opportunity areas;
- определяем candidate skills.

Результат:

- понятна первая волна;
- scope не расползается по всей компании.

---

## Режим 2. Pilot Design Mode

Этот режим нужен, чтобы перевести discovery в управляемый пилот.

### Шаг 5. Описать skills

Документы:

- [SKILL-template.md](./03-skills/SKILL-template.md)
- [skill-spec-template.md](./03-skills/skill-spec-template.md)

Что делаем:

- описываем `3-5` skills первой волны;
- фиксируем входы, выходы, ограничения и dependencies;
- назначаем owner и reviewer;
- задаём режим исполнения.

Результат:

- skills описаны как управляемые capability units, а не как “идеи”.

### Шаг 6. Собрать pilot brief

Документ:

- [pilot-brief-template.md](./05-delivery/pilot-brief-template.md)

Что делаем:

- ограничиваем scope;
- подтверждаем роли и системы;
- фиксируем success criteria;
- фиксируем risks и exit rule.

Результат:

- пилот можно запускать без двусмысленности.

### Шаг 7. Провести через quality layer

Документы:

- [release-gates.md](./04-quality/release-gates.md)
- [eval-plan-template.md](./04-quality/eval-plan-template.md)

Что делаем:

- проверяем readiness;
- собираем eval plan;
- определяем thresholds;
- подтверждаем переход в пилот.

Результат:

- пилот не запускается “на энтузиазме”.

---

## Режим 3. Pilot Execution Mode

Этот режим нужен, чтобы показать эффект и принять управленческие решения.

### Шаг 8. Снять baseline

Документы:

- [metrics-shortlist.md](./07-metrics/metrics-shortlist.md)
- [baseline-template.md](./07-metrics/baseline-template.md)

Что делаем:

- выбираем бизнес-метрики;
- выбираем операционные метрики;
- фиксируем точку “до”.

Результат:

- можно честно сравнивать эффект, а не опираться на впечатления.

### Шаг 9. Подготовить adoption layer

Документы:

- [stakeholder-map-template.md](./06-adoption/stakeholder-map-template.md)
- [champion-model.md](./06-adoption/champion-model.md)
- [pilot-communication-template.md](./06-adoption/pilot-communication-template.md)
- [training-plan-template.md](./06-adoption/training-plan-template.md)

Что делаем:

- собираем stakeholder map;
- назначаем champions;
- готовим коммуникацию;
- готовим короткое role-based onboarding.

Результат:

- пилот не разваливается на сопротивлении.

### Шаг 10. Вести weekly review

Документы:

- [weekly-review-agenda.md](./05-delivery/weekly-review-agenda.md)
- [pilot-scorecard.md](./04-quality/pilot-scorecard.md)
- [before-after-template.md](./07-metrics/before-after-template.md)
- [executive-review-template.md](./05-delivery/executive-review-template.md)

Что делаем:

- обновляем scorecard;
- обсуждаем blockers;
- принимаем решения;
- готовим before/after;
- поднимаем leadership decisions.

Результат:

- проект движется по сигналам, а не по эмоциям.

---

## Самый короткий маршрут

Если нужно совсем коротко, Starter Kit используется так:

`intake -> operating model -> SoT -> role cards -> skills -> pilot brief -> release gates -> baseline -> pilot -> weekly review -> before/after -> executive review`

---

## С чего начинать на реальном клиенте

Если клиент уже был на воркшопе:

- начать с `intake`;
- сразу после этого пройти operating model;
- в ту же неделю собрать draft `SoT`;
- выбрать `2-3` роли и `3-5` skills;
- зафиксировать первую волну пилота.

Если клиент холодный:

- сначала workshop or diagnostic;
- потом только Starter Kit.

---

## Что не делать

- не пытаться заполнить весь пакет сразу;
- не начинать со skills до SoT;
- не стартовать пилот без baseline;
- не пускать новый сценарий в `Delegate`, если он ещё требует `Review`;
- не использовать kit как красивую методологию без owners и weekly rhythm.

---

## Практическое правило для coMind

На каждом новом проекте спрашиваем:

1. Intake пройден?
2. Operating model зафиксирован?
3. SoT map есть?
4. Roles первой волны выбраны?
5. Skills описаны?
6. Pilot brief подписан?
7. Baseline снят?
8. Weekly review поставлен?

Если на любой вопрос ответ “нет”, значит проект ещё не готов к нормальному запуску.

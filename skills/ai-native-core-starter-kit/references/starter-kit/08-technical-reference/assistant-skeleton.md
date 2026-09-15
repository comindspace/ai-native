# Assistant Skeleton

## Назначение

Это не кодовая реализация под конкретную платформу, а reference shape базового операционного ассистента.

## Базовые компоненты

### 1. Head instructions

Глобальный слой, который задаёт:

- роль ассистента;
- принципы работы;
- границы полномочий;
- правила эскалации;
- требования к прозрачности.

### 2. Skill layer

Набор отдельных role-based capabilities, оформленных как skills с:

- purpose;
- scope;
- inputs;
- outputs;
- restrictions;
- dependencies.

### 3. Source of truth access layer

Ассистент не должен “знать всё из воздуха”.

Он опирается на:

- knowledge base;
- approved systems;
- qualified exports;
- role-based access.

### 4. Quality and approval layer

Ассистент должен уметь:

- останавливаться;
- сигнализировать о нехватке данных;
- переводить задачи в `Review`;
- не выполнять запрещённые действия.

### 5. Logging layer

Минимально должны быть видны:

- что пытались сделать;
- на каких данных;
- какой был mode;
- было ли review;
- чем закончился сценарий.

## Платформенная оговорка

Эта схема общая для `Claude`, `Codex`, `Cursor` и других сред.

Платформенные pack’и позже адаптируют:

- формат инструкций;
- структуру workspace;
- tool wiring;
- memory conventions;
- agent UX.


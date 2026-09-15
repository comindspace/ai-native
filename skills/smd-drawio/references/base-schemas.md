# Каталог базовых СМД-схем

Каждая схема содержит: описание, когда применять, структуру элементов, layout и полный XML-пример.

---

## 1. Схема акта деятельности

### Описание
Базовая схема для **распредмечивания позиции** — "из чего состоит деятельность данного человека?" Раскладывает любую позицию на составляющие.

### Когда применять
- "Распредмети позицию X"
- "Из чего состоит деятельность X?"
- "Какие цели, инструменты, материалы и результаты у X?"
- Нужно понять, что конкретно делает человек в данной роли

### Элементы
| Элемент | Тип | Расположение |
|---------|-----|-------------|
| Позиция | Человечек | Центр |
| Знания, инструменты | Текст или прямоугольник | Слева от позиции |
| Целеполагание | Мишень | Справа от позиции |
| Материал | Прямоугольник | Левый нижний угол |
| Результат | Прямоугольник | Правый нижний угол |
| Стрелка М→Р | Сплошная | Материал → Результат |

### Layout
```
        З, И          Позиция        Целеполагание
      (слева)         (центр)          (справа)

      Материал ──────────────────→ Результат
      (лево-низ)                   (право-низ)
```

Размер области: ~600×300

### XML-пример (шаблон)

```xml
<!-- Заголовок -->
<mxCell id="title_1" value="Схема акта деятельности" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;fontSize=16;fontStyle=1" vertex="1" parent="1">
  <mxGeometry x="400" y="130" width="360" height="30" as="geometry" />
</mxCell>

<!-- Позиция (человечек) -->
<mxCell id="pos_1_grp" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="540" y="240" width="40" height="110" as="geometry" />
</mxCell>
<mxCell id="pos_1_head" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="pos_1_grp">
  <mxGeometry width="40" height="40" as="geometry" />
</mxCell>
<mxCell id="pos_1_body" value="" style="triangle;whiteSpace=wrap;html=1;rotation=90;" vertex="1" parent="pos_1_grp">
  <mxGeometry x="-10" y="60" width="60" height="40" as="geometry" />
</mxCell>

<!-- Знания, инструменты -->
<mxCell id="ki_1" value="Знания,&lt;div&gt;инструменты&lt;/div&gt;" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="350" y="200" width="130" height="30" as="geometry" />
</mxCell>

<!-- Целеполагание (мишень) -->
<mxCell id="goal_1_grp" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="664" y="211" width="64" height="67" as="geometry" />
</mxCell>
<mxCell id="goal_1_outer" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="goal_1_grp">
  <mxGeometry x="9.14" y="10.24" width="45.71" height="45.71" as="geometry" />
</mxCell>
<mxCell id="goal_1_inner" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="goal_1_grp">
  <mxGeometry x="18.29" y="19.54" width="27.43" height="27.43" as="geometry" />
</mxCell>
<mxCell id="goal_1_l" value="" style="endArrow=none;html=1;rounded=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" edge="1" parent="goal_1_grp" target="goal_1_inner">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint y="33.5" as="sourcePoint" />
  </mxGeometry>
</mxCell>
<mxCell id="goal_1_r" value="" style="endArrow=none;html=1;rounded=0;exitX=1;exitY=0.5;exitDx=0;exitDy=0;" edge="1" parent="goal_1_grp" source="goal_1_inner">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="64" y="33.31" as="targetPoint" />
  </mxGeometry>
</mxCell>
<mxCell id="goal_1_u" value="" style="endArrow=none;html=1;rounded=0;exitX=0.5;exitY=0;exitDx=0;exitDy=0;" edge="1" parent="goal_1_grp" source="goal_1_inner">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="32" as="targetPoint" />
  </mxGeometry>
</mxCell>
<mxCell id="goal_1_d" value="" style="endArrow=none;html=1;rounded=0;" edge="1" parent="goal_1_grp">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="31.93" y="67" as="sourcePoint" />
    <mxPoint x="32" y="47" as="targetPoint" />
  </mxGeometry>
</mxCell>

<!-- Подпись целеполагания -->
<mxCell id="goal_1_label" value="Целеполагание" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="630" y="180" width="130" height="30" as="geometry" />
</mxCell>

<!-- Материал -->
<mxCell id="mat_1" value="Материал" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="378.75" y="360" width="72.5" height="40" as="geometry" />
</mxCell>

<!-- Результат -->
<mxCell id="res_1" value="Результат" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="659.75" y="360" width="72.5" height="40" as="geometry" />
</mxCell>

<!-- Стрелка Материал → Результат -->
<mxCell id="edge_mr" style="rounded=0;orthogonalLoop=1;jettySize=auto;html=1;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" edge="1" parent="1" source="mat_1" target="res_1">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Пример конкретного заполнения
Для CTO:
- Знания, инструменты → "GitHub, AI-ассистент, архитектурные паттерны"
- Целеполагание → "Техническое лидерство, инновации"
- Материал → "Бизнес-требования, техдолг"
- Результат → "Работающая система, НМА"

---

## 2. Схема СРТ (система разделения труда)

### Описание
Показывает **кооперацию позиций** — как результат одной позиции становится материалом другой. Несколько актов деятельности, связанных потоками.

### Когда применять
- "Покажи систему разделения труда"
- "Кто что делает и кому передаёт?"
- "Как связаны позиции в команде?"
- Нужно понять кооперативную структуру

### Элементы
| Элемент | Тип | Расположение |
|---------|-----|-------------|
| Акт деятельности N | Контейнер | Горизонтально, слева направо |
| Позиция N | Человечек | Внутри каждого контейнера |
| Целеполагание N | Мишень | Внутри, справа от позиции |
| З, И N | Текст / прямоугольник | Внутри, слева от позиции |
| Материал N | Прямоугольник | Внутри, нижний левый |
| Результат N | Прямоугольник | Внутри, нижний правый |
| Связь Р₁→М₂ | Пунктирная стрелка | Результат₁ → Материал₂ |

### Layout
```
┌─────────────────────┐     ┌─────────────────────┐
│  Акт деятельности 1 │     │  Акт деятельности 2 │
│                     │     │                     │
│   З,И  [Поз]  Цел  │     │   З,И  [Поз]  Цел  │
│                     │     │                     │
│   М ──────────→ Р ──┤─ ─ ─┤→ М ──────────→ Р   │
└─────────────────────┘     └─────────────────────┘
```

Размер области: ~1000×550

### XML-пример (шаблон)

```xml
<!-- Заголовок -->
<mxCell id="title_1" value="Схема СРТ (системы разделения труда)" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;fontSize=16;fontStyle=1" vertex="1" parent="1">
  <mxGeometry x="355" y="120" width="410" height="30" as="geometry" />
</mxCell>

<!-- Контейнер: Акт деятельности 1 -->
<mxCell id="act_1" value="Акт деятельности 1" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;verticalAlign=top;" vertex="1" parent="1">
  <mxGeometry x="255" y="184" width="330" height="230" as="geometry" />
</mxCell>

<!-- Позиция 1 (внутри акта 1) -->
<mxCell id="pos_1_grp" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="405" y="234" width="40" height="110" as="geometry" />
</mxCell>
<mxCell id="pos_1_head" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="pos_1_grp">
  <mxGeometry width="40" height="40" as="geometry" />
</mxCell>
<mxCell id="pos_1_body" value="" style="triangle;whiteSpace=wrap;html=1;rotation=90;" vertex="1" parent="pos_1_grp">
  <mxGeometry x="-10" y="60" width="60" height="40" as="geometry" />
</mxCell>

<!-- Целеполагание 1 -->
<mxCell id="goal_1_grp" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="475" y="225" width="64" height="67" as="geometry" />
</mxCell>
<!-- (вложенные элементы мишени — аналогично схеме акта деятельности) -->

<!-- З, И для позиции 1 -->
<mxCell id="ki_1" value="З, И" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="285" y="238.5" width="72.5" height="40" as="geometry" />
</mxCell>

<!-- Материал 1 -->
<mxCell id="mat_1" value="М" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="285" y="344" width="72.5" height="40" as="geometry" />
</mxCell>

<!-- Результат 1 -->
<mxCell id="res_1" value="Р" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="475" y="344" width="72.5" height="40" as="geometry" />
</mxCell>

<!-- Стрелка М₁ → Р₁ -->
<mxCell id="edge_mr1" style="rounded=0;orthogonalLoop=1;jettySize=auto;html=1;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" edge="1" parent="1" source="mat_1" target="res_1">
  <mxGeometry relative="1" as="geometry" />
</mxCell>

<!-- Контейнер: Акт деятельности 2 -->
<mxCell id="act_2" value="Акт деятельности 2" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;verticalAlign=top;" vertex="1" parent="1">
  <mxGeometry x="600" y="320" width="330" height="230" as="geometry" />
</mxCell>

<!-- (Позиция 2, Целеполагание 2, З,И 2, Материал 2, Результат 2 — аналогично) -->

<!-- Связь Р₁ → М₂ (пунктирная, ортогональная) -->
<mxCell id="edge_srt" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;entryX=0;entryY=0.5;entryDx=0;entryDy=0;exitX=0.5;exitY=1;exitDx=0;exitDy=0;dashed=1;" edge="1" parent="1" source="res_1" target="mat_2">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

---

## 3. Схема "велосипеда" (шаг развития)

### Описание
Показывает **переход от текущего состояния (As Is) к целевому (To Be)**. "Велосипед" — потому что форма напоминает велосипед: два колеса (As Is и To Be) и общая верхушка.

### Когда применять
- "Покажи переход от X к Y"
- "Как перейти от текущего состояния к целевому?"
- "Схема шага развития"
- Нужно организовать изменения

### Элементы
| Элемент | Тип | Расположение |
|---------|-----|-------------|
| Верхушка | 3 расходящиеся линии | Верхний центр |
| Позиция (As Is) | Человечек (маленький) | Внутри верхушки, слева |
| Ситуация (As Is) | Эллипс (маленький) | Внутри верхушки, под позицией |
| Позиция' (To Be) | Человечек (маленький) | Внутри верхушки, справа |
| Ситуация' (To Be) | Эллипс (маленький) | Внутри верхушки, под позицией' |
| Позиция (As Is, большая) | Человечек | Нижний левый |
| Ситуация (As Is, большая) | Эллипс | Под большой позицией |
| Позиция' (To Be, большая) | Человечек | Нижний правый |
| Ситуация' (To Be, большая) | Эллипс | Под большой позицией' |
| Подписи As Is / To Be | Текст | Под каждой парой |
| Пунктирные стрелки | Пунктир | Между мини и большими парами |

### Layout
```
                 /\
                /  \
     [Поз]──Сит  Сит'──[Поз']    ← мини-версии
              /    \
             /      \
            /        \
    [Позиция]      [Позиция']     ← полные версии
    Ситуация       Ситуация'

      As Is          To Be
```

### Схема перехода от As Is к To Be (подтип)
Если нужно показать связи между мини-позициями:

```
     [Поз] ─ ─ → [Поз']          ← пунктир между позициями
     Сит  ─ ─ → Сит'             ← пунктир между ситуациями
```

---

## 4. Схема выхода в рефлексивную позицию

### Описание
Показывает ключевой приём СМД: выход из погружённости в деятельность "наверх" — в рефлексивную позицию, откуда ситуация видна целиком.

### Когда применять
- "Покажи выход в рефлексию"
- "Посмотри на ситуацию сверху"
- Есть проблемная ситуация — нужно осмыслить

### Элементы
| Элемент | Тип | Расположение |
|---------|-----|-------------|
| Позиция | Человечек | Центр-низ |
| Ситуация | Эллипс | Под позицией |
| Проблема | || + текст | Под ситуацией |
| Рефлексивная позиция (*) | Человечек + * | Верх-право |
| Экран (#) | Параллелограмм | Справа от рефлексивной позиции |
| Изогнутая стрелка | Пунктир, curved | От позиции к рефлексивной |
| Заголовок | Текст | Верх |

### Layout
```
    Схема выхода в рефлексивную позицию

              [Рефл.поз*]   [Экран #]
                  ↑ (пунктир, изогнутая)
                  │
              [Позиция]
              (Ситуация)
                ‖‖
              Проблема
```

### XML-пример

```xml
<!-- Заголовок -->
<mxCell id="title_1" value="Схема выхода в рефлексивную позицию" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;fontSize=16;fontStyle=1" vertex="1" parent="1">
  <mxGeometry x="390" y="40" width="360" height="30" as="geometry" />
</mxCell>

<!-- Ситуация -->
<mxCell id="sit_1" value="Ситуация" style="ellipse;whiteSpace=wrap;html=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="225" y="550" width="150" height="36" as="geometry" />
</mxCell>

<!-- Позиция (в деятельности) -->
<mxCell id="pos_1_grp" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="270" y="380" width="80" height="150" as="geometry" />
</mxCell>
<mxCell id="pos_1_head" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="pos_1_grp">
  <mxGeometry x="20" width="40" height="40" as="geometry" />
</mxCell>
<mxCell id="pos_1_body" value="" style="triangle;whiteSpace=wrap;html=1;rotation=90;" vertex="1" parent="pos_1_grp">
  <mxGeometry x="10" y="60" width="60" height="40" as="geometry" />
</mxCell>
<mxCell id="pos_1_label" value="Позиция" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="pos_1_grp">
  <mxGeometry y="120" width="80" height="30" as="geometry" />
</mxCell>

<!-- Рефлексивная позиция (*) -->
<mxCell id="rpos_outer" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="490" y="120" width="100" height="170" as="geometry" />
</mxCell>
<mxCell id="rpos_star" value="*" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=36;" vertex="1" parent="rpos_outer">
  <mxGeometry x="50" width="40" height="40" as="geometry" />
</mxCell>
<mxCell id="rpos_grp" value="" style="group" vertex="1" connectable="0" parent="rpos_outer">
  <mxGeometry y="20" width="100" height="150" as="geometry" />
</mxCell>
<mxCell id="rpos_head" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="rpos_grp">
  <mxGeometry x="20" width="40" height="40" as="geometry" />
</mxCell>
<mxCell id="rpos_body" value="" style="triangle;whiteSpace=wrap;html=1;rotation=90;" vertex="1" parent="rpos_grp">
  <mxGeometry x="10" y="60" width="60" height="40" as="geometry" />
</mxCell>
<mxCell id="rpos_label" value="Рефлексивная позиция" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="rpos_grp">
  <mxGeometry y="120" width="80" height="30" as="geometry" />
</mxCell>

<!-- Экран-заглушка (#) -->
<mxCell id="screen_1" value="#" style="shape=parallelogram;perimeter=parallelogramPerimeter;whiteSpace=wrap;html=1;fixedSize=1;fontFamily=Verdana;fontSize=36;fontStyle=1" vertex="1" parent="1">
  <mxGeometry x="600" y="130" width="120" height="150" as="geometry" />
</mxCell>

<!-- Подпись экрана -->
<mxCell id="screen_label" value="Схема ситуации" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="610" y="290" width="80" height="30" as="geometry" />
</mxCell>

<!-- Изогнутая пунктирная стрелка (выход в рефлексию) -->
<mxCell id="edge_refl" value="" style="endArrow=classic;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;curved=1;dashed=1;" edge="1" parent="1">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="380" y="470" as="sourcePoint" />
    <mxPoint x="530" y="290" as="targetPoint" />
    <Array as="points">
      <mxPoint x="530" y="470" />
    </Array>
  </mxGeometry>
</mxCell>

<!-- Проблема (||) -->
<mxCell id="prob_l1" value="" style="endArrow=none;html=1;rounded=0;" edge="1" parent="1">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="290" y="590" as="sourcePoint" />
    <mxPoint x="290" y="580" as="targetPoint" />
  </mxGeometry>
</mxCell>
<mxCell id="prob_l2" value="" style="endArrow=none;html=1;rounded=0;" edge="1" parent="1">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="296" y="590" as="sourcePoint" />
    <mxPoint x="296" y="580" as="targetPoint" />
  </mxGeometry>
</mxCell>
<mxCell id="prob_text" value="Проблема" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="260" y="590" width="60" height="30" as="geometry" />
</mxCell>
```

---

## 5. Позиционная коммуникация

### Описание
Показывает **несколько позиций**, обсуждающих общую проблему вокруг общего экрана/доски. Каждая позиция видит ситуацию по-своему.

### Когда применять
- "Покажи позиционную коммуникацию"
- "Как разные стейкхолдеры видят ситуацию?"
- "Покажи позиционную растяжку"
- Нужно организовать коллективное мышление

### Элементы
| Элемент | Тип | Расположение |
|---------|-----|-------------|
| Экран/Доска | Параллелограмм (большой) | Центр |
| Позиция 1..N | Человечки | Вокруг экрана |
| Стрелки | Сплошные, от позиций к экрану | От каждой позиции |
| Содержимое экрана | Различные элементы | Внутри параллелограмма |

### Layout
```
     [Поз1]        [Поз2]
       \              /
        \            /
    ┌──────────────────┐
    │    Экран/Доска    │  (параллелограмм)
    │   (содержимое)    │
    └──────────────────┘
        /            \
       /              \
     [Поз3]        [Поз4]
```

Размер области: ~800×600

---

## 6. Схема мыследеятельности (3 пояса)

### Описание
**Предельная схема** СМД. Три горизонтальных пояса: мыследействование (мД), мысль-коммуникация (М-К), чистое мышление (М). Показывает полную структуру коллективной мыследеятельности.

### Когда применять
- "Покажи структуру мыследеятельности"
- "Покажи три пояса"
- Нужен полный анализ ситуации на мета-уровне

### Элементы
| Элемент | Тип | Расположение |
|---------|-----|-------------|
| Пояс М (чистое мышление) | Горизонтальная область | Верх |
| Пояс М-К (мысль-коммуникация) | Горизонтальная область | Середина |
| Пояс мД (мыследействование) | Горизонтальная область | Низ |
| Позиции в мД | Человечки | В нижнем поясе |
| Тексты/высказывания | Облачки, стрелки | В среднем поясе |
| Схемы/понятия | Экраны, параллелограммы | В верхнем поясе |
| Рефлексивные связи | Вертикальные пунктирные стрелки | Между поясами |

### Layout
```
┌─────────────────────────────────────────┐
│ М (чистое мышление)                     │
│   [Экран/Схема]    [Экран/Схема]        │
├─────────────────────────────────────────┤
│ М-К (мысль-коммуникация)                │
│   [Поз1] ←─текст─→ [Поз2]              │
├─────────────────────────────────────────┤
│ мД (мыследействование)                  │
│   [Поз1]──М→Р    [Поз2]──М→Р           │
└─────────────────────────────────────────┘
```

Размер области: ~1200×800

---

## 7. Схема воспроизводства и трансляции культуры

### Описание
Показывает, как деятельность **воспроизводится** через трансляцию норм и культуры. Верхний слой (культура, нормы) передаётся в нижний слой (конкретная деятельность) через процессы нормирования и трансляции.

### Когда применять
- "Как передаются знания и нормы?"
- "Как воспроизводится деятельность?"
- "Покажи трансляцию культуры"
- Нужно организовать обучение, онбординг, передачу практик

### Элементы
| Элемент | Тип | Расположение |
|---------|-----|-------------|
| Слой культуры/норм | Горизонтальная область | Верх |
| Нормы, знания, стандарты | Прямоугольники, документы | В верхнем слое |
| Слой деятельности | Горизонтальная область | Низ |
| Позиции и ситуации | Человечки, эллипсы | В нижнем слое |
| Стрелки трансляции (↓) | Пунктирные, вниз | Нормы → Деятельность |
| Стрелки нормирования (↑) | Пунктирные, вверх | Деятельность → Нормы (рефлексия) |

### Layout
```
┌─────────────────────────────────────┐
│ Культура / Нормы                    │
│  [Норма1]  [Норма2]  [Стандарт]    │
│     │ (трансляция)    ↑ (нормирование)
├─────│─────────────────│─────────────┤
│ Деятельность          │             │
│  [Поз1]──Ситуация   [Поз2]         │
└─────────────────────────────────────┘
```

---

## 8. Схема ОТС (оргтехническая система)

### Описание
Показывает **управление**: управляющая позиция расположена "ортогонально" к управляемой деятельности. Управляющий видит систему как объект, задаёт нормы и цели, а управляемые позиции функционируют внутри системы.

### Когда применять
- "Покажи систему управления"
- "Как организована управляемая деятельность?"
- "Покажи оргтехническую схему"
- Нужно показать отношение управляющего к управляемым

### Элементы
| Элемент | Тип | Расположение |
|---------|-----|-------------|
| Управляющая позиция | Человечек (сверху, "ортогонально") | Верх |
| Управляемая система | Контейнер | Центр/Низ |
| Управляемые позиции | Человечки | Внутри контейнера |
| Орг. связи | Пунктирные стрелки вниз | Управляющий → Система |
| Нормативные связи | Пунктирные стрелки | Нормы → Позиции |

### Layout
```
         [Управляющий]
              │ (пунктир, нормирование)
              ▼
    ┌─────────────────────┐
    │   Управляемая       │
    │   система            │
    │  [Поз1] ── [Поз2]   │
    └─────────────────────┘
```

---

## Общие рекомендации по выбору схемы

| Вопрос | Схема |
|--------|-------|
| "Что делает X?" | Акт деятельности |
| "Как связаны X и Y в работе?" | СРТ |
| "Как перейти от A к B?" | Велосипед |
| "Как осмыслить проблему?" | Выход в рефлексию |
| "Как стейкхолдеры видят ситуацию?" | Позиционная коммуникация |
| "Какая структура мышления?" | Схема мыследеятельности (3 пояса) |
| "Как передаются знания?" | Воспроизводство и трансляция |
| "Как организовано управление?" | ОТС |

### Комбинирование схем
Схемы можно комбинировать на одной диаграмме:
- Акт деятельности + выход в рефлексию (позиция + рефлексивная позиция над ней)
- СРТ + велосипед (текущая кооперация → целевая кооперация)
- Позиционная коммуникация + ОТС (управляющий организует коммуникацию)

---

## 9. EPICON (экспериментальный примитив)

> **Статус:** экспериментальный. Введён Г. Стрюком (HSB MSU) для работы с фреймворками и методологиями. Не является стандартным элементом классической СМД, но совместим с её принципами.

### Описание
**EPICON** (эпистемический образ, epistemic icon) — сжатый образ, "zip-архив состояния". Это **смена рамки видения** + **корневая метафора**, порождающая новый способ смотреть на ситуацию. В отличие от CONCEPT (понятия), EPICON не разложим на формальные компоненты — он работает через **переживание** и **узнавание**.

### Когда применять
- При анализе фреймворков/методологий — для фиксации ключевых "сдвигов оптики"
- Когда автор вводит метафору, меняющую способ видения ("технический долг", "антихрупкость", "чёрный лебедь")
- Когда нужно показать: вот здесь у автора происходит **смена рамки**, а не просто новое понятие

### Элементы
| Элемент | Тип | Описание |
|---------|-----|----------|
| Рамка (frame shift) | Двойной прямоугольник (со сдвигом) | Визуализирует смену рамки видения |
| Корневая метафора | Текст внутри (курсив) | Ключевой образ, порождающий новую оптику |
| Стрелка "до" | Пунктирная, входящая | Исходный способ видения |
| Стрелка "после" | Сплошная, исходящая | Новый способ видения |

### Layout
```
   [Исходная рамка]
         │ (пунктир)
    ┌────┼──────────┐
    │ ┌──┼────────┐ │
    │ │  ▼        │ │
    │ │ «метафора»│ │    ← EPICON
    │ │           │ │
    │ └───────────┘ │
    └───────┬───────┘
            │ (сплошная)
            ▼
   [Новая рамка видения]
```

### Примеры
- **"Технический долг"** (Каннингем): EPICON, сменивший рамку с "плохой код" на "финансовое обязательство с процентами"
- **"Антихрупкость"** (Талеб): EPICON, сменивший рамку с "устойчивость к стрессу" на "выигрыш от стресса"
- **"Схема села на человека"** (Щедровицкий): EPICON, сменивший рамку с "человек использует схему" на "схема определяет человека"

---

## Общие рекомендации по выбору схемы

| Вопрос | Схема |
|--------|-------|
| "Что делает X?" | Акт деятельности |
| "Как связаны X и Y в работе?" | СРТ |
| "Как перейти от A к B?" | Велосипед |
| "Как осмыслить проблему?" | Выход в рефлексию |
| "Как стейкхолдеры видят ситуацию?" | Позиционная коммуникация |
| "Какая структура мышления?" | Схема мыследеятельности (3 пояса) |
| "Как передаются знания?" | Воспроизводство и трансляция |
| "Как организовано управление?" | ОТС |
| "Какая метафора меняет оптику?" | EPICON (эксп.) |

### Комбинирование схем
Схемы можно комбинировать на одной диаграмме:
- Акт деятельности + выход в рефлексию (позиция + рефлексивная позиция над ней)
- СРТ + велосипед (текущая кооперация → целевая кооперация)
- Позиционная коммуникация + ОТС (управляющий организует коммуникацию)

### Свободная схематизация
Если ситуация не укладывается ни в одну базовую схему — используй **примитивы** (позиции, ситуации, стрелки, экраны) для свободного конструирования. Главное:
1. Каждый элемент приписан к позиции
2. Есть заголовок
3. Пиктограммы снижают когнитивную нагрузку
4. Сплошное vs пунктирное различает уровни
5. Минимум пересечений

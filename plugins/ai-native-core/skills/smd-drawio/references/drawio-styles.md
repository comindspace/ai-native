# Стили draw.io для элементов СМД-схематизации

Стили извлечены из эталонных диаграмм `smd_sample_1..6.drawio`.

## XML-обёртка

```xml
<mxfile host="Electron" agent="Claude Code" version="27.0.5">
  <diagram name="Название диаграммы" id="DIAGRAM_ID">
    <mxGraphModel dx="1303" dy="835" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="827" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <!-- Элементы здесь -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Для больших диаграмм увеличивай `pageWidth`/`pageHeight` и соответственно `dx`/`dy`.

---

## Основные элементы

### Позиция (человечек) — базовый примитив

Группа из трёх элементов: голова (круг), тело (перевёрнутый треугольник), подпись. Это **ключевой** элемент СМД — функциональное место в деятельности.

```xml
<!-- Группа-контейнер -->
<mxCell id="pos_GROUP" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="X" y="Y" width="80" height="150" as="geometry" />
</mxCell>
<!-- Голова -->
<mxCell id="pos_HEAD" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="pos_GROUP">
  <mxGeometry x="20" width="40" height="40" as="geometry" />
</mxCell>
<!-- Тело -->
<mxCell id="pos_BODY" value="" style="triangle;whiteSpace=wrap;html=1;rotation=90;" vertex="1" parent="pos_GROUP">
  <mxGeometry x="10" y="60" width="60" height="40" as="geometry" />
</mxCell>
<!-- Подпись -->
<mxCell id="pos_LABEL" value="Название позиции" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="pos_GROUP">
  <mxGeometry y="120" width="80" height="30" as="geometry" />
</mxCell>
```

- **Размер группы:** 80×150
- Стрелки подключаются к `pos_BODY` (треугольник)
- Для длинных подписей можно увеличить width подписи до 100 и соответственно group width

### Позиция (уменьшенная) — для вложенных схем

Когда позиция помещается внутрь общей композиции (напр. на "велосипеде"), используется уменьшенный вариант:

```xml
<mxCell id="spos_GROUP" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="X" y="Y" width="40" height="80" as="geometry" />
</mxCell>
<mxCell id="spos_HEAD" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="spos_GROUP">
  <mxGeometry x="12.73" y="20.5" width="14.55" height="14.55" as="geometry" />
</mxCell>
<mxCell id="spos_BODY" value="" style="triangle;whiteSpace=wrap;html=1;rotation=90;" vertex="1" parent="spos_GROUP">
  <mxGeometry x="7.5" y="41.5" width="25" height="18" as="geometry" />
</mxCell>
<mxCell id="spos_LABEL" value="Позиция" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="spos_GROUP">
  <mxGeometry y="64" width="40" height="16" as="geometry" />
</mxCell>
```

- **Размер группы:** 40×80
- Используется в схемах "велосипеда" и других компактных схемах

### Рефлексивная позиция

Позиция + звёздочка (*). Обёрнуто в дополнительную группу для объединения * и человечка.

```xml
<!-- Внешняя группа (контейнер для * и позиции) -->
<mxCell id="rpos_OUTER" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="X" y="Y" width="100" height="170" as="geometry" />
</mxCell>
<!-- Звёздочка (*) — в правом верхнем углу внешней группы -->
<mxCell id="rpos_STAR" value="*" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=36;" vertex="1" parent="rpos_OUTER">
  <mxGeometry x="50" width="40" height="40" as="geometry" />
</mxCell>
<!-- Внутренняя группа (сам человечек) -->
<mxCell id="rpos_GROUP" value="" style="group" vertex="1" connectable="0" parent="rpos_OUTER">
  <mxGeometry y="20" width="100" height="150" as="geometry" />
</mxCell>
<!-- Голова -->
<mxCell id="rpos_HEAD" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="rpos_GROUP">
  <mxGeometry x="20" width="40" height="40" as="geometry" />
</mxCell>
<!-- Тело -->
<mxCell id="rpos_BODY" value="" style="triangle;whiteSpace=wrap;html=1;rotation=90;" vertex="1" parent="rpos_GROUP">
  <mxGeometry x="10" y="60" width="60" height="40" as="geometry" />
</mxCell>
<!-- Подпись -->
<mxCell id="rpos_LABEL" value="Рефлексивная позиция" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="rpos_GROUP">
  <mxGeometry y="120" width="80" height="30" as="geometry" />
</mxCell>
```

- **Размер внешней группы:** 100×170
- Звёздочка (*) fontSize=36 в правом верхнем углу
- Стрелки подключаются к `rpos_BODY`

### Целеполагание (мишень)

Два концентрических круга с четырьмя линиями-осями (перекрестие).

```xml
<!-- Группа мишени -->
<mxCell id="goal_GROUP" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="X" y="Y" width="64" height="67" as="geometry" />
</mxCell>
<!-- Внешний круг -->
<mxCell id="goal_OUTER" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="goal_GROUP">
  <mxGeometry x="9.14" y="10.24" width="45.71" height="45.71" as="geometry" />
</mxCell>
<!-- Внутренний круг -->
<mxCell id="goal_INNER" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="goal_GROUP">
  <mxGeometry x="18.29" y="19.54" width="27.43" height="27.43" as="geometry" />
</mxCell>
<!-- Линия влево -->
<mxCell id="goal_L" value="" style="endArrow=none;html=1;rounded=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" edge="1" parent="goal_GROUP" target="goal_INNER">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint y="33.5" as="sourcePoint" />
  </mxGeometry>
</mxCell>
<!-- Линия вправо -->
<mxCell id="goal_R" value="" style="endArrow=none;html=1;rounded=0;exitX=1;exitY=0.5;exitDx=0;exitDy=0;" edge="1" parent="goal_GROUP" source="goal_INNER">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="64" y="33.31" as="targetPoint" />
  </mxGeometry>
</mxCell>
<!-- Линия вверх -->
<mxCell id="goal_U" value="" style="endArrow=none;html=1;rounded=0;exitX=0.5;exitY=0;exitDx=0;exitDy=0;" edge="1" parent="goal_GROUP" source="goal_INNER">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="32" as="targetPoint" />
  </mxGeometry>
</mxCell>
<!-- Линия вниз -->
<mxCell id="goal_D" value="" style="endArrow=none;html=1;rounded=0;" edge="1" parent="goal_GROUP">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="31.93" y="67" as="sourcePoint" />
    <mxPoint x="32" y="47" as="targetPoint" />
  </mxGeometry>
</mxCell>
```

- **Размер группы:** 64×67
- Располагается справа от позиции (обычно на 15-20px правее и немного выше)

### Ситуация

Горизонтальный эллипс.

```xml
<mxCell id="sit_ID" value="Название ситуации" style="ellipse;whiteSpace=wrap;html=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="150" height="36" as="geometry" />
</mxCell>
```

- **Стандартный размер:** 150×36
- Для уменьшенных вариантов (на велосипеде): 90×24 или 90×28

### Экран / Доска (параллелограмм)

Пространство мышления — внешний экран, куда позиция выносит свои схемы.

```xml
<mxCell id="screen_ID" value="" style="shape=parallelogram;perimeter=parallelogramPerimeter;whiteSpace=wrap;html=1;fixedSize=1;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="W" height="H" as="geometry" />
</mxCell>
```

- **Размер:** варьируется (120×150 для малого, до 530×258 для большого)
- Пустой value="" — экран с содержимым внутри (другие элементы геометрически размещаются поверх)
- С содержимым как надписью — для простых экранов

### Схема-заглушка (нераспредмеченная схема)

Параллелограмм со знаком "#" — показывает, что здесь есть самостоятельная схема, но она не распредмечена.

```xml
<mxCell id="stub_ID" value="#" style="shape=parallelogram;perimeter=parallelogramPerimeter;whiteSpace=wrap;html=1;fixedSize=1;fontFamily=Verdana;fontSize=36;fontStyle=1" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="120" height="150" as="geometry" />
</mxCell>
```

- **Размер:** 120×150
- fontSize=36 для крупного "#"
- fontStyle=1 (bold)

---

## Дополнительные элементы

### Материал / Результат (прямоугольник)

```xml
<mxCell id="mat_ID" value="Материал" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="72.5" height="40" as="geometry" />
</mxCell>
```

- **Размер:** 72.5×40 (стандарт) или до 260×40 (для длинных подписей)
- Материал и Результат визуально идентичны — различаются положением и подписью
- В акте деятельности: Материал слева внизу, Результат справа внизу

### Знания / Инструменты (текстовая метка)

```xml
<mxCell id="ki_ID" value="Знания,&lt;div&gt;инструменты&lt;/div&gt;" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="130" height="30" as="geometry" />
</mxCell>
```

- Без рамки (чистый текст)
- В акте деятельности: слева от позиции
- Для конкретных описаний — используется прямоугольник `rounded=0` с конкретными З и И

### Облачко мысли (индивидуальное "думание")

```xml
<mxCell id="cloud_ID" value="Размышление" style="whiteSpace=wrap;html=1;shape=mxgraph.basic.cloud_callout;fontFamily=Verdana;verticalAlign=middle;spacingTop=-20;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="140" height="90" as="geometry" />
</mxCell>
```

- **Размер:** 140×90
- spacingTop=-20 — сдвигает текст вверх внутри облачка (т.к. хвостик внизу)
- Располагается рядом с позицией, обычно сверху-справа

### Документ / Артефакт

```xml
<mxCell id="doc_ID" value="Название документа" style="shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;size=16;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="80" height="100" as="geometry" />
</mxCell>
```

- **Размер:** 80×100
- size=16 — размер загнутого уголка

### ML-модель / AI / Спецэлемент (шестиугольник)

```xml
<mxCell id="ai_ID" value="AI-ассистент" style="shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;fixedSize=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="110" height="50" as="geometry" />
</mxCell>
```

- **Размер:** 110×50 (малый) или 200×70 (большой)

### Система / Контейнер (скруглённый прямоугольник с заголовком)

```xml
<mxCell id="sys_ID" value="Акт деятельности 1" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;verticalAlign=top;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="330" height="230" as="geometry" />
</mxCell>
```

- verticalAlign=top — заголовок сверху
- Для СРТ используется как контейнер акта деятельности

### Проблема (двойная вертикальная линия + текст)

Обозначает разрыв в деятельности — место, где возникла проблемная ситуация.

```xml
<!-- Линия 1 -->
<mxCell id="prob_L1" value="" style="endArrow=none;html=1;rounded=0;" edge="1" parent="1">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="X" y="Y+10" as="sourcePoint" />
    <mxPoint x="X" y="Y" as="targetPoint" />
  </mxGeometry>
</mxCell>
<!-- Линия 2 (сдвинута на 6px вправо) -->
<mxCell id="prob_L2" value="" style="endArrow=none;html=1;rounded=0;" edge="1" parent="1">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="X+6" y="Y+10" as="sourcePoint" />
    <mxPoint x="X+6" y="Y" as="targetPoint" />
  </mxGeometry>
</mxCell>
<!-- Подпись -->
<mxCell id="prob_TEXT" value="Проблема" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X-27" y="Y+10" width="60" height="30" as="geometry" />
</mxCell>
```

- Две короткие параллельные вертикальные линии
- Подпись "Проблема" снизу
- Обычно размещается под ситуацией

### Заголовок схемы

```xml
<mxCell id="title_ID" value="Название схемы" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;fontSize=16;fontStyle=1" vertex="1" parent="1">
  <mxGeometry x="X" y="40" width="360" height="30" as="geometry" />
</mxCell>
```

- fontSize=16, fontStyle=1 (bold)
- Размещается сверху по центру диаграммы

---

## Соединительные линии (Edges)

### Сплошная стрелка (деятельность, поток)

```xml
<mxCell id="edge_ID" style="rounded=0;orthogonalLoop=1;jettySize=auto;html=1;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Сплошная стрелка с подписью

```xml
<mxCell id="edge_ID" value="Запрос" style="endArrow=classic;html=1;rounded=0;fontFamily=Verdana;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry width="50" height="50" relative="1" as="geometry" />
</mxCell>
```

### Пунктирная стрелка (мета-переход, рефлексия)

```xml
<mxCell id="edge_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;dashed=1;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Изогнутая пунктирная стрелка (рефлексивный выход)

Для стрелки от позиции к рефлексивной позиции — curved=1, edgeStyle=orthogonalEdgeStyle:

```xml
<mxCell id="edge_ID" value="" style="endArrow=classic;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;curved=1;dashed=1;" edge="1" parent="1">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="SRC_X" y="SRC_Y" as="sourcePoint" />
    <mxPoint x="TGT_X" y="TGT_Y" as="targetPoint" />
    <Array as="points">
      <mxPoint x="BEND_X" y="BEND_Y" />
    </Array>
  </mxGeometry>
</mxCell>
```

- Используется для выхода в рефлексивную позицию
- Промежуточная точка (Array/points) создаёт L-образный изгиб
- dashed=1 — пунктир для мета-перехода

### Пунктирная стрелка без наконечника (связь СРТ)

```xml
<mxCell id="edge_ID" style="rounded=0;orthogonalLoop=1;jettySize=auto;html=1;dashed=1;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Линия без наконечника (структурная связь)

```xml
<mxCell id="edge_ID" value="" style="endArrow=none;html=1;rounded=0;" edge="1" parent="1">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="X1" y="Y1" as="sourcePoint" />
    <mxPoint x="X2" y="Y2" as="targetPoint" />
  </mxGeometry>
</mxCell>
```

### Двунаправленная стрелка

```xml
<mxCell id="edge_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;startArrow=classic;startFill=1;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Кривая стрелка (свободная форма)

```xml
<mxCell id="edge_ID" value="" style="curved=1;endArrow=classic;html=1;rounded=0;" edge="1" parent="1">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="X1" y="Y1" as="sourcePoint" />
    <mxPoint x="X2" y="Y2" as="targetPoint" />
    <Array as="points">
      <mxPoint x="MID_X" y="MID_Y" />
    </Array>
  </mxGeometry>
</mxCell>
```

---

## Правила размещения (Layout)

### Общие правила
- **Заголовок** — сверху по центру, y=40
- **Позиции** — ближе к своим объектам (ситуации, материалам)
- **Рефлексивные позиции** — выше обычных позиций (рефлексия = "над" деятельностью)
- **Экраны/доски** — рядом с рефлексивными позициями
- **Ситуации** — обычно ниже позиций
- **Проблемы** — ниже ситуаций
- **Минимизация пересечений стрелок** — основной критерий
- **Отступы** ≥20px между элементами
- **Шрифт:** Verdana для всех надписей

### Порядок элементов в XML
1. Контейнеры и группировки (задний план) — ПЕРВЫМИ
2. Экраны/доски — ПОСЛЕ контейнеров
3. Объекты внутри экранов
4. Позиции
5. Ситуации
6. Стрелки — ПОСЛЕДНИМИ

### Управление точками привязки стрелок
Точки: `X=0` (лево), `X=0.5` (центр), `X=1` (право); `Y=0` (верх), `Y=0.5` (середина), `Y=1` (низ).

```
exitX=0.5;exitY=0    — выход сверху по центру
entryX=0.5;entryY=1  — вход снизу по центру
exitX=1;exitY=0.5    — выход справа по середине
```

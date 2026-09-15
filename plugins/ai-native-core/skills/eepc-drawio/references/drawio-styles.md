# Стили draw.io для eEPC-элементов

Все стили извлечены из эталонной диаграммы `eepc_sample_1.drawio`.

## XML-обёртка

```xml
<mxfile host="Electron" agent="Claude Code" version="27.0.5">
  <diagram name="eEPC" id="DIAGRAM_ID">
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

Для больших диаграмм увеличивай `pageHeight` (кратно 827) и `dy`.

## Элементы

### Событие (Event)

Розовый шестиугольник. Начало и конец процесса, результат функции.

```xml
<mxCell id="ID" value="Текст события" style="shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;fixedSize=1;fillColor=#f8cecc;strokeColor=#b85450;fontFamily=Verdana;spacingLeft=10;spacingRight=10;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="200" height="70" as="geometry" />
</mxCell>
```

- **Размер:** 200×70 (ширину можно увеличить для длинного текста)
- **Fill:** `#f8cecc` | **Stroke:** `#b85450`

### Функция (Function)

Зелёный прямоугольник со скруглёнными углами.

```xml
<mxCell id="ID" value="Текст функции" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontFamily=Verdana;spacingLeft=10;spacingRight=10;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="200" height="70" as="geometry" />
</mxCell>
```

- **Размер:** 200×70 (или 150×70 для параллельных веток)
- **Fill:** `#d5e8d4` | **Stroke:** `#82b366`
- **Spacing:** `spacingLeft=10;spacingRight=10;` — отступ текста от границ элемента

### Точка ветвления (Gateway: XOR / OR / AND)

Круг с текстом типа ветвления.

```xml
<mxCell id="ID" value="XOR" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="40" height="40" as="geometry" />
</mxCell>
```

- **Размер:** 40×40 (фиксированный)
- **Текст:** `XOR`, `OR` или `AND`

### Роль (Role)

Жёлтый эллипс с иконкой-человечком (линия от нижнего-левого к верхнему-левому краю).

Роль оформляется как группа из двух элементов:

```xml
<!-- Группа-контейнер -->
<mxCell id="GROUP_ID" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="X" y="Y" width="170" height="80" as="geometry" />
</mxCell>
<!-- Эллипс роли -->
<mxCell id="ROLE_ID" value="Название роли" style="ellipse;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;spacingLeft=20;fontFamily=Verdana;" vertex="1" parent="GROUP_ID">
  <mxGeometry width="170" height="80" as="geometry" />
</mxCell>
<!-- Иконка человечка (линия) -->
<mxCell id="ICON_ID" value="" style="endArrow=none;html=1;rounded=0;entryX=0;entryY=0;entryDx=0;entryDy=0;exitX=0;exitY=1;exitDx=0;exitDy=0;strokeColor=light-dark(#d6b656, #ededed);" edge="1" parent="GROUP_ID" source="ROLE_ID" target="ROLE_ID">
  <mxGeometry width="50" height="50" relative="1" as="geometry">
    <mxPoint x="-90" y="200" as="sourcePoint" />
    <mxPoint x="-40" y="150" as="targetPoint" />
  </mxGeometry>
</mxCell>
```

- **Размер группы:** 170×80
- **Fill:** `#fff2cc` | **Stroke:** `#d6b656`
- **Соединение с функцией:** без стрелок (`endArrow=none;startFill=0;`)

### Информационная система (Information System)

Голубой прямоугольник с вертикальными полосками по бокам (shape=process).

```xml
<mxCell id="ID" value="Название системы" style="shape=process;whiteSpace=wrap;html=1;backgroundOutline=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontFamily=Verdana;spacingLeft=25;spacingRight=25;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="160" height="60" as="geometry" />
</mxCell>
```

- **Размер:** 160×60
- **Fill:** `#dae8fc` | **Stroke:** `#6c8ebf`
- **Spacing:** `spacingLeft=25;spacingRight=25;` — увеличенный отступ, т.к. shape=process имеет внутренние вертикальные границы (~15% от ширины), отступ считается от внешнего края

### Документ (Document)

Голубой элемент с волнистым нижним краем.

```xml
<mxCell id="ID" value="Название документа" style="shape=document;whiteSpace=wrap;html=1;boundedLbl=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="160" height="70" as="geometry" />
</mxCell>
```

- **Размер:** 160×70
- **Fill:** `#dae8fc` | **Stroke:** `#6c8ebf`

## Соединительные линии (Edges)

### Основной поток (событие <-> функция, функция <-> точка ветвления)

```xml
<mxCell id="EDGE_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Роль -> Функция (без стрелок)

```xml
<mxCell id="EDGE_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=none;startFill=0;" edge="1" parent="1" source="ROLE_ID" target="FUNCTION_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Документ/ИС -> Функция (стрелка = вход, используется при выполнении)

```xml
<mxCell id="EDGE_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="DOC_OR_IS_ID" target="FUNCTION_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Функция -> Документ/ИС (стрелка = выход, порождается при выполнении)

```xml
<mxCell id="EDGE_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="FUNCTION_ID" target="DOC_OR_IS_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Двунаправленная связь (Документ/ИС <-> Функция)

```xml
<mxCell id="EDGE_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;startArrow=classic;startFill=1;" edge="1" parent="1" source="FUNCTION_ID" target="DOC_OR_IS_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

## Правила размещения (Layout)

- **Вертикальная ось:** основной поток идёт сверху вниз
- **Интервал между элементами основного потока:** ~35px по вертикали
- **Роли:** размещаются справа или слева от функций
- **Документы и ИС:** размещаются слева от функций (или справа, если роль уже справа)
- **Точки ветвления:** центрируются по оси основного потока
- **Ветви XOR/OR:** расходятся влево и вправо от точки ветвления
- **Центр основного потока:** примерно x=480–580 (при pageWidth=1169)

### Горизонтальное выравнивание (критично для чистых стрелок)

Чтобы горизонтальные стрелки (роль↔функция, документ↔функция) были **прямыми без изломов**, дополнительные элементы должны быть выровнены по вертикальному центру с функцией, к которой они привязаны:

- Если функция: `y=Y, h=70` → центр по y = `Y + 35`
- Документ (h=70): должен иметь `y = Y` (тот же y, что и функция)
- ИС (h=60): должен иметь `y = Y + 5` (чтобы центры совпали: `Y+5+30 = Y+35`)
- Роль (h=80 в группе): должен иметь `y = Y - 5` (чтобы центры совпали: `Y-5+40 = Y+35`)

**Правило:** если два элемента соединены горизонтальной стрелкой, их вертикальные центры ДОЛЖНЫ совпадать. Иначе orthogonalEdgeStyle создаст лишний излом.

### Маршрутизация ветвлений (XOR/OR/AND)

Стрелки от точки ветвления к ветвям должны иметь **ровно один угол** (L-образный маршрут):

- **Левая ветвь:** выход из ЛЕВОЙ стороны точки ветвления (`exitX=0;exitY=0.5`), вход в верх события (`entryX=0.5;entryY=0`). Маршрут: горизонтально влево → вертикально вниз.
- **Правая ветвь:** выход из ПРАВОЙ стороны (`exitX=1;exitY=0.5`), вход в верх события (`entryX=0.5;entryY=0`). Маршрут: горизонтально вправо → вертикально вниз.

Для чистого L-маршрута первый элемент ветви должен быть существенно ниже точки ветвления (зазор ≥75px от центра точки ветвления до верхнего края первого элемента ветви). Это даёт достаточно места для горизонтального сегмента.

**НЕ использовать** `exitX=0.5;exitY=1` (выход снизу) для ветвлений — это создаёт двойной излом (вниз → в сторону → вниз).

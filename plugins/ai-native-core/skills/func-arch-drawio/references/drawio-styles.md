# Стили draw.io для элементов функциональной архитектуры

Стили извлечены из эталонных диаграмм `func-arch_sample_1..5.drawio`.

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

## Основные элементы

### Роль (Person) — вариант «круг + треугольник»

Группа из трёх элементов: голова (круг), тело (перевёрнутый треугольник), подпись.

```xml
<!-- Группа-контейнер -->
<mxCell id="GROUP_ID" value="" style="group" vertex="1" connectable="0" parent="1">
  <mxGeometry x="X" y="Y" width="80" height="150" as="geometry" />
</mxCell>
<!-- Голова -->
<mxCell id="HEAD_ID" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="GROUP_ID">
  <mxGeometry x="20" width="40" height="40" as="geometry" />
</mxCell>
<!-- Тело -->
<mxCell id="BODY_ID" value="" style="triangle;whiteSpace=wrap;html=1;rotation=90;" vertex="1" parent="GROUP_ID">
  <mxGeometry x="10" y="60" width="60" height="40" as="geometry" />
</mxCell>
<!-- Подпись -->
<mxCell id="LABEL_ID" value="Название роли" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="GROUP_ID">
  <mxGeometry y="120" width="80" height="30" as="geometry" />
</mxCell>
```

- **Размер группы:** 80×150
- Стрелки подключаются к BODY_ID (треугольнику) или к HEAD_ID (кругу)

### Система (System) — контейнер

Скруглённый прямоугольник с заголовком сверху. Содержит вложенные функции.

```xml
<mxCell id="ID" value="Название системы" style="rounded=1;whiteSpace=wrap;html=1;arcSize=6;verticalAlign=top;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="W" height="H" as="geometry" />
</mxCell>
```

- **arcSize:** 2–8 (чем больше контейнер, тем меньше arcSize, чтобы скругление не было слишком заметным)
- **verticalAlign:** `top` — заголовок сверху, место для вложенных элементов ниже
- **Без verticalAlign** (или `middle`) — для верхнеуровневых схем без вложенных элементов
- Размер подбирается, чтобы вложенные элементы помещались с отступами ≥20px

#### Система с цветной границей (акцент на свою систему)

```xml
<mxCell id="ID" value="Название" style="rounded=1;whiteSpace=wrap;html=1;fillColor=default;strokeColor=#97D077;strokeWidth=1;fontStyle=1;verticalAlign=top;fontSize=14;arcSize=8;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="W" height="H" as="geometry" />
</mxCell>
```

- **strokeColor:** `#97D077` (зелёный) — для «своих» систем
- **fontStyle:** `1` = bold
- **fontSize:** `14` — крупнее для контейнеров верхнего уровня

### Функциональный блок (Function)

Прямоугольник без скругления. Текст по центру.

```xml
<mxCell id="ID" value="Название функции" style="rounded=0;whiteSpace=wrap;html=1;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="W" height="50" as="geometry" />
</mxCell>
```

- **Высота:** 50–60px (одинаковая для всех функций на одной диаграмме)
- **Ширина:** подбирается под текст (120–220px)

#### Функция с цветной заливкой

Для визуального разделения групп функций можно использовать заливку:

```xml
<!-- Зелёная (основная система) -->
<mxCell id="ID" value="..." style="rounded=1;whiteSpace=wrap;html=1;fillColor=#BFE7AA;strokeColor=#82b366;strokeWidth=1;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="120" height="60" as="geometry" />
</mxCell>

<!-- Голубая (вспомогательная/аналитическая) -->
<mxCell id="ID" value="..." style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=1;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="120" height="40" as="geometry" />
</mxCell>
```

### Группировка (Grouping)

Объединяет системы логически (орг. единица, контур безопасности, территория).

```xml
<!-- Пунктирная граница (виртуальная/условная граница) -->
<mxCell id="ID" value="Название группы" style="rounded=1;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 8;arcSize=7;verticalAlign=top;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="W" height="H" as="geometry" />
</mxCell>

<!-- Сплошная граница (физическая граница / надсистема) -->
<mxCell id="ID" value="Название группы" style="rounded=1;whiteSpace=wrap;html=1;arcSize=7;verticalAlign=top;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="W" height="H" as="geometry" />
</mxCell>
```

- Пунктирная: `dashed=1;dashPattern=8 8` — виртуальная/условная граница (контур безопасности, организация)
- Сплошная — физическая граница или надсистема
- **Надпись сверху или снизу:** `verticalAlign=top` (по умолчанию) или `verticalAlign=bottom` — выбирать так, чтобы надпись не пересекалась со стрелками. Например, если стрелки входят в группировку сверху, надпись лучше разместить снизу

## Дополнительные элементы

### База данных (Database)

```xml
<mxCell id="ID" value="" style="shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="120" height="75" as="geometry" />
</mxCell>
<!-- Подпись под БД -->
<mxCell id="LABEL_ID" value="Название БД" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y+80" width="120" height="30" as="geometry" />
</mxCell>
```

### Облако / Интернет (Cloud)

```xml
<mxCell id="ID" value="" style="ellipse;shape=cloud;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="155" height="140" as="geometry" />
</mxCell>
<!-- Подпись -->
<mxCell id="LABEL_ID" value="Открытые источники (Интернет)" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y+145" width="155" height="30" as="geometry" />
</mxCell>
```

- С текстом внутри: `value="Облачная LLM"` + `fontFamily=Verdana;`

### Документ / Артефакт (Note)

```xml
<mxCell id="ID" value="Название документа" style="shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;size=7;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="150" height="43" as="geometry" />
</mxCell>
```

### Шестиугольник (ML-модель, спецэлемент)

```xml
<mxCell id="ID" value="Название модели" style="shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;fixedSize=1;size=20;fontFamily=Verdana;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="140" height="60" as="geometry" />
</mxCell>
```

### Хранилище данных (Internal Storage)

```xml
<mxCell id="ID" value="Данные" style="shape=internalStorage;whiteSpace=wrap;html=1;backgroundOutline=1;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="125" height="75" as="geometry" />
</mxCell>
```

## «Множественные» объекты

Три перекрывающиеся фигуры с небольшим смещением (dx=10, dy=10). Только передняя фигура содержит надпись.

```xml
<mxCell id="ID_1" value="" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="X" y="Y" width="120" height="60" as="geometry" />
</mxCell>
<mxCell id="ID_2" value="" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="X+10" y="Y+10" width="120" height="60" as="geometry" />
</mxCell>
<mxCell id="ID_3" value="Название" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="X+20" y="Y+20" width="120" height="60" as="geometry" />
</mxCell>
```

- Стрелки подключаются только к переднему элементу (ID_3)
- Форма может быть любой (rect, hexagon, cylinder и т.д.)

## Соединительные линии (Edges)

### Стандартная стрелка

```xml
<mxCell id="EDGE_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Двунаправленная стрелка

```xml
<mxCell id="EDGE_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;startArrow=classic;startFill=1;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Стрелка с точками входа/выхода

Для управления маршрутом стрелки — указать точки на границах элементов:

```xml
<mxCell id="EDGE_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

Точки: `X=0` (лево), `X=0.5` (центр), `X=1` (право); `Y=0` (верх), `Y=0.5` (середина), `Y=1` (низ).

### Стрелка с промежуточными точками маршрута

Для сложных маршрутов — массив `Array` с промежуточными точками:

```xml
<mxCell id="EDGE_ID" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="SOURCE_ID" target="TARGET_ID">
  <mxGeometry relative="1" as="geometry">
    <Array as="points">
      <mxPoint x="400" y="200" />
      <mxPoint x="400" y="350" />
    </Array>
  </mxGeometry>
</mxCell>
```

## Правила размещения (Layout)

- **Роли** размещаются по краям диаграммы (сверху, снизу, по бокам) — ближе к системам, с которыми взаимодействуют
- **Системы-контейнеры** размещаются в центре, содержат функции внутри
- **Вложенные элементы** должны иметь отступы ≥20px от границ контейнера (сверху ≥40px, чтобы заголовок не перекрывался)
- **Функции** внутри контейнера выравниваются в сетку (строки и/или столбцы)
- **Группировки** являются самыми нижними слоями — на заднем плане
- **Минимизация пересечений стрелок** — основной критерий размещения. Если роль A работает с функциями слева, роль B — с функциями справа, разнести соответственно
- **Интервал** между элементами ≥20px
- **Шрифт:** Verdana для всех надписей

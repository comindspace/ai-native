#!/usr/bin/env python3
"""
Functional Architecture Layout Engine for draw.io
==================================================
Produces well-routed functional-architecture diagrams:
  1. Zone-based node placement (top / left / center / right / bottom)
  2. Barycenter crossing-minimisation within each zone
  3. A*-based orthogonal edge routing that avoids node bounding boxes

Usage
-----
    from layout_engine import Node, Edge, LayoutEngine
    engine = LayoutEngine(nodes, edges, canvas_w=1800, canvas_h=1200)
    engine.run()
    xml = engine.to_drawio_xml("Page name")
    with open("output.drawio", "w", encoding="utf-8") as f:
        f.write(xml)
"""

from __future__ import annotations
import heapq
import math
import uuid
import html
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Tuning constants
# ──────────────────────────────────────────────────────────────────────────────
GRID      = 20    # routing grid resolution (px) – coarser = faster
MARGIN    = 18    # clearance around node rects during routing
TURN_COST = 40    # A* penalty per direction change
ZONE_GAP  = 20    # gap between sibling nodes in a zone

# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Rect:
    x: int; y: int; w: int; h: int

    @property
    def x2(self): return self.x + self.w
    @property
    def y2(self): return self.y + self.h
    @property
    def cx(self): return self.x + self.w // 2
    @property
    def cy(self): return self.y + self.h // 2

    def expanded(self, m: int) -> Rect:
        return Rect(self.x - m, self.y - m, self.w + 2*m, self.h + 2*m)

    def contains_pt(self, px: int, py: int) -> bool:
        return self.x <= px <= self.x2 and self.y <= py <= self.y2


@dataclass
class Node:
    id: str
    label: str
    zone: str         # 'top' | 'left' | 'center' | 'right' | 'bottom'
    node_type: str    # 'system' | 'role'
    role_side: str = ''      # for roles: same value as zone where they live
    w: int = 170
    h: int = 65
    style_extra: str = ''    # extra draw.io style overrides
    rect: Optional[Rect] = field(default=None, compare=False, repr=False)
    _order: int = field(default=0, compare=False, repr=False)


@dataclass
class Edge:
    src: str
    tgt: str
    bidirectional: bool = False
    waypoints: List[Tuple[int, int]] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Layout engine
# ──────────────────────────────────────────────────────────────────────────────

class LayoutEngine:

    # Horizontal zones: nodes arranged left→right
    H_ZONES = ('top', 'bottom')
    # Vertical zones: nodes arranged top→bottom
    V_ZONES = ('left', 'right')

    def __init__(
        self,
        nodes: List[Node],
        edges: List[Edge],
        canvas_w: int = 1800,
        canvas_h: int = 1200,
    ):
        self.nodes: Dict[str, Node] = {n.id: n for n in nodes}
        self.edges = edges
        self.CW = canvas_w
        self.CH = canvas_h

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Full pipeline: place → minimise crossings → route edges."""
        self._initial_placement()
        self._minimise_crossings()
        self._reassign_positions()
        self._place_roles()
        self._route_edges()

    def to_drawio_xml(self, page_name: str = "Функциональная архитектура") -> str:
        cells = []
        for n in self.nodes.values():
            if n.node_type == 'system':
                cells.append(self._system_xml(n))
        for n in self.nodes.values():
            if n.node_type == 'role':
                cells.append(self._role_xml(n))
        for e in self.edges:
            cells.append(self._edge_xml(e))

        body = "".join(cells)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<mxfile host="Electron" agent="Claude Code" version="27.0.5">\n'
            f'  <diagram name="{html.escape(page_name)}" id="{self._uid()}">\n'
            f'    <mxGraphModel dx="1303" dy="835" grid="1" gridSize="10" guides="1"'
            f' tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1"'
            f' pageWidth="{self.CW}" pageHeight="{self.CH}" math="0" shadow="0">\n'
            '      <root>\n'
            '        <mxCell id="0" />\n'
            '        <mxCell id="1" parent="0" />\n'
            + body +
            '      </root>\n'
            '    </mxGraphModel>\n'
            '  </diagram>\n'
            '</mxfile>\n'
        )

    # ── Step 1: initial placement ───────────────────────────────────────────────

    def _initial_placement(self) -> None:
        """Assign Rect to every system node using simple zone rules."""
        zones: Dict[str, List[Node]] = defaultdict(list)
        for n in self.nodes.values():
            if n.node_type == 'system':
                zones[n.zone].append(n)

        # ── top (horizontal, centred) ──
        self._layout_h(zones.get('top', []), anchor_y=200)

        # ── left (vertical) ──
        self._layout_v(zones.get('left', []), anchor_x=150)

        # ── center (single node, centred on canvas) ──
        for n in zones.get('center', []):
            n.rect = Rect(self.CW // 2 - n.w // 2, self.CH // 2 - n.h // 2, n.w, n.h)

        # ── right (vertical, right side) ──
        self._layout_v(zones.get('right', []), anchor_x=self.CW - 150 - 170)

        # ── bottom (horizontal, centred) ──
        bottom_y = self._bottom_of_zone('left') + 80
        self._layout_h(zones.get('bottom', []), anchor_y=bottom_y)

    def _layout_h(self, nodes: List[Node], anchor_y: int) -> None:
        if not nodes:
            return
        total_w = sum(n.w for n in nodes) + ZONE_GAP * (len(nodes) - 1)
        x = (self.CW - total_w) // 2
        for n in nodes:
            n.rect = Rect(x, anchor_y, n.w, n.h)
            x += n.w + ZONE_GAP

    def _layout_v(self, nodes: List[Node], anchor_x: int) -> None:
        if not nodes:
            return
        # Start below top-zone systems with a comfortable margin
        start_y = self._bottom_of_zone('top') + 50
        y = start_y
        for n in nodes:
            n.rect = Rect(anchor_x, y, n.w, n.h)
            y += n.h + ZONE_GAP

    def _bottom_of_zone(self, zone: str) -> int:
        nodes = [n for n in self.nodes.values() if n.zone == zone and n.rect]
        return max((n.rect.y2 for n in nodes), default=200)

    def _right_of_zone(self, zone: str) -> int:
        nodes = [n for n in self.nodes.values() if n.zone == zone and n.rect]
        return max((n.rect.x2 for n in nodes), default=0)

    # ── Step 2: crossing minimisation (barycenter heuristic) ──────────────────

    def _minimise_crossings(self) -> None:
        """Assign _order within each zone by barycenter of cross-zone neighbours."""
        for zone in ('top', 'left', 'right', 'bottom'):
            zone_nodes = [
                n for n in self.nodes.values()
                if n.zone == zone and n.node_type == 'system'
            ]
            if len(zone_nodes) < 2:
                continue

            bary: Dict[str, float] = {}
            for n in zone_nodes:
                coords = []
                for e in self.edges:
                    other_id = e.tgt if e.src == n.id else (e.src if e.tgt == n.id else None)
                    if other_id is None:
                        continue
                    other = self.nodes.get(other_id)
                    if not other or other.zone == zone or not other.rect:
                        continue
                    # Use the axis orthogonal to the zone's layout direction
                    coords.append(other.rect.cy if zone in self.H_ZONES else other.rect.cx)
                bary[n.id] = sum(coords) / len(coords) if coords else 0.0

            zone_nodes.sort(key=lambda n: bary[n.id])
            for i, n in enumerate(zone_nodes):
                n._order = i

    # ── Step 3: reassign positions in sorted order ─────────────────────────────

    def _reassign_positions(self) -> None:
        for zone in ('top', 'left', 'right', 'bottom'):
            nodes = sorted(
                [n for n in self.nodes.values() if n.zone == zone and n.node_type == 'system'],
                key=lambda n: n._order,
            )
            if not nodes:
                continue
            if zone == 'top':
                anchor_y = nodes[0].rect.y
                self._layout_h(nodes, anchor_y)
            elif zone == 'bottom':
                anchor_y = nodes[0].rect.y
                self._layout_h(nodes, anchor_y)
            elif zone == 'left':
                anchor_x = nodes[0].rect.x
                self._layout_v(nodes, anchor_x)
                # Fix: re-layout_v re-starts from bottom_of_zone('top'), keep that
                start_y = self._bottom_of_zone('top') + 50
                y = start_y
                for n in nodes:
                    n.rect.y = y
                    y += n.h + ZONE_GAP
            elif zone == 'right':
                start_y = self._bottom_of_zone('top') + 50
                y = start_y
                anchor_x = nodes[0].rect.x
                for n in nodes:
                    n.rect = Rect(anchor_x, y, n.w, n.h)
                    y += n.h + ZONE_GAP

    # ── Step 4: place roles ────────────────────────────────────────────────────

    def _place_roles(self) -> None:
        for n in self.nodes.values():
            if n.node_type != 'role':
                continue
            side = n.role_side
            sys_in_zone = [
                s for s in self.nodes.values()
                if s.zone == side and s.node_type == 'system' and s.rect
            ]

            if side == 'top':
                # Centre above top zone
                cx = self.CW // 2 - 40
                top_y = min(s.rect.y for s in sys_in_zone) if sys_in_zone else 200
                n.rect = Rect(cx, max(10, top_y - 170), 80, 150)

            elif side == 'left':
                min_y = min(s.rect.y for s in sys_in_zone) if sys_in_zone else 300
                max_y = max(s.rect.y2 for s in sys_in_zone) if sys_in_zone else 600
                cy = (min_y + max_y) // 2 - 75
                left_x = min(s.rect.x for s in sys_in_zone) if sys_in_zone else 150
                n.rect = Rect(max(10, left_x - 110), cy, 80, 150)

            elif side == 'right':
                min_y = min(s.rect.y for s in sys_in_zone) if sys_in_zone else 300
                max_y = max(s.rect.y2 for s in sys_in_zone) if sys_in_zone else 600
                cy = (min_y + max_y) // 2 - 75
                right_x2 = max(s.rect.x2 for s in sys_in_zone) if sys_in_zone else self.CW - 150
                n.rect = Rect(min(self.CW - 90, right_x2 + 30), cy, 80, 150)

            elif side == 'bottom':
                bottom_y2 = max(s.rect.y2 for s in sys_in_zone) if sys_in_zone else 850
                min_x = min(s.rect.x for s in sys_in_zone) if sys_in_zone else self.CW // 2 - 200
                max_x = max(s.rect.x2 for s in sys_in_zone) if sys_in_zone else self.CW // 2 + 200
                cx = (min_x + max_x) // 2 - 40
                n.rect = Rect(cx, bottom_y2 + 50, 80, 150)

    # ── Step 5: route edges ────────────────────────────────────────────────────

    def _route_edges(self) -> None:
        """Compute explicit waypoints for edges that cross zones."""
        obstacle_rects = [n.rect for n in self.nodes.values() if n.rect]

        for e in self.edges:
            src = self.nodes.get(e.src)
            tgt = self.nodes.get(e.tgt)
            if not src or not tgt or not src.rect or not tgt.rect:
                continue

            # Skip simple same-zone or adjacent role→zone connections
            if self._is_trivial(e, src, tgt):
                continue

            obstacles = [
                n.rect for nid, n in self.nodes.items()
                if nid not in (e.src, e.tgt) and n.rect
            ]
            pts = self._astar(src.rect, tgt.rect, obstacles)
            if pts and len(pts) > 2:
                e.waypoints = pts[1:-1]   # strip endpoints (draw.io adds them)

    def _is_trivial(self, e: Edge, src: Node, tgt: Node) -> bool:
        """Return True if draw.io's built-in router handles this edge well."""
        # Role → its own zone
        if src.node_type == 'role' and src.role_side == tgt.zone:
            return True
        # Within same zone
        if src.zone == tgt.zone:
            return True
        return False

    def _astar(
        self,
        src_rect: Rect,
        tgt_rect: Rect,
        obstacles: List[Rect],
    ) -> List[Tuple[int, int]]:
        """A* on GRID-sized grid; returns pixel waypoints or []."""
        gw = math.ceil(self.CW / GRID) + 2
        gh = math.ceil(self.CH / GRID) + 2

        # Pre-build blocked set (speeds up inner loop)
        blocked: set = set()
        for r in obstacles:
            re = r.expanded(MARGIN)
            for gx in range(max(0, re.x // GRID), min(gw, re.x2 // GRID + 2)):
                for gy in range(max(0, re.y // GRID), min(gh, re.y2 // GRID + 2)):
                    if re.contains_pt(gx * GRID, gy * GRID):
                        blocked.add((gx, gy))

        # Try four exit × four entry combinations; keep cheapest
        exits   = self._border_points(src_rect)
        entries = self._border_points(tgt_rect)

        best_path: List[Tuple[int,int]] = []
        best_cost = float('inf')

        for ex, ey in exits:
            for enx, eny in entries:
                sg = (ex // GRID, ey // GRID)
                eg = (enx // GRID, eny // GRID)
                if sg == eg:
                    return [(ex, ey), (enx, eny)]

                # A* search
                open_q: list = []
                h0 = abs(sg[0] - eg[0]) + abs(sg[1] - eg[1])
                heapq.heappush(open_q, (h0, 0, sg, None, [sg]))
                visited: Dict[Tuple[int,int], float] = {}

                found_cost = float('inf')
                found_path: List = []

                while open_q:
                    f, g, pos, last_dir, path = heapq.heappop(open_q)
                    if f >= best_cost:
                        break
                    if pos in visited and visited[pos] <= g:
                        continue
                    visited[pos] = g

                    if pos == eg:
                        if g < found_cost:
                            found_cost = g
                            found_path = path
                        break

                    gx, gy = pos
                    for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                        ngx, ngy = gx+dx, gy+dy
                        if not (0 <= ngx < gw and 0 <= ngy < gh):
                            continue
                        np = (ngx, ngy)
                        if (ngx, ngy) in blocked:
                            continue
                        turn = 0 if (dx,dy) == last_dir else TURN_COST
                        ng = g + 1 + turn
                        nh = abs(ngx - eg[0]) + abs(ngy - eg[1])
                        if np not in visited or visited[np] > ng:
                            heapq.heappush(open_q, (ng+nh, ng, np, (dx,dy), path+[np]))

                if found_cost < best_cost:
                    best_cost = found_cost
                    best_path = found_path

        if not best_path:
            return []

        pixels = [(p[0]*GRID, p[1]*GRID) for p in best_path]
        return self._simplify(pixels)

    @staticmethod
    def _border_points(r: Rect) -> List[Tuple[int,int]]:
        return [
            (r.cx, r.y),    # top-centre
            (r.cx, r.y2),   # bottom-centre
            (r.x,  r.cy),   # left-centre
            (r.x2, r.cy),   # right-centre
        ]

    @staticmethod
    def _simplify(pts: List[Tuple[int,int]]) -> List[Tuple[int,int]]:
        """Remove collinear intermediate points."""
        if len(pts) <= 2:
            return pts
        result = [pts[0]]
        for i in range(1, len(pts)-1):
            x0,y0 = pts[i-1]; x1,y1 = pts[i]; x2,y2 = pts[i+1]
            # corner = direction change
            if (x1-x0)*(y2-y0) != (x2-x0)*(y1-y0):
                result.append(pts[i])
        result.append(pts[-1])
        return result

    # ── XML helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _uid() -> str:
        return uuid.uuid4().hex[:12]

    def _system_xml(self, n: Node) -> str:
        r = n.rect
        lbl = html.escape(n.label)
        style = f'rounded=1;whiteSpace=wrap;html=1;arcSize=8;fontFamily=Verdana;{n.style_extra}'
        return (
            f'        <mxCell id="{n.id}" value="{lbl}" style="{style}" vertex="1" parent="1">\n'
            f'          <mxGeometry x="{r.x}" y="{r.y}" width="{r.w}" height="{r.h}" as="geometry" />\n'
            f'        </mxCell>\n'
        )

    def _role_xml(self, n: Node) -> str:
        r = n.rect
        lbl = html.escape(n.label)
        grp   = f'{n.id}_grp'
        head  = f'{n.id}_head'
        body  = f'{n.id}_body'
        label = f'{n.id}_lbl'
        return (
            f'        <mxCell id="{grp}" value="" style="group" vertex="1" connectable="0" parent="1">\n'
            f'          <mxGeometry x="{r.x}" y="{r.y}" width="80" height="150" as="geometry" />\n'
            f'        </mxCell>\n'
            f'        <mxCell id="{head}" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;" vertex="1" parent="{grp}">\n'
            f'          <mxGeometry x="20" y="0" width="40" height="40" as="geometry" />\n'
            f'        </mxCell>\n'
            f'        <mxCell id="{body}" value="" style="triangle;whiteSpace=wrap;html=1;rotation=90;" vertex="1" parent="{grp}">\n'
            f'          <mxGeometry x="10" y="60" width="60" height="40" as="geometry" />\n'
            f'        </mxCell>\n'
            f'        <mxCell id="{label}" value="{lbl}" style="text;html=1;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily=Verdana;" vertex="1" parent="{grp}">\n'
            f'          <mxGeometry x="0" y="110" width="80" height="30" as="geometry" />\n'
            f'        </mxCell>\n'
        )

    def _edge_xml(self, e: Edge) -> str:
        src_node = self.nodes[e.src]
        tgt_node = self.nodes[e.tgt]

        # For roles, connect from the label cell (bottom of group)
        src_id = f'{e.src}_lbl' if src_node.node_type == 'role' else e.src
        tgt_id = f'{e.tgt}_lbl' if tgt_node.node_type == 'role' else e.tgt

        style = 'edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;'
        if e.bidirectional:
            style += 'startArrow=classic;startFill=1;'

        eid = self._uid()

        if e.waypoints:
            pts = '\n'.join(
                f'              <mxPoint x="{p[0]}" y="{p[1]}" />' for p in e.waypoints
            )
            geo = (
                '          <mxGeometry relative="1" as="geometry">\n'
                '            <Array as="points">\n'
                f'{pts}\n'
                '            </Array>\n'
                '          </mxGeometry>\n'
            )
        else:
            geo = '          <mxGeometry relative="1" as="geometry" />\n'

        return (
            f'        <mxCell id="{eid}" style="{style}" edge="1"'
            f' source="{src_id}" target="{tgt_id}" parent="1">\n'
            f'{geo}'
            f'        </mxCell>\n'
        )

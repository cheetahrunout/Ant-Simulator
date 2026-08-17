"""
Formicarium nests painted onto the world tile grid.

Two layouts:

  organic  — soil mass with irregular chambers + winding galleries
             (L. niger–like: dump near the entrance, brood/queen deeper)
  box      — legacy two-rectangle rooms + cargo hall

Tile roles:
  WALL  — packed earth / shell
  NEST  — chambers, galleries, entrance floor (walkable)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from src.sim import tiles as T
from src.util.vec import Vec2


Rect = Tuple[float, float, float, float]

# Normalized (u, v, rx, ry) inside the soil mass. v grows south (toward entrance).
_ORGANIC_PRESETS: Dict[str, Dict[str, Any]] = {
    # Flattened under-stone nest: small distinct chambers, skinny galleries.
    "home": {
        "chambers": [
            {"id": "queen", "u": 0.84, "v": 0.13, "rx": 0.07, "ry": 0.09},
            {"id": "brood", "u": 0.60, "v": 0.14, "rx": 0.11, "ry": 0.10},
            {"id": "dump", "u": 0.38, "v": 0.38, "rx": 0.12, "ry": 0.11, "home": True},
            {"id": "pantry", "u": 0.13, "v": 0.34, "rx": 0.07, "ry": 0.08},
            {"id": "alcove", "u": 0.68, "v": 0.42, "rx": 0.07, "ry": 0.06},
            {"id": "vestibule", "u": 0.42, "v": 0.84, "rx": 0.08, "ry": 0.07, "entrance": True},
        ],
        "links": [
            ("vestibule", "dump", "haul"),
            ("dump", "brood", "gallery"),
            ("brood", "queen", "gallery"),
            ("dump", "pantry", "gallery"),
            ("dump", "alcove", "gallery"),
        ],
    },
    "good": {
        "chambers": [
            {"id": "queen", "u": 0.78, "v": 0.16, "rx": 0.08, "ry": 0.09},
            {"id": "brood", "u": 0.44, "v": 0.20, "rx": 0.12, "ry": 0.11, "home": True},
            {"id": "vestibule", "u": 0.48, "v": 0.82, "rx": 0.08, "ry": 0.07, "entrance": True},
            {"id": "pantry", "u": 0.16, "v": 0.46, "rx": 0.07, "ry": 0.07},
        ],
        "links": [
            ("vestibule", "brood", "haul"),
            ("brood", "queen", "gallery"),
            ("brood", "pantry", "gallery"),
        ],
    },
    "poor": {
        # Bright, wide, too-open — a worse site (M4 still ranks it lower).
        "chambers": [
            {"id": "hall", "u": 0.48, "v": 0.36, "rx": 0.22, "ry": 0.18, "home": True},
            {"id": "vestibule", "u": 0.50, "v": 0.78, "rx": 0.14, "ry": 0.10, "entrance": True},
        ],
        "links": [
            ("vestibule", "hall", "haul"),
        ],
    },
}


def _merge_cells_to_rects(
    cells: List[Tuple[int, int]], tile: float
) -> List[Rect]:
    """Merge (r,c) cells into horizontal runs (cheap draw / legacy lists)."""
    if not cells:
        return []
    by_row: Dict[int, List[int]] = {}
    for r, c in cells:
        by_row.setdefault(r, []).append(c)
    rects: List[Rect] = []
    for r, cols in by_row.items():
        cols.sort()
        start = cols[0]
        prev = cols[0]
        for c in cols[1:]:
            if c == prev + 1:
                prev = c
                continue
            rects.append((start * tile, r * tile, (prev - start + 1) * tile, tile))
            start = prev = c
        rects.append((start * tile, r * tile, (prev - start + 1) * tile, tile))
    return rects


def _hash01(*vals: int) -> float:
    """Deterministic 0..1 hash (no RNG object needed at build time)."""
    x = 2166136261
    for v in vals:
        x ^= (int(v) + 0x9E3779B9) & 0xFFFFFFFF
        x = (x * 16777619) & 0xFFFFFFFF
    return (x & 0xFFFFFF) / 16777215.0


def _stamp_disk(
    nest: set[tuple[int, int]],
    wall: set[tuple[int, int]],
    cx: float,
    cy: float,
    radius: float,
) -> None:
    """Carve a disk of NEST cells (radius in tiles) out of the soil."""
    r = max(0.55, float(radius))
    r2 = r * r
    c0 = int(math.floor(cx - r))
    c1 = int(math.ceil(cx + r))
    r0 = int(math.floor(cy - r))
    r1 = int(math.ceil(cy + r))
    for row in range(r0, r1 + 1):
        for col in range(c0, c1 + 1):
            dx = (col + 0.5) - cx
            dy = (row + 0.5) - cy
            if dx * dx + dy * dy <= r2:
                wall.discard((row, col))
                nest.add((row, col))


def _carve_bezier(
    nest: set[tuple[int, int]],
    wall: set[tuple[int, int]],
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    radius: float,
    wobble: float,
    seed: int,
) -> None:
    """Winding cubic gallery from (x0,y0) to (x1,y1)."""
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    _stamp_disk(nest, wall, x0, y0, radius)
    if length < 0.6:
        _stamp_disk(nest, wall, x1, y1, radius)
        return
    nx = -dy / length
    ny = dx / length
    s1 = (_hash01(seed, 11) * 2.0 - 1.0) * wobble * length
    s2 = (_hash01(seed, 29) * 2.0 - 1.0) * wobble * length * 0.8
    c1x = x0 + dx * 0.33 + nx * s1
    c1y = y0 + dy * 0.33 + ny * s1
    c2x = x0 + dx * 0.66 + nx * s2
    c2y = y0 + dy * 0.66 + ny * s2
    steps = max(10, int(length * 4) + 1)
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = (
            u * u * u * x0
            + 3.0 * u * u * t * c1x
            + 3.0 * u * t * t * c2x
            + t * t * t * x1
        )
        y = (
            u * u * u * y0
            + 3.0 * u * u * t * c1y
            + 3.0 * u * t * t * c2y
            + t * t * t * y1
        )
        _stamp_disk(nest, wall, x, y, radius)


def _in_noisy_ellipse(
    col: int,
    row: int,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    seed: int,
) -> bool:
    """Irregular chamber: ellipse whose radius wobbles with angle."""
    rx = max(1.2, float(rx))
    ry = max(1.2, float(ry))
    dx = (col + 0.5 - cx) / rx
    dy = (row + 0.5 - cy) / ry
    ang = math.atan2(dy, dx)
    n = (
        0.20 * math.sin(2.0 * ang + seed * 0.37)
        + 0.12 * math.sin(3.0 * ang + seed * 0.19)
        + 0.08 * math.sin(5.0 * ang + seed * 0.11)
        + 0.05 * math.sin(8.0 * ang + seed * 0.07)
    )
    rad = 1.0 + n
    return dx * dx + dy * dy <= rad * rad


def _in_soil_blob(
    col: int,
    row: int,
    oc: int,
    orow: int,
    sw: int,
    sh: int,
    seed: int,
) -> bool:
    """Flattened, noisy soil mass — not a rectangle, not a circle."""
    cx = oc + sw * 0.5
    cy = orow + sh * 0.5
    # Superellipse (n≈2.6) fills the box better than a circle, still rounded.
    rx = sw * 0.50
    ry = sh * 0.50
    if rx < 2 or ry < 2:
        return False
    dx = (col + 0.5 - cx) / rx
    dy = (row + 0.5 - cy) / ry
    ang = math.atan2(dy, dx)
    n = (
        0.10 * math.sin(2.0 * ang + seed * 0.21)
        + 0.07 * math.sin(3.0 * ang + seed * 0.41)
        + 0.05 * math.sin(6.0 * ang + seed * 0.13)
        + 0.03 * math.sin(col * 0.55 + row * 0.31 + seed)
    )
    # Lumpy south lip (excavated mound, not a straight wall)
    if dy > 0.25:
        n += 0.06 * math.sin(col * 0.85 + seed)
    p = 3.15
    return (abs(dx) ** p + abs(dy) ** p) <= (1.0 + n) ** p


def _flood(
    start: tuple[int, int], walkable: set[tuple[int, int]]
) -> set[tuple[int, int]]:
    if start not in walkable:
        return set()
    seen = {start}
    stack = [start]
    while stack:
        r, c = stack.pop()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nxt = (r + dr, c + dc)
            if nxt in walkable and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


@dataclass
class NestSite:
    """Multi-chamber nest painted in tile units onto the world grid."""

    name: str
    origin_col: int
    origin_row: int
    chamber_w: int
    chamber_h: int
    tunnel_len: int
    tunnel_w: int
    wall: int
    door_h: int
    light_level: float
    occupied: bool = False
    cargo_path: bool = False
    cargo_width: int = 6
    cargo_extra_len: int = 6
    door_width: int = 2
    layout: str = "organic"
    soil_w: int = 46
    soil_h: int = 32
    gallery_width: int = 2
    haul_width: int = 5
    entrance_len: int = 7
    preset: str = "home"
    chambers_cfg: List[Dict[str, Any]] = field(default_factory=list)
    links_cfg: List[Tuple[str, str, str]] = field(default_factory=list)

    walls: List[Rect] = field(default_factory=list)
    floors: List[Rect] = field(default_factory=list)
    entrance_pos: Vec2 = field(default_factory=Vec2)
    cargo_entrance_pos: Vec2 = field(default_factory=Vec2)
    interior_spawn: Vec2 = field(default_factory=Vec2)
    home_tile: Vec2 = field(default_factory=Vec2)
    bounds: Rect = (0.0, 0.0, 0.0, 0.0)
    wall_cells: List[Tuple[int, int]] = field(default_factory=list)
    nest_cells: List[Tuple[int, int]] = field(default_factory=list)
    tile: float = 20.0
    chamber_centers: Dict[str, Vec2] = field(default_factory=dict)
    _nest_lookup: set = field(default_factory=set, repr=False)
    _wall_lookup: set = field(default_factory=set, repr=False)

    def build(self, tile: float) -> None:
        tile = max(float(tile), 1.0)
        self.tile = tile
        if str(self.layout).lower() == "box":
            self._build_box(tile)
        else:
            self._build_organic(tile)
        self._nest_lookup = set(self.nest_cells)
        self._wall_lookup = set(self.wall_cells)

    # ------------------------------------------------------------------
    # Organic soil-mass nest
    # ------------------------------------------------------------------

    def _build_organic(self, tile: float) -> None:
        oc = int(self.origin_col)
        orow = int(self.origin_row)
        sw = max(18, int(self.soil_w))
        sh = max(16, int(self.soil_h))
        wall_pad = max(1, int(self.wall))
        gal_w = max(1, int(self.gallery_width))
        haul_w = max(gal_w + 1, int(self.haul_width))
        ent_len = max(4, int(self.entrance_len))
        self.soil_w, self.soil_h = sw, sh
        self.gallery_width, self.haul_width = gal_w, haul_w
        self.entrance_len = ent_len

        seed = 2166136261
        for ch in self.name:
            seed ^= ord(ch)
            seed = (seed * 16777619) & 0xFFFFFFFF
        seed %= 10_000
        preset_name = str(self.preset or "home")
        preset = _ORGANIC_PRESETS.get(preset_name, _ORGANIC_PRESETS["home"])
        chambers = list(self.chambers_cfg) or list(preset["chambers"])
        links: List[Tuple[str, str, str]] = list(self.links_cfg) or [
            (a, b, k) for a, b, k in preset["links"]
        ]

        wall_cells: set[tuple[int, int]] = set()
        nest_cells: set[tuple[int, int]] = set()

        # 1) Soil mass
        for r in range(orow - 1, orow + sh + 2):
            for c in range(oc - 1, oc + sw + 2):
                if _in_soil_blob(c, r, oc, orow, sw, sh, seed):
                    wall_cells.add((r, c))

        # 2) Chambers
        centers: Dict[str, Tuple[float, float]] = {}
        home_id = None
        entrance_id = None
        for spec in chambers:
            cid = str(spec["id"])
            cx = oc + float(spec["u"]) * sw
            cy = orow + float(spec["v"]) * sh
            rx = max(2.0, float(spec["rx"]) * sw)
            ry = max(2.0, float(spec["ry"]) * sh)
            # Keep chambers inside the soil with a wall rind (except vestibule south)
            cx = min(max(cx, oc + rx + wall_pad), oc + sw - rx - wall_pad)
            cy = min(max(cy, orow + ry + wall_pad), orow + sh - ry - 1)
            centers[cid] = (cx, cy)
            if spec.get("home"):
                home_id = cid
            if spec.get("entrance"):
                entrance_id = cid
            ch_seed = seed + sum(ord(ch) for ch in cid)
            r0 = int(math.floor(cy - ry * 1.25))
            r1 = int(math.ceil(cy + ry * 1.25))
            c0 = int(math.floor(cx - rx * 1.25))
            c1 = int(math.ceil(cx + rx * 1.25))
            for row in range(r0, r1 + 1):
                for col in range(c0, c1 + 1):
                    if _in_noisy_ellipse(col, row, cx, cy, rx, ry, ch_seed):
                        # Only open voids inside the soil mass (no floating floor)
                        if (row, col) in wall_cells:
                            wall_cells.discard((row, col))
                            nest_cells.add((row, col))

        if not centers:
            # Degenerate fallback
            cx, cy = oc + sw * 0.5, orow + sh * 0.5
            centers["dump"] = (cx, cy)
            home_id = entrance_id = "dump"
            _stamp_disk(nest_cells, wall_cells, cx, cy, min(sw, sh) * 0.22)

        if home_id is None:
            home_id = next(iter(centers))
        if entrance_id is None:
            entrance_id = home_id

        # 3) Galleries between chambers
        for a, b, kind in links:
            if a not in centers or b not in centers:
                continue
            ax, ay = centers[a]
            bx, by = centers[b]
            width = haul_w if kind == "haul" else gal_w
            radius = width * 0.48
            wobble = 0.22 if kind == "haul" else 0.34
            _carve_bezier(
                nest_cells,
                wall_cells,
                ax,
                ay,
                bx,
                by,
                radius,
                wobble,
                seed + int(_hash01(seed, sum(ord(ch) for ch in a + b)) * 997),
            )

        # 4) Short worn hole — taper from vestibule rim to a small mouth
        vx, vy = centers[entrance_id]
        vest_ry = 2.4
        for spec in chambers:
            if str(spec.get("id")) == entrance_id:
                vest_ry = max(2.0, float(spec["ry"]) * sh)
                break
        rim_y = vy + vest_ry * 0.75
        mouth_x = vx + (_hash01(seed, 3) - 0.5) * 1.4
        soil_south = orow + sh
        mouth_y = soil_south + min(ent_len, 4) - 0.2
        steps = max(6, int((mouth_y - rim_y) * 4))
        for i in range(steps + 1):
            t = i / steps
            x = vx * (1.0 - t) + mouth_x * t
            y = rim_y * (1.0 - t) + mouth_y * t
            # Taper: haul-wide inside, worker-hole at the lip
            rad = (haul_w * 0.48) * (1.0 - 0.45 * t) + 1.05 * t
            _stamp_disk(nest_cells, wall_cells, x, y, rad)
        # Tiny worn apron (not a paved driveway)
        _stamp_disk(nest_cells, wall_cells, mouth_x, mouth_y + 0.4, 1.35)

        # Optional second (wider) cargo mouth a little east of the main hole
        cargo_on = bool(self.cargo_path)
        if cargo_on:
            hx, hy = centers[home_id]
            cargo_x = mouth_x + max(6.0, haul_w * 1.6)
            cargo_y = mouth_y + max(1, int(self.cargo_extra_len)) * 0.35
            _carve_bezier(
                nest_cells,
                wall_cells,
                hx,
                hy,
                cargo_x,
                cargo_y,
                max(haul_w, int(self.cargo_width)) * 0.52,
                0.14,
                seed + 99,
            )

        # 5) Spoil crumbs beside the entrance (excavated earth)
        for dc, dr, rad in (
            (-haul_w - 1, 1, 1.1),
            (-haul_w - 2, 2, 0.8),
            (haul_w + 1, 1, 1.15),
            (haul_w + 2, 3, 0.85),
            (-haul_w, 3, 0.7),
        ):
            sc = int(round(mouth_x + dc))
            sr = int(round(soil_south + dr))
            if (sr, sc) not in nest_cells:
                for rr in range(sr - 1, sr + 2):
                    for cc in range(sc - 1, sc + 2):
                        if (rr + 0.5 - sr) ** 2 + (cc + 0.5 - sc) ** 2 <= rad * rad:
                            if (rr, cc) not in nest_cells:
                                wall_cells.add((rr, cc))

        # 6) If home is not reachable from the mouth, punch a straight haul rescue
        mouth_cell = (int(mouth_y), int(mouth_x))
        # pick a nest cell nearest the mouth
        if nest_cells:
            mouth_cell = min(
                nest_cells,
                key=lambda rc: (rc[0] - mouth_y) ** 2 + (rc[1] - mouth_x) ** 2,
            )
        home_cx, home_cy = centers[home_id]
        home_cell = (int(home_cy), int(home_cx))
        if home_cell not in nest_cells:
            # nearest nest cell to intended home
            home_cell = min(
                nest_cells,
                key=lambda rc: (rc[0] - home_cy) ** 2 + (rc[1] - home_cx) ** 2,
            )
        reachable = _flood(mouth_cell, nest_cells)
        if home_cell not in reachable:
            _carve_bezier(
                nest_cells,
                wall_cells,
                mouth_x,
                mouth_y,
                home_cx,
                home_cy,
                haul_w * 0.52,
                0.04,
                seed,
            )

        # Walls never stay as nest
        nest_cells -= wall_cells

        self.wall_cells = sorted(wall_cells)
        self.nest_cells = sorted(nest_cells)
        self.walls = _merge_cells_to_rects(self.wall_cells, tile)
        self.floors = _merge_cells_to_rects(self.nest_cells, tile)

        self.entrance_pos = Vec2(mouth_x * tile, (mouth_y + 0.4) * tile)
        if cargo_on:
            self.cargo_entrance_pos = Vec2(cargo_x * tile, cargo_y * tile)
        else:
            self.cargo_entrance_pos = self.entrance_pos.copy()

        self.home_tile = Vec2(home_cx * tile, home_cy * tile)
        self.interior_spawn = self.home_tile.copy()
        self.chamber_centers = {
            cid: Vec2(x * tile, y * tile) for cid, (x, y) in centers.items()
        }

        # Tight AABB around painted cells (plus a little pad)
        all_cells = wall_cells | nest_cells
        if all_cells:
            rs = [r for r, _ in all_cells]
            cs = [c for _, c in all_cells]
            cmin, cmax = min(cs), max(cs)
            rmin, rmax = min(rs), max(rs)
            self.bounds = (
                cmin * tile,
                rmin * tile,
                (cmax - cmin + 1) * tile,
                (rmax - rmin + 1) * tile,
            )
        else:
            self.bounds = (oc * tile, orow * tile, sw * tile, (sh + ent_len) * tile)

    # ------------------------------------------------------------------
    # Legacy box nest
    # ------------------------------------------------------------------

    def _build_box(self, tile: float) -> None:
        """
        Layout (tile units):

            [ chamber A ]=wide door=[ chamber B ][ cargo hall ]
                    |                      |
                 tunnel (short)     cargo tunnel (wider + longer)
        """
        w = max(1, int(self.wall))
        cw = max(2, int(self.chamber_w))
        ch = max(2, int(self.chamber_h))
        tlen = max(1, int(self.tunnel_len))
        opening = max(1, int(self.tunnel_w))
        door = max(1, min(int(self.door_h), ch))
        door_w = max(w, int(self.door_width))
        cargo_on = bool(self.cargo_path)
        cargo_w = max(opening, int(self.cargo_width)) if cargo_on else 0
        cargo_extra = max(0, int(self.cargo_extra_len)) if cargo_on else 0
        cargo_tlen = tlen + cargo_extra

        self.wall = w
        self.chamber_w = cw
        self.chamber_h = ch
        self.tunnel_len = tlen
        self.tunnel_w = opening
        self.door_h = door
        self.door_width = door_w
        self.cargo_width = cargo_w
        self.cargo_extra_len = cargo_extra

        oc = int(self.origin_col)
        orow = int(self.origin_row)
        self.origin_col = oc
        self.origin_row = orow

        outer_w = w + cw + door_w + cw + w
        if cargo_on:
            outer_w += cargo_w + w
        tunnel_span = max(tlen, cargo_tlen) if cargo_on else tlen
        outer_h = w + ch + w + tunnel_span

        wall_cells: set[tuple[int, int]] = set()
        nest_cells: set[tuple[int, int]] = set()

        def add_rect_cells(
            c0: int, r0: int, c1: int, r1: int, into: set[tuple[int, int]]
        ) -> None:
            for r in range(r0, r1):
                for c in range(c0, c1):
                    into.add((r, c))

        a_c0 = oc + w
        a_c1 = a_c0 + cw
        mid_c0 = a_c1
        mid_c1 = mid_c0 + door_w
        b_c0 = mid_c1
        b_c1 = b_c0 + cw
        cargo_hall_c0 = b_c1
        cargo_hall_c1 = cargo_hall_c0 + cargo_w if cargo_on else b_c1

        add_rect_cells(oc, orow, oc + outer_w, orow + w, wall_cells)
        add_rect_cells(oc, orow, oc + w, orow + w + ch + w, wall_cells)
        add_rect_cells(
            oc + outer_w - w, orow, oc + outer_w, orow + w + ch + w, wall_cells
        )

        door_r0 = orow + w + (ch - door) // 2
        door_r1 = door_r0 + door
        if door_r0 > orow + w:
            add_rect_cells(mid_c0, orow + w, mid_c1, door_r0, wall_cells)
        if door_r1 < orow + w + ch:
            add_rect_cells(mid_c0, door_r1, mid_c1, orow + w + ch, wall_cells)
        add_rect_cells(mid_c0, door_r0, mid_c1, door_r1, nest_cells)
        add_rect_cells(a_c0, orow + w, a_c1, orow + w + ch, nest_cells)
        add_rect_cells(b_c0, orow + w, b_c1, orow + w + ch, nest_cells)
        if cargo_on:
            add_rect_cells(
                cargo_hall_c0, orow + w, cargo_hall_c1, orow + w + ch, nest_cells
            )

        bot_r0 = orow + w + ch
        bot_r1 = bot_r0 + w
        tun_c0 = a_c0 + max(0, (cw - opening) // 2)
        tun_c0 = max(a_c0, min(tun_c0, a_c1 - opening))
        tun_c1 = tun_c0 + opening
        if cargo_on:
            cg_c0 = cargo_hall_c0
            cg_c1 = cargo_hall_c1
        else:
            cg_c0 = cg_c1 = tun_c1

        add_rect_cells(oc, bot_r0, tun_c0, bot_r1, wall_cells)
        if cargo_on:
            add_rect_cells(tun_c1, bot_r0, cg_c0, bot_r1, wall_cells)
            add_rect_cells(cg_c1, bot_r0, oc + outer_w, bot_r1, wall_cells)
        else:
            add_rect_cells(tun_c1, bot_r0, oc + outer_w, bot_r1, wall_cells)
        add_rect_cells(tun_c0, bot_r0, tun_c1, bot_r1, nest_cells)
        if cargo_on:
            add_rect_cells(cg_c0, bot_r0, cg_c1, bot_r1, nest_cells)

        tun_r0 = bot_r1
        tun_r1 = tun_r0 + tlen
        add_rect_cells(tun_c0 - w, tun_r0 - w, tun_c0, tun_r1, wall_cells)
        add_rect_cells(tun_c1, tun_r0 - w, tun_c1 + w, tun_r1, wall_cells)
        add_rect_cells(tun_c0, tun_r0, tun_c1, tun_r1, nest_cells)

        if cargo_on:
            cg_r0 = bot_r1
            cg_r1 = cg_r0 + cargo_tlen
            add_rect_cells(cg_c0 - w, cg_r0 - w, cg_c0, cg_r1, wall_cells)
            add_rect_cells(cg_c1, cg_r0 - w, cg_c1 + w, cg_r1, wall_cells)
            add_rect_cells(cg_c0, cg_r0, cg_c1, cg_r1, nest_cells)

        nest_cells -= wall_cells
        self.wall_cells = sorted(wall_cells)
        self.nest_cells = sorted(nest_cells)
        self.walls = _merge_cells_to_rects(self.wall_cells, tile)
        self.floors = _merge_cells_to_rects(self.nest_cells, tile)

        ent_c = tun_c0 + opening * 0.5
        ent_r = tun_r1 + 0.5
        self.entrance_pos = Vec2(ent_c * tile, ent_r * tile)
        if cargo_on:
            cg_ent_c = (cg_c0 + cg_c1) * 0.5
            cg_ent_r = (bot_r1 + cargo_tlen) + 0.5
            self.cargo_entrance_pos = Vec2(cg_ent_c * tile, cg_ent_r * tile)
        else:
            self.cargo_entrance_pos = self.entrance_pos.copy()

        home_c = a_c0 + cw * 0.5
        home_r = orow + w + ch * 0.5
        self.interior_spawn = Vec2(home_c * tile, home_r * tile)
        self.home_tile = self.interior_spawn.copy()
        self.chamber_centers = {"A": self.home_tile.copy()}
        self.bounds = (oc * tile, orow * tile, outer_w * tile, outer_h * tile)

    def paint(self, role_map: "object") -> None:
        """Paint WALL / NEST roles onto a role ndarray (rows, cols)."""
        rows, cols = role_map.shape
        for r, c in self.wall_cells:
            if 0 <= r < rows and 0 <= c < cols:
                role_map[r, c] = T.WALL
        for r, c in self.nest_cells:
            if 0 <= r < rows and 0 <= c < cols:
                if role_map[r, c] != T.WALL:
                    role_map[r, c] = T.NEST

    def contains_point(self, p: Vec2) -> bool:
        """True if ``p`` is on this nest's floor (not just inside the AABB)."""
        if self.tile <= 0:
            return False
        c = int(p.x / self.tile)
        r = int(p.y / self.tile)
        if (r, c) in self._nest_lookup:
            return True
        # Fallback before build() lookup is filled
        if not self._nest_lookup:
            bx, by, bw, bh = self.bounds
            return bx <= p.x <= bx + bw and by <= p.y <= by + bh
        return False

    def contains_cell(self, r: int, c: int) -> bool:
        return (r, c) in self._nest_lookup or (r, c) in self._wall_lookup

    def reachable_from_entrance(self) -> bool:
        """Home floor cell can be walked to from the entrance gallery."""
        if not self.nest_cells:
            return False
        tile = max(self.tile, 1.0)
        er = int(self.entrance_pos.y / tile)
        ec = int(self.entrance_pos.x / tile)
        walk = set(self.nest_cells)
        start = min(walk, key=lambda rc: (rc[0] - er) ** 2 + (rc[1] - ec) ** 2)
        hr = int(self.home_tile.y / tile)
        hc = int(self.home_tile.x / tile)
        goal = min(walk, key=lambda rc: (rc[0] - hr) ** 2 + (rc[1] - hc) ** 2)
        return goal in _flood(start, walk)


def _as_tiles(val: Any, tile: float, default: int) -> int:
    if val is None:
        return default
    if isinstance(val, int):
        return max(1, val)
    v = float(val)
    if v > 20:
        return max(1, int(round(v / tile)))
    return max(1, int(round(v)))


def _parse_links(raw: Any) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    if not raw:
        return out
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            kind = str(item[2]) if len(item) > 2 else "gallery"
            out.append((str(item[0]), str(item[1]), kind))
        elif isinstance(item, dict):
            out.append(
                (
                    str(item.get("a", item.get("from"))),
                    str(item.get("b", item.get("to"))),
                    str(item.get("kind", "gallery")),
                )
            )
    return out


def nest_from_config(
    cfg: Dict[str, Any],
    occupied: bool = False,
    tile: float = 20.0,
) -> NestSite:
    tile = max(float(tile), 1.0)

    if "origin_tile" in cfg:
        oc, orow = int(cfg["origin_tile"][0]), int(cfg["origin_tile"][1])
    else:
        ox, oy = cfg.get("origin", [0, 0])
        oc = int(round(float(ox) / tile))
        orow = int(round(float(oy) / tile))

    if "chamber_tiles" in cfg:
        cw, ch = int(cfg["chamber_tiles"][0]), int(cfg["chamber_tiles"][1])
    else:
        cs = cfg.get("chamber_size", [8 * tile, 6 * tile])
        cw = max(2, int(round(float(cs[0]) / tile)))
        ch = max(2, int(round(float(cs[1]) / tile)))

    tunnel_len = (
        int(cfg["tunnel_length_tiles"])
        if "tunnel_length_tiles" in cfg
        else _as_tiles(cfg.get("tunnel_length", 4), tile, 4)
    )
    tunnel_w = (
        int(cfg["tunnel_width_tiles"])
        if "tunnel_width_tiles" in cfg
        else _as_tiles(
            max(
                float(cfg.get("tunnel_width", tile)),
                float(cfg.get("entrance_width", tile)),
            ),
            tile,
            2,
        )
    )
    wall = (
        int(cfg["wall_tiles"])
        if "wall_tiles" in cfg
        else _as_tiles(cfg.get("wall_thickness", tile), tile, 1)
    )
    door_h = (
        int(cfg["door_tiles"]) if "door_tiles" in cfg else max(1, min(tunnel_w, ch))
    )
    door_width = (
        int(cfg["door_width_tiles"]) if "door_width_tiles" in cfg else max(wall, 2)
    )
    cargo_path = bool(cfg.get("cargo_path", False))
    cargo_width = (
        int(cfg["cargo_width_tiles"])
        if "cargo_width_tiles" in cfg
        else max(tunnel_w, 6)
    )
    cargo_extra = (
        int(cfg["cargo_extra_length_tiles"])
        if "cargo_extra_length_tiles" in cfg
        else 6
    )

    layout = str(cfg.get("layout", "organic")).lower()
    if layout not in ("organic", "box"):
        layout = "organic"

    # Soil footprint: explicit, or derived from the old chamber box
    if "soil_tiles" in cfg:
        sw, sh = int(cfg["soil_tiles"][0]), int(cfg["soil_tiles"][1])
    else:
        sw = max(22, cw * 2 + 14)
        sh = max(18, ch * 2 + 8)

    gallery_w = int(cfg.get("gallery_width_tiles", 2))
    haul_w = int(cfg.get("haul_width_tiles", max(tunnel_w, 5)))
    ent_len = int(cfg.get("entrance_length_tiles", max(tunnel_len, 6)))

    name = str(cfg["name"])
    preset = str(cfg.get("preset", ""))
    if not preset:
        if "good" in name:
            preset = "good"
        elif "poor" in name:
            preset = "poor"
        else:
            preset = "home"

    chambers_cfg = list(cfg.get("chambers") or [])
    links_cfg = _parse_links(cfg.get("links"))

    nest = NestSite(
        name=name,
        origin_col=oc,
        origin_row=orow,
        chamber_w=cw,
        chamber_h=ch,
        tunnel_len=tunnel_len,
        tunnel_w=tunnel_w,
        wall=wall,
        door_h=door_h,
        light_level=float(cfg.get("light_level", 0.15)),
        occupied=occupied,
        cargo_path=cargo_path,
        cargo_width=cargo_width,
        cargo_extra_len=cargo_extra,
        door_width=door_width,
        layout=layout,
        soil_w=sw,
        soil_h=sh,
        gallery_width=gallery_w,
        haul_width=haul_w,
        entrance_len=ent_len,
        preset=preset,
        chambers_cfg=chambers_cfg,
        links_cfg=links_cfg,
    )
    nest.build(tile)
    return nest


def build_default_nests(
    nest_cfg: Dict[str, Any],
    tile: float = 20.0,
) -> List[NestSite]:
    return [
        nest_from_config(nest_cfg["home"], occupied=True, tile=tile),
        nest_from_config(nest_cfg["empty_good"], occupied=False, tile=tile),
        nest_from_config(nest_cfg["empty_poor"], occupied=False, tile=tile),
    ]


def all_wall_rects(nests: Sequence[NestSite]) -> List[Rect]:
    walls: List[Rect] = []
    for n in nests:
        walls.extend(n.walls)
    return walls

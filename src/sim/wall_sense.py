"""Nearest-wall queries for thigmotaxis / wall sensors.

Prefer the tile-role grid (O(local cells)). Legacy list-of-rects path is
kept for callers that only have wall AABBs.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, List, NamedTuple, Optional, Tuple

from src.sim import tiles as T
from src.util.vec import Vec2

if TYPE_CHECKING:
    from src.sim.grid import PheromoneGrid

Rect = Tuple[float, float, float, float]


class WallHit(NamedTuple):
    point: Vec2
    normal: Vec2  # unit, points from wall surface into free space
    distance: float


def closest_point_on_aabb(pos: Vec2, rect: Rect) -> Vec2:
    x, y, w, h = rect
    return Vec2(
        min(max(pos.x, x), x + w),
        min(max(pos.y, y), y + h),
    )


def nearest_wall(pos: Vec2, walls: List[Rect]) -> Optional[WallHit]:
    """Closest wall surface among AABB rects (legacy / merged segments)."""
    best: Optional[WallHit] = None
    best_d2 = float("inf")

    for rect in walls:
        cp = closest_point_on_aabb(pos, rect)
        dx = pos.x - cp.x
        dy = pos.y - cp.y
        d2 = dx * dx + dy * dy

        if d2 < best_d2:
            best_d2 = d2
            if d2 < 1e-12:
                x, y, w, h = rect
                left = pos.x - x
                right = (x + w) - pos.x
                top = pos.y - y
                bottom = (y + h) - pos.y
                m = min(left, right, top, bottom)
                if m == left:
                    n = Vec2(-1.0, 0.0)
                    cp = Vec2(x, pos.y)
                elif m == right:
                    n = Vec2(1.0, 0.0)
                    cp = Vec2(x + w, pos.y)
                elif m == top:
                    n = Vec2(0.0, -1.0)
                    cp = Vec2(pos.x, y)
                else:
                    n = Vec2(0.0, 1.0)
                    cp = Vec2(pos.x, y + h)
                best = WallHit(cp, n, 0.0)
            else:
                dist = math.sqrt(d2)
                best = WallHit(cp, Vec2(dx / dist, dy / dist), dist)

    return best


def nearest_wall_grid(
    pos: Vec2,
    grid: "PheromoneGrid",
    max_range: float = 40.0,
) -> Optional[WallHit]:
    """
    Closest WALL tile near pos. Only scans a local ring of cells — cheap even
    on a 1000×600 map.
    """
    cs = grid.cell_size
    if max_range <= 0:
        return None
    rad = max(1, int(math.ceil(max_range / cs)) + 1)
    r_c, c_c = grid.world_to_cell(pos.x, pos.y)
    best: Optional[WallHit] = None
    best_d2 = max_range * max_range

    for dr in range(-rad, rad + 1):
        for dc in range(-rad, rad + 1):
            r = r_c + dr
            c = c_c + dc
            if grid.wrap:
                r %= grid.rows
                c %= grid.cols
                if r < 0:
                    r += grid.rows
                if c < 0:
                    c += grid.cols
            else:
                if r < 0 or r >= grid.rows or c < 0 or c >= grid.cols:
                    continue
            if grid.role[r, c] != T.WALL:
                continue
            x0, y0 = c * cs, r * cs
            x1, y1 = x0 + cs, y0 + cs
            cx = min(max(pos.x, x0), x1)
            cy = min(max(pos.y, y0), y1)
            dx = pos.x - cx
            dy = pos.y - cy
            d2 = dx * dx + dy * dy
            if d2 >= best_d2:
                continue
            best_d2 = d2
            if d2 < 1e-12:
                left = pos.x - x0
                right = x1 - pos.x
                top = pos.y - y0
                bottom = y1 - pos.y
                m = min(left, right, top, bottom)
                if m == left:
                    n = Vec2(-1.0, 0.0)
                    cp = Vec2(x0, pos.y)
                elif m == right:
                    n = Vec2(1.0, 0.0)
                    cp = Vec2(x1, pos.y)
                elif m == top:
                    n = Vec2(0.0, -1.0)
                    cp = Vec2(pos.x, y0)
                else:
                    n = Vec2(0.0, 1.0)
                    cp = Vec2(pos.x, y1)
                best = WallHit(cp, n, 0.0)
            else:
                dist = math.sqrt(d2)
                best = WallHit(Vec2(cx, cy), Vec2(dx / dist, dy / dist), dist)

    return best


def wall_ahead(
    pos: Vec2,
    heading: float,
    walls: List[Rect],
    sense_range: float,
    samples: int = 5,
) -> float:
    """Legacy ray march over wall rect list."""
    if sense_range <= 0:
        return 0.0
    max_block = 0.0
    for i in range(samples):
        t = (i / max(samples - 1, 1)) - 0.5
        ang = heading + t * 0.6
        dir_v = Vec2.from_angle(ang)
        step = sense_range / 6.0
        d = step
        while d <= sense_range:
            p = pos + dir_v * d
            hit = nearest_wall(p, walls)
            if hit is not None and hit.distance < 2.0:
                center_w = 1.0 - abs(t) * 0.5
                block = (1.0 - d / sense_range) * center_w
                if block > max_block:
                    max_block = block
                break
            d += step
    return max_block


def wall_ahead_grid(
    pos: Vec2,
    heading: float,
    grid: "PheromoneGrid",
    sense_range: float,
    samples: int = 5,
) -> float:
    """
    Forward-arc blockage using tile roles only.
    Each sample is a few cell lookups — no O(walls) scans.
    """
    if sense_range <= 0:
        return 0.0
    max_block = 0.0
    # ~half-tile steps so thin 1-tile walls are not skipped
    step = max(grid.cell_size * 0.5, sense_range / 8.0)
    for i in range(samples):
        t = (i / max(samples - 1, 1)) - 0.5
        ang = heading + t * 0.6
        dir_v = Vec2.from_angle(ang)
        d = step
        while d <= sense_range:
            p = pos + dir_v * d
            if grid.role_at(p) == T.WALL:
                center_w = 1.0 - abs(t) * 0.5
                block = (1.0 - d / sense_range) * center_w
                if block > max_block:
                    max_block = block
                break
            d += step
    return max_block

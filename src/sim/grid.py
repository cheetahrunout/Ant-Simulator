"""
World grid — one tile map with a clear role per cell, plus scent layers.

Tile roles (structural):
  OPEN  — outdoor free ground (pheromone trails live here)
  WALL  — solid; no walk, no pheromone
  NEST  — nest floor / tunnel / door
  FOOD  — food patch tile (walkable outdoor)

Food-trail model (simple):
  1. Carrying ants **deposit** chemical on tiles they enter (reinforce path).
  2. Every tick, active trail tiles **fade** (wind) by trail_evaporation units/s.
     Very high tiles also lose a % of their excess (faster crash when food is gone).
  3. Values below **floor** become 0 and drop off the active set.
  Optional mild **diffusion** blurs the path slightly so sensing is forgiving.

Nest scent is separate: emitted at home, same fade rule.
"""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from src.sim import tiles as T
from src.util.vec import Vec2


class PheromoneGrid:
    def __init__(
        self,
        world_w: float,
        world_h: float,
        cell_size: float,
        wrap: bool = True,
    ) -> None:
        self.world_w = world_w
        self.world_h = world_h
        self.cell_size = max(cell_size, 1.0)
        self.wrap = wrap
        self.cols = max(1, int(round(world_w / self.cell_size)))
        self.rows = max(1, int(round(world_h / self.cell_size)))
        # Exact world size from whole tiles
        self.world_w = self.cols * self.cell_size
        self.world_h = self.rows * self.cell_size

        self.role = np.full((self.rows, self.cols), T.OPEN, dtype=np.uint8)
        self.trail = np.zeros((self.rows, self.cols), dtype=np.float32)
        self.nest = np.zeros((self.rows, self.cols), dtype=np.float32)
        # Alarm pheromone: fast-evaporating panic/recruitment signal (C1)
        self.alarm = np.zeros((self.rows, self.cols), dtype=np.float32)
        # Sparse active sets — only cells with mass are updated/drawn
        self._trail_active: set[tuple[int, int]] = set()
        self._nest_active: set[tuple[int, int]] = set()
        self._alarm_active: set[tuple[int, int]] = set()
        self._food_cells: set[tuple[int, int]] = set()
        self._tick = 0
        self._sync_blocked()

    # --- roles ---------------------------------------------------------------

    def _sync_blocked(self) -> None:
        """Mark WALL cells. Silent wall scent is kept (not wiped on re-paint)."""
        self.blocked = self.role == T.WALL

    def reset_roles(self) -> None:
        self.role[:] = T.OPEN
        self._sync_blocked()

    def paint_nest(self, nest: object) -> None:
        """Paint a NestSite's wall/nest cells onto the role map."""
        nest.paint(self.role)  # type: ignore[attr-defined]
        self._sync_blocked()

    def set_food_cell(self, r: int, c: int, is_food: bool = True) -> None:
        """Mark / clear a FOOD role (won't overwrite WALL or NEST)."""
        if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
            return
        if self.role[r, c] == T.WALL or self.role[r, c] == T.NEST:
            return
        if is_food:
            self.role[r, c] = T.FOOD
            self._food_cells.add((r, c))
        else:
            if self.role[r, c] == T.FOOD:
                self.role[r, c] = T.OPEN
            self._food_cells.discard((r, c))

    def clear_food_roles(self) -> None:
        """Clear FOOD tiles only where we stamped them (not a full-grid scan)."""
        for r, c in self._food_cells:
            if 0 <= r < self.rows and 0 <= c < self.cols:
                if self.role[r, c] == T.FOOD:
                    self.role[r, c] = T.OPEN
        self._food_cells.clear()

    def role_at(self, pos: Vec2) -> int:
        r, c = self.world_to_cell(pos.x, pos.y)
        return int(self.role[r, c])

    def is_wall(self, pos: Vec2) -> bool:
        return self.role_at(pos) == T.WALL

    def is_nest(self, pos: Vec2) -> bool:
        return self.role_at(pos) == T.NEST

    def cell_center(self, r: int, c: int) -> Vec2:
        cs = self.cell_size
        return Vec2((c + 0.5) * cs, (r + 0.5) * cs)

    def world_to_cell(self, x: float, y: float) -> Tuple[int, int]:
        c = int(x / self.cell_size)
        r = int(y / self.cell_size)
        if self.wrap:
            c %= self.cols
            r %= self.rows
            if c < 0:
                c += self.cols
            if r < 0:
                r += self.rows
        else:
            c = min(max(c, 0), self.cols - 1)
            r = min(max(r, 0), self.rows - 1)
        return r, c

    def is_blocked_cell(self, r: int, c: int) -> bool:
        if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
            return True
        return bool(self.role[r, c] == T.WALL)

    def circle_hits_wall(self, pos: Vec2, radius: float) -> bool:
        """True if the circle overlaps any WALL tile."""
        cs = self.cell_size
        r0 = int((pos.y - radius) / cs) - 1
        r1 = int((pos.y + radius) / cs) + 1
        c0 = int((pos.x - radius) / cs) - 1
        c1 = int((pos.x + radius) / cs) + 1
        rr = radius * radius
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if self.wrap:
                    rr_ = r % self.rows
                    cc_ = c % self.cols
                    if rr_ < 0:
                        rr_ += self.rows
                    if cc_ < 0:
                        cc_ += self.cols
                else:
                    if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
                        continue
                    rr_, cc_ = r, c
                if self.role[rr_, cc_] != T.WALL:
                    continue
                # Closest point on cell AABB to circle center
                x0, y0 = cc_ * cs, rr_ * cs
                x1, y1 = x0 + cs, y0 + cs
                cx = min(max(pos.x, x0), x1)
                cy = min(max(pos.y, y0), y1)
                dx = pos.x - cx
                dy = pos.y - cy
                if dx * dx + dy * dy < rr:
                    return True
        return False

    def resolve_circle(
        self, pos: Vec2, radius: float, max_iters: int = 4
    ) -> Vec2:
        """Push circle out of WALL tiles."""
        p = pos.copy()
        cs = self.cell_size
        for _ in range(max_iters):
            moved = False
            r0 = int((p.y - radius) / cs) - 1
            r1 = int((p.y + radius) / cs) + 1
            c0 = int((p.x - radius) / cs) - 1
            c1 = int((p.x + radius) / cs) + 1
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    if self.wrap:
                        rr_ = r % self.rows
                        cc_ = c % self.cols
                        if rr_ < 0:
                            rr_ += self.rows
                        if cc_ < 0:
                            cc_ += self.cols
                        # Use unwrapped cell origin near p for push math
                        x0 = (c) * cs  # use loop c so push stays local
                        y0 = (r) * cs
                    else:
                        if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
                            continue
                        rr_, cc_ = r, c
                        x0, y0 = cc_ * cs, rr_ * cs
                    if self.role[rr_, cc_] != T.WALL:
                        continue
                    x1, y1 = x0 + cs, y0 + cs
                    cx = min(max(p.x, x0), x1)
                    cy = min(max(p.y, y0), y1)
                    dx = p.x - cx
                    dy = p.y - cy
                    dist_sq = dx * dx + dy * dy
                    if dist_sq >= radius * radius:
                        continue
                    if dist_sq < 1e-12:
                        left = p.x - x0
                        right = x1 - p.x
                        top = p.y - y0
                        bottom = y1 - p.y
                        m = min(left, right, top, bottom)
                        if m == left:
                            p.x = x0 - radius
                        elif m == right:
                            p.x = x1 + radius
                        elif m == top:
                            p.y = y0 - radius
                        else:
                            p.y = y1 + radius
                        moved = True
                        continue
                    dist = dist_sq**0.5
                    push = (radius - dist) / dist
                    p.x += dx * push
                    p.y += dy * push
                    moved = True
            if not moved:
                break
        # wrap
        if self.wrap:
            p.x %= self.world_w
            p.y %= self.world_h
            if p.x < 0:
                p.x += self.world_w
            if p.y < 0:
                p.y += self.world_h
        return p

    def wall_rects_visible(
        self, r0: int, r1: int, c0: int, c1: int
    ) -> list[Tuple[float, float, float, float]]:
        """Individual wall tile rects in a view window (for drawing)."""
        cs = self.cell_size
        out: list[Tuple[float, float, float, float]] = []
        r0 = max(0, r0)
        r1 = min(self.rows - 1, r1)
        c0 = max(0, c0)
        c1 = min(self.cols - 1, c1)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if self.role[r, c] == T.WALL:
                    out.append((c * cs, r * cs, cs, cs))
        return out

    def nest_rects_visible(
        self, r0: int, r1: int, c0: int, c1: int
    ) -> list[Tuple[float, float, float, float]]:
        cs = self.cell_size
        out: list[Tuple[float, float, float, float]] = []
        r0 = max(0, r0)
        r1 = min(self.rows - 1, r1)
        c0 = max(0, c0)
        c1 = min(self.cols - 1, c1)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if self.role[r, c] == T.NEST:
                    out.append((c * cs, r * cs, cs, cs))
        return out

    # --- scent ---------------------------------------------------------------

    def _layer(self, name: str) -> np.ndarray:
        if name == "trail":
            return self.trail
        if name == "nest":
            return self.nest
        if name == "alarm":
            return self.alarm
        raise KeyError(name)

    def _active_set(self, layer: str) -> set[tuple[int, int]]:
        if layer == "trail":
            return self._trail_active
        if layer == "nest":
            return self._nest_active
        if layer == "alarm":
            return self._alarm_active
        raise KeyError(layer)

    def _mark_active(self, r: int, c: int, layer: str) -> None:
        self._active_set(layer).add((r, c))

    def sample(self, pos: Vec2, layer: str = "trail") -> float:
        """Sample scent under pos (walls always read as 0)."""
        r, c = self.world_to_cell(pos.x, pos.y)
        if self.blocked[r, c]:
            return 0.0
        return float(self._layer(layer)[r, c])

    def deposit(self, pos: Vec2, amount: float, layer: str = "trail") -> None:
        if amount <= 0:
            return
        r, c = self.world_to_cell(pos.x, pos.y)
        if self.blocked[r, c]:
            return
        self._layer(layer)[r, c] += np.float32(amount)
        self._mark_active(r, c, layer)

    def deposit_at_cell(
        self, r: int, c: int, amount: float, layer: str = "trail"
    ) -> None:
        if amount <= 0:
            return
        if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
            return
        if self.blocked[r, c]:
            return
        self._layer(layer)[r, c] += np.float32(amount)
        self._mark_active(r, c, layer)

    def cells_along_segment(self, a: Vec2, b: Vec2) -> list[tuple[int, int]]:
        """
        Grid cells crossed by the step a→b.

        On a wrapping world, uses the **shortest** toroidal delta so a one-step
        wrap near an edge does not paint a trail across the entire map.
        """
        r0, c0 = self.world_to_cell(a.x, a.y)
        r1, c1 = self.world_to_cell(b.x, b.y)
        if r0 == r1 and c0 == c1:
            return [(r0, c0)]

        dx = b.x - a.x
        dy = b.y - a.y
        if self.wrap:
            # Shortest path on torus (same idea as World.wrap_delta)
            if dx > self.world_w * 0.5:
                dx -= self.world_w
            elif dx < -self.world_w * 0.5:
                dx += self.world_w
            if dy > self.world_h * 0.5:
                dy -= self.world_h
            elif dy < -self.world_h * 0.5:
                dy += self.world_h

        dist = (dx * dx + dy * dy) ** 0.5
        if dist < 1e-9:
            return [(r0, c0)]
        n = max(1, int(dist / (self.cell_size * 0.4)) + 1)
        seen: dict[tuple[int, int], None] = {}
        out: list[tuple[int, int]] = []
        for i in range(n + 1):
            t = i / n
            # Sample along shortest delta; world_to_cell wraps coordinates
            p = Vec2(a.x + dx * t, a.y + dy * t)
            rc = self.world_to_cell(p.x, p.y)
            if rc not in seen:
                seen[rc] = None
                out.append(rc)
        return out

    def deposit_disk(
        self, pos: Vec2, amount: float, radius_cells: int = 1, layer: str = "nest"
    ) -> None:
        if amount <= 0:
            return
        cr, cc = self.world_to_cell(pos.x, pos.y)
        grid = self._layer(layer)
        for dr in range(-radius_cells, radius_cells + 1):
            for dc in range(-radius_cells, radius_cells + 1):
                if dr * dr + dc * dc > radius_cells * radius_cells:
                    continue
                r = cr + dr
                c = cc + dc
                if self.wrap:
                    r %= self.rows
                    c %= self.cols
                else:
                    if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
                        continue
                if self.blocked[r, c]:
                    continue
                falloff = 1.0 / (1.0 + dr * dr + dc * dc)
                grid[r, c] += np.float32(amount * falloff)
                self._mark_active(r, c, layer)

    def gradient(self, pos: Vec2, layer: str = "trail") -> Vec2:
        grid = self._layer(layer)
        r, c = self.world_to_cell(pos.x, pos.y)

        def at(rr: int, cc: int) -> float:
            if self.wrap:
                rr = rr % self.rows
                cc = cc % self.cols
            else:
                rr = min(max(rr, 0), self.rows - 1)
                cc = min(max(cc, 0), self.cols - 1)
            if self.blocked[rr, cc]:
                return 0.0
            return float(grid[rr, cc])

        gx = (at(r, c + 1) - at(r, c - 1)) * 0.5
        gy = (at(r + 1, c) - at(r - 1, c)) * 0.5
        return Vec2(gx, gy)

    def trail_follow_steering(
        self,
        pos: Vec2,
        heading: float,
        sense_distance: float = 28.0,
        sense_angle: float = 0.55,
        layer: str = "trail",
    ) -> Tuple[Vec2, float]:
        fwd = Vec2.from_angle(heading)
        p_l = pos + Vec2.from_angle(heading - sense_angle) * sense_distance
        p_r = pos + Vec2.from_angle(heading + sense_angle) * sense_distance
        p_c = pos + fwd * sense_distance
        p_c2 = pos + fwd * (sense_distance * 1.6)

        L = self.sample(p_l, layer)
        R = self.sample(p_r, layer)
        C = self.sample(p_c, layer)
        C2 = self.sample(p_c2, layer)
        H = self.sample(pos, layer)

        strength = max(L, R, C, C2, H)
        if strength < 1e-5:
            return Vec2(0.0, 0.0), 0.0

        diff = (R - L) / (strength + 1e-6)
        forward_good = (
            min(1.0, (C + C2) / (strength + 1e-6)) if (C + C2) > 1e-6 else 0.0
        )
        turn = max(-1.0, min(1.0, diff * (1.35 - 0.6 * forward_good)))

        if abs(diff) < 0.12 and H >= max(L, R) * 0.85:
            if C2 >= H * 0.5 or C >= H * 0.5:
                return fwd, strength
            if L > R:
                return Vec2.from_angle(heading - sense_angle * 0.5), strength
            if R > L:
                return Vec2.from_angle(heading + sense_angle * 0.5), strength
            return fwd, strength

        desired = heading + turn * sense_angle * 1.4
        if max(L, R) > C * 1.25 and max(L, R) > C2 * 1.1:
            desired = heading + (sense_angle if R > L else -sense_angle) * min(
                1.0, abs(diff) * 2.0
            )
        return Vec2.from_angle(desired), strength

    def step(
        self,
        dt: float,
        floor: float = 0.5,
        trail_evaporation: float = 2.0,
        nest_evaporation: float = 0.5,
        alarm_evaporation: float = 12.0,
        diffusion: float = 0.0,
        trail_high_threshold: float = 40.0,
        trail_high_fade_rate: float = 0.5,
        # legacy kwargs ignored (old complex trail models)
        trickle_fraction: float = 0.0,
        spread_every_ticks: int = 1,
        trail_idle_seconds: float = 0.0,
        trail_idle_decay_fraction: float = 0.0,
        trail_idle_low_threshold: float = 0.0,
        trail_idle_low_decay_amount: float = 0.0,
        wall_absorb_fraction: float = 0.0,
        trail_evap: float = 0.0,
        nest_evap: float = 0.0,
        trickle_amount: float = 0.0,
        spread_rate: float = 0.0,
        relative_floor: float = 0.0,
    ) -> None:
        """
        Simple environment tick (sparse, active cells only):

          1) Optional mild diffusion (blur path slightly).
          2) Continuous fade ("wind"): base units/s + faster fade of excess
             above trail_high_threshold (peaks crash when deposits stop).
          3) Absolute floor → 0 and drop from active set.
        """
        if dt <= 0:
            return

        self._tick += 1
        fl = max(0.0, float(floor))
        t_evap = float(trail_evaporation if trail_evaporation else trail_evap)
        n_evap = float(nest_evaporation if nest_evaporation else nest_evap)
        diff = max(0.0, float(diffusion))
        high_th = max(0.0, float(trail_high_threshold))
        high_rate = max(0.0, float(trail_high_fade_rate))

        if diff > 0 and self._trail_active:
            self._diffuse_active(self.trail, self._trail_active, diff * dt)
        if self._trail_active and (t_evap > 0 or high_rate > 0):
            self._fade_trail_active(
                t_evap * dt, high_th, high_rate * dt
            )
        self._apply_floor_active(self.trail, self._trail_active, fl)

        if diff > 0 and self._nest_active:
            self._diffuse_active(self.nest, self._nest_active, diff * 0.35 * dt)
        if n_evap > 0 and self._nest_active:
            self._fade_flat_active(self.nest, self._nest_active, n_evap * dt)
        self._apply_floor_active(self.nest, self._nest_active, fl)

        # Alarm: fast flat fade, no diffusion (panic signal stays local)
        a_evap = float(alarm_evaporation)
        if a_evap > 0 and self._alarm_active:
            self._fade_flat_active(self.alarm, self._alarm_active, a_evap * dt)
        self._apply_floor_active(self.alarm, self._alarm_active, fl)

    def _fade_flat_active(
        self,
        grid: np.ndarray,
        active: set[tuple[int, int]],
        amount: float,
    ) -> None:
        """Subtract a fixed amount from every active cell (nest wind)."""
        if amount <= 0 or not active:
            return
        amt = float(amount)
        for r, c in active:
            grid[r, c] = max(0.0, float(grid[r, c]) - amt)

    def _fade_trail_active(
        self,
        base_amount: float,
        high_threshold: float,
        high_frac_step: float,
    ) -> None:
        """
        Wind on food trail:

          loss = base_amount                          # usual fade
               + max(0, value − high_threshold) * high_frac_step

        So huge peaks drop much faster than modest path values once ants
        stop reinforcing (no new food deposits).
        """
        if not self._trail_active:
            return
        if base_amount <= 0 and high_frac_step <= 0:
            return
        for r, c in self._trail_active:
            v = float(self.trail[r, c])
            if v <= 0.0:
                continue
            loss = base_amount
            if high_frac_step > 0 and v > high_threshold:
                loss += (v - high_threshold) * high_frac_step
            self.trail[r, c] = max(0.0, v - loss)

    def _diffuse_active(
        self,
        grid: np.ndarray,
        active: set[tuple[int, int]],
        leave_frac: float,
    ) -> None:
        """
        Mild blur: each free active cell shares a fraction of its value with
        free neighbours. Keeps sensing slightly more forgiving without complex
        downhill rules. Walls never hold scent.
        """
        if leave_frac <= 0 or not active:
            return
        leave_frac = min(float(leave_frac), 0.25)
        rows, cols = self.rows, self.cols
        wrap = self.wrap
        blocked = self.blocked
        dirs = ((-1, 0), (1, 0), (0, -1), (0, 1))

        sources = [rc for rc in active if not blocked[rc[0], rc[1]]]
        if not sources:
            return

        leave: dict[tuple[int, int], float] = {}
        recv: dict[tuple[int, int], float] = {}

        for r, c in sources:
            val = float(grid[r, c])
            if val <= 0.0:
                continue
            neigh: list[tuple[int, int]] = []
            for dr, dc in dirs:
                rr, cc = r + dr, c + dc
                if wrap:
                    rr %= rows
                    cc %= cols
                else:
                    if rr < 0 or rr >= rows or cc < 0 or cc >= cols:
                        continue
                if blocked[rr, cc]:
                    continue
                neigh.append((rr, cc))
            if not neigh:
                continue
            share = val * leave_frac
            per = share / len(neigh)
            leave[(r, c)] = share
            for rr, cc in neigh:
                recv[(rr, cc)] = recv.get((rr, cc), 0.0) + per

        for (r, c), amt in leave.items():
            grid[r, c] -= np.float32(amt)
        for (rr, cc), amt in recv.items():
            grid[rr, cc] += np.float32(amt)
            active.add((rr, cc))

    def _apply_floor_active(
        self,
        grid: np.ndarray,
        active: set[tuple[int, int]],
        abs_floor: float,
    ) -> None:
        """Zero tiny values and drop dead cells from the active set."""
        if not active:
            return
        dead: list[tuple[int, int]] = []
        for r, c in active:
            v = float(grid[r, c])
            if abs_floor > 0 and v < abs_floor:
                grid[r, c] = 0.0
                dead.append((r, c))
            elif v <= 0.0:
                grid[r, c] = 0.0
                dead.append((r, c))
        for key in dead:
            active.discard(key)

    def max_trail(self) -> float:
        """Max over active trail cells only."""
        if not self._trail_active:
            return 0.0
        m = 0.0
        for r, c in self._trail_active:
            v = float(self.trail[r, c])
            if v > m:
                m = v
        return m

    def active_trail_cells(self) -> set[tuple[int, int]]:
        """Cells with trail mass — for sparse drawing."""
        return self._trail_active

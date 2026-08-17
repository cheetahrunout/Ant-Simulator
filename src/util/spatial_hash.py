"""Uniform grid for neighbor queries (O(n) separation instead of O(n²))."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from src.util.vec import Vec2

Cell = Tuple[int, int]


class SpatialHash2D:
    """Bucket world positions into cells for local queries."""

    __slots__ = ("cell_size", "inv", "cols", "rows", "wrap", "cells")

    def __init__(
        self,
        positions: Sequence[Vec2],
        cell_size: float,
        world_w: float,
        world_h: float,
        wrap: bool = True,
    ) -> None:
        cs = max(4.0, float(cell_size))
        self.cell_size = cs
        self.inv = 1.0 / cs
        self.wrap = bool(wrap)
        self.cols = max(1, int(world_w * self.inv) + 1)
        self.rows = max(1, int(world_h * self.inv) + 1)
        self.cells: Dict[Cell, List[int]] = {}
        for i, p in enumerate(positions):
            cx = int(p.x * self.inv)
            cy = int(p.y * self.inv)
            if self.wrap:
                cx %= self.cols
                cy %= self.rows
            self.cells.setdefault((cx, cy), []).append(i)

    def rebuild(self, positions: Sequence[Vec2]) -> None:
        """Clear and re-insert all positions (avoids re-allocating the object)."""
        self.cells.clear()
        for i, p in enumerate(positions):
            cx = int(p.x * self.inv)
            cy = int(p.y * self.inv)
            if self.wrap:
                cx %= self.cols
                cy %= self.rows
            self.cells.setdefault((cx, cy), []).append(i)

    def _cell(self, x: float, y: float) -> Cell:
        cx = int(x * self.inv)
        cy = int(y * self.inv)
        if self.wrap:
            cx %= self.cols
            cy %= self.rows
            if cx < 0:
                cx += self.cols
            if cy < 0:
                cy += self.rows
        return cx, cy

    def query_indices(self, pos: Vec2, radius: float) -> List[int]:
        """All agent indices in cells overlapping the query disk."""
        r = max(0.0, float(radius))
        if r <= 0.0:
            return []
        # How many cells to cover the radius
        span = max(1, int(r * self.inv) + 1)
        cx0, cy0 = self._cell(pos.x, pos.y)
        out: List[int] = []
        seen = out.append  # local bind
        cells = self.cells
        if self.wrap:
            cols, rows = self.cols, self.rows
            for dy in range(-span, span + 1):
                for dx in range(-span, span + 1):
                    key = ((cx0 + dx) % cols, (cy0 + dy) % rows)
                    bucket = cells.get(key)
                    if bucket:
                        out.extend(bucket)
        else:
            for dy in range(-span, span + 1):
                for dx in range(-span, span + 1):
                    bucket = cells.get((cx0 + dx, cy0 + dy))
                    if bucket:
                        out.extend(bucket)
        return out

"""
Nest floor + wall autotile sprites.

Wall pieces use a 4-neighbor bitmask (N=1, E=2, S=4, W=8) where a bit is set
when the adjacent cell is also WALL. Assets: assets/nest/wall_00.png … wall_15.png

Floor: seamless sandy tiles assets/nest/floor_0.png … floor_3.png (hash by cell).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame

from src.sim import tiles as T


_ROOT = Path(__file__).resolve().parents[2]
_NEST_DIR = _ROOT / "assets" / "nest"

# Neighbor bits for wall autotile
N, E, S, W = 1, 2, 4, 8
_DELTAS = (
    (-1, 0, N),  # north
    (0, 1, E),   # east
    (1, 0, S),   # south
    (0, -1, W),  # west
)


class NestTileBank:
    """Cached floor / wall tiles scaled to current on-screen cell size."""

    def __init__(self, nest_dir: Path | str | None = None) -> None:
        self.dir = Path(nest_dir) if nest_dir else _NEST_DIR
        self.ok = False
        self._floor_raw: List[pygame.Surface] = []
        self._wall_raw: List[Optional[pygame.Surface]] = [None] * 16
        self._floor_scaled: Dict[Tuple[int, int], pygame.Surface] = {}
        self._wall_scaled: Dict[Tuple[int, int], pygame.Surface] = {}
        self._load()

    def _load(self) -> None:
        if not self.dir.is_dir():
            return
        for i in range(4):
            path = self.dir / f"floor_{i}.png"
            if path.is_file():
                try:
                    self._floor_raw.append(
                        pygame.image.load(str(path)).convert()
                    )
                except pygame.error:
                    pass
        if not self._floor_raw:
            base = self.dir / "floor_base.png"
            if base.is_file():
                try:
                    self._floor_raw.append(
                        pygame.image.load(str(base)).convert()
                    )
                except pygame.error:
                    pass

        for m in range(16):
            path = self.dir / f"wall_{m:02d}.png"
            if not path.is_file():
                continue
            try:
                self._wall_raw[m] = pygame.image.load(str(path)).convert()
            except pygame.error:
                self._wall_raw[m] = None

        self.ok = bool(self._floor_raw) or any(s is not None for s in self._wall_raw)

    def floor_for_cell(self, r: int, c: int, px: int) -> Optional[pygame.Surface]:
        if not self._floor_raw or px < 1:
            return None
        px = max(1, int(px))
        # Stable variant pick — subtle noise only; same mean brightness
        vi = ((r * 73856093) ^ (c * 19349663) ^ (r * c * 83492791)) & 0x7FFFFFFF
        vi %= len(self._floor_raw)
        key = (vi, px)
        hit = self._floor_scaled.get(key)
        if hit is not None:
            return hit
        raw = self._floor_raw[vi]
        scaled = pygame.transform.scale(raw, (px, px))
        if len(self._floor_scaled) > 64:
            self._floor_scaled.clear()
        self._floor_scaled[key] = scaled
        return scaled

    def wall_for_mask(self, mask: int, px: int) -> Optional[pygame.Surface]:
        if px < 1:
            return None
        mask = int(mask) & 15
        px = max(1, int(px))
        key = (mask, px)
        hit = self._wall_scaled.get(key)
        if hit is not None:
            return hit
        raw = self._wall_raw[mask]
        if raw is None:
            # Prefer solid cross fill as fallback
            raw = self._wall_raw[15] or next((s for s in self._wall_raw if s), None)
        if raw is None:
            return None
        scaled = pygame.transform.scale(raw, (px, px))
        if len(self._wall_scaled) > 128:
            self._wall_scaled.clear()
        self._wall_scaled[key] = scaled
        return scaled


def wall_mask_at(role, r: int, c: int, rows: int, cols: int) -> int:
    """4-neighbor wall connectivity mask at (r, c)."""
    mask = 0
    for dr, dc, bit in _DELTAS:
        rr, cc = r + dr, c + dc
        if 0 <= rr < rows and 0 <= cc < cols and int(role[rr, cc]) == T.WALL:
            mask |= bit
    return mask


_BANK: Optional[NestTileBank] = None


def get_nest_tiles() -> NestTileBank:
    global _BANK
    if _BANK is None:
        _BANK = NestTileBank()
    return _BANK

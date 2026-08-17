"""
Animated walking-ant sprites (OpenGameArt CC0 pack).

Sheet: assets/ant/walk_strip.png  (horizontal frames, faces UP).
Source: https://opengameart.org/content/walking-ant-with-parts-and-rigged-spriter-file
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame


_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STRIP = _ROOT / "assets" / "ant" / "walk_strip.png"
_DEFAULT_META = _ROOT / "assets" / "ant" / "walk_strip.json"

CacheKey = Tuple[int, int, int, int, int, int]  # frame, deg, scale_m, r, g, b


class AntSpriteBank:
    """Shared walk-cycle frames + rotation/scale cache."""

    def __init__(
        self,
        strip_path: Path | str | None = None,
        meta_path: Path | str | None = None,
    ) -> None:
        strip_path = Path(strip_path) if strip_path else _DEFAULT_STRIP
        meta_path = Path(meta_path) if meta_path else _DEFAULT_META

        self.ok = False
        self.frames: List[pygame.Surface] = []
        self.frame_w = 0
        self.frame_h = 0
        self.count = 0
        self._cache: Dict[CacheKey, pygame.Surface] = {}
        self._cache_order: List[CacheKey] = []
        self._cache_max = 2048

        if not strip_path.is_file():
            return

        meta: dict = {}
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        sheet = pygame.image.load(str(strip_path)).convert_alpha()
        self.frame_w = int(meta.get("frame_w", 0)) or sheet.get_height()
        self.frame_h = int(meta.get("frame_h", 0)) or sheet.get_height()
        self.count = int(meta.get("count", 0)) or max(
            1, sheet.get_width() // max(self.frame_w, 1)
        )

        for i in range(self.count):
            rect = pygame.Rect(i * self.frame_w, 0, self.frame_w, self.frame_h)
            if rect.right > sheet.get_width():
                break
            self.frames.append(sheet.subsurface(rect).copy())
        self.count = len(self.frames)
        self.ok = self.count > 0

    def frame_index(self, walk_phase: float, stride: float = 10.0) -> int:
        """Map distance walked to a cycle frame."""
        if self.count <= 0:
            return 0
        stride = max(stride, 1e-3)
        return int(walk_phase / stride * self.count) % self.count

    def get(
        self,
        frame_i: int,
        heading: float,
        scale: float,
        tint: Optional[Tuple[int, int, int]] = None,
    ) -> Optional[pygame.Surface]:
        """
        Rotated + scaled frame. Sprite art faces UP (−Y); heading 0 is +X.
        pygame.rotate is CCW in degrees.
        """
        if not self.ok:
            return None
        frame_i = int(frame_i) % self.count
        scale = max(0.02, float(scale))
        # Bucket angle (~5°) so the cache stays small
        deg = -math.degrees(heading) - 90.0
        bucket = int(round(deg / 5.0) * 5) % 360
        scale_m = max(1, int(round(scale * 1000)))
        tr, tg, tb = tint if tint is not None else (255, 255, 255)
        key: CacheKey = (frame_i, bucket, scale_m, tr, tg, tb)

        hit = self._cache.get(key)
        if hit is not None:
            return hit

        surf = self.frames[frame_i]
        if scale_m != 1000:
            w = max(1, int(self.frame_w * scale))
            h = max(1, int(self.frame_h * scale))
            surf = pygame.transform.smoothscale(surf, (w, h))
        if (tr, tg, tb) != (255, 255, 255):
            surf = surf.copy()
            surf.fill((tr, tg, tb, 255), special_flags=pygame.BLEND_RGBA_MULT)
        surf = pygame.transform.rotate(surf, float(bucket))

        self._cache[key] = surf
        self._cache_order.append(key)
        if len(self._cache_order) > self._cache_max:
            old = self._cache_order.pop(0)
            self._cache.pop(old, None)
        return surf


_bank: Optional[AntSpriteBank] = None


def get_ant_sprites() -> AntSpriteBank:
    global _bank
    if _bank is None:
        _bank = AntSpriteBank()
    return _bank

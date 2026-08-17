"""
Prey insect sprites: whole-body fallback + layered damage / haul parts.

Layout per kind (optional — falls back to legacy single sprite)::

    assets/food/{kind}/
      wing_l.png, wing_r.png, leg_*.png, head.png, body.png
      _meta.yaml   # optional offsets / canvas

Carcass = composite of layers still in ``remaining``.
Loose part = that part's layer alone (rotated for haul).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

import pygame

from src.sim.carcass import DEFAULT_PART_TABLES

_ROOT = Path(__file__).resolve().parents[2]

# Back → front when stacking remaining layers
_LAYER_Z_ORDER: Tuple[str, ...] = (
    "body",
    "leg_1",
    "leg_2",
    "leg_3",
    "leg_4",
    "wing_l",
    "wing_r",
    "head",
)

# Fraction of the *full prey* draw size. Tight-cropped part art is scaled so
# max(w,h) ≈ this × carcass fit — matches how large that piece looked on body.
_PART_SIZE_FRAC: Dict[str, float] = {
    "wing_l": 0.62,
    "wing_r": 0.62,
    "leg_1": 0.48,
    "leg_2": 0.48,
    "leg_3": 0.52,
    "leg_4": 0.55,
    "head": 0.48,
    "body": 0.88,
}


def part_ids_for_kind(kind: str) -> List[str]:
    table = DEFAULT_PART_TABLES.get(kind) or DEFAULT_PART_TABLES["fruit_fly"]
    return [str(e["id"]) for e in table]


def layer_z_order_for_kind(kind: str) -> List[str]:
    ids = set(part_ids_for_kind(kind))
    return [p for p in _LAYER_Z_ORDER if p in ids] + sorted(
        ids - set(_LAYER_Z_ORDER)
    )


class FoodSpriteBank:
    """Load + scale-cache prey sprites (legacy full body + part layers)."""

    def __init__(self) -> None:
        self._raw: Dict[str, pygame.Surface] = {}
        self._scaled: Dict[Tuple[str, int, int], pygame.Surface] = {}
        self._layers: Dict[str, Dict[str, pygame.Surface]] = {}
        self._compose: Dict[
            Tuple[str, FrozenSet[str], int, int], pygame.Surface
        ] = {}
        self._part_rot: Dict[
            Tuple[str, str, int, int, int], pygame.Surface
        ] = {}
        self._missing_logged: Set[str] = set()
        self.ok = False

    # --- path helpers -------------------------------------------------

    def kind_dir(self, kind: str, sprite_dir: str = "") -> Path:
        if sprite_dir:
            p = Path(sprite_dir)
            return p if p.is_absolute() else _ROOT / p
        return _ROOT / "assets" / "food" / kind

    def _resolve(self, rel_path: str) -> Path:
        path = Path(rel_path)
        if not path.is_absolute():
            path = _ROOT / path
        return path

    # --- load raw -----------------------------------------------------

    def load(self, rel_path: str) -> Optional[pygame.Surface]:
        if not rel_path:
            return None
        key = rel_path.replace("\\", "/")
        if key in self._raw:
            return self._raw[key]
        path = self._resolve(key)
        if not path.is_file():
            return None
        try:
            surf = pygame.image.load(str(path)).convert_alpha()
        except pygame.error:
            return None
        surf = _harden_subject_alpha(surf)
        self._raw[key] = surf
        self.ok = True
        return surf

    def load_kind_layers(
        self, kind: str, sprite_dir: str = ""
    ) -> Dict[str, pygame.Surface]:
        if kind in self._layers:
            return self._layers[kind]
        folder = self.kind_dir(kind, sprite_dir)
        layers: Dict[str, pygame.Surface] = {}
        for pid in part_ids_for_kind(kind):
            path = folder / f"{pid}.png"
            if not path.is_file():
                continue
            try:
                surf = pygame.image.load(str(path)).convert_alpha()
            except pygame.error:
                continue
            layers[pid] = _harden_subject_alpha(surf)
        self._layers[kind] = layers
        if layers:
            self.ok = True
        return layers

    def has_layers(self, kind: str, sprite_dir: str = "") -> bool:
        return bool(self.load_kind_layers(kind, sprite_dir))

    # --- scale helpers ------------------------------------------------

    def get_scaled(
        self, rel_path: str, world_size: float, zoom: float
    ) -> Optional[pygame.Surface]:
        """Legacy: full body sized so max(w,h) ≈ world_size * zoom."""
        raw = self.load(rel_path)
        if raw is None:
            return None
        tw, th = _fit_size(raw, world_size, zoom, min_px=20)
        return self._scale_cached(rel_path.replace("\\", "/"), raw, tw, th)

    def _scale_cached(
        self, key: str, raw: pygame.Surface, tw: int, th: int
    ) -> pygame.Surface:
        cache_key = (key, tw, th)
        hit = self._scaled.get(cache_key)
        if hit is not None:
            return hit
        scaled = pygame.transform.smoothscale(raw, (tw, th))
        scaled = _harden_subject_alpha(scaled, subject_min=80)
        if len(self._scaled) > 256:
            self._scaled.clear()
        self._scaled[cache_key] = scaled
        return scaled

    # --- carcass compose ----------------------------------------------

    def compose_carcass(
        self,
        kind: str,
        remaining_ids: Iterable[str],
        world_size: float,
        zoom: float,
        sprite_dir: str = "",
        fallback_path: str = "",
    ) -> Optional[pygame.Surface]:
        """
        Draw carcass for the still-attached parts.

        Preference:
          1. Progressive damage frame ``damage/{n_detached}.png``
             (n_detached = total_parts - len(remaining); 0 = intact)
             — reliable full-body art with missing limbs
          2. Registered part-layer composite (only if a ``layers/`` subfolder
             of same-canvas overlays exists — isolated haul chips are NOT used)
          3. Legacy full-body ``sprite`` path
        """
        remain_list = [str(x) for x in remaining_ids]
        remain = frozenset(remain_list)
        if not remain:
            return None

        all_ids = part_ids_for_kind(kind)
        n_total = max(1, len(all_ids))
        n_left = len(remain)
        # How many parts have been taken (assumes linear detach order)
        n_detached = max(0, n_total - n_left)

        folder = self.kind_dir(kind, sprite_dir)

        # Progressive damage sheet: damage/0.png = intact, 1 = first part gone, …
        dmg_path = folder / "damage" / f"{n_detached}.png"
        if dmg_path.is_file():
            rel = str(dmg_path.relative_to(_ROOT)).replace("\\", "/")
            return self.get_scaled(rel, world_size, zoom)
        for k in range(n_detached, -1, -1):
            p = folder / "damage" / f"{k}.png"
            if p.is_file():
                rel = str(p.relative_to(_ROOT)).replace("\\", "/")
                return self.get_scaled(rel, world_size, zoom)

        # Optional same-canvas overlays in layers/ (not the haul chips in kind root)
        overlay_dir = folder / "layers"
        if overlay_dir.is_dir():
            overlays: Dict[str, pygame.Surface] = {}
            for pid in all_ids:
                path = overlay_dir / f"{pid}.png"
                if not path.is_file():
                    continue
                try:
                    overlays[pid] = _harden_subject_alpha(
                        pygame.image.load(str(path)).convert_alpha()
                    )
                except pygame.error:
                    continue
            if len(overlays) >= max(2, (n_total + 1) // 2):
                sample = next(iter(overlays.values()))
                tw, th = _fit_size(sample, world_size, zoom, min_px=20)
                ckey = (kind, remain, tw, th)
                hit = self._compose.get(ckey)
                if hit is not None:
                    return hit
                canvas = pygame.Surface((tw, th), pygame.SRCALPHA)
                for pid in layer_z_order_for_kind(kind):
                    if pid not in remain:
                        continue
                    raw = overlays.get(pid)
                    if raw is None:
                        continue
                    layer = pygame.transform.smoothscale(raw, (tw, th))
                    layer = _harden_subject_alpha(layer, subject_min=70)
                    canvas.blit(layer, (0, 0))
                if len(self._compose) > 128:
                    self._compose.clear()
                self._compose[ckey] = canvas
                return canvas

        if fallback_path:
            return self.get_scaled(fallback_path, world_size, zoom)
        legacy = f"assets/food/{kind}.png"
        return self.get_scaled(legacy, world_size, zoom)

    # --- loose / hauled part ------------------------------------------

    def get_part_sprite(
        self,
        kind: str,
        part_id: str,
        world_size: float,
        zoom: float,
        angle: float = 0.0,
        sprite_dir: str = "",
        color: Tuple[int, int, int] = (160, 130, 80),
    ) -> Optional[pygame.Surface]:
        """
        Single part layer, scaled and rotated.

        ``world_size`` should be the *parent prey* draw size (same fit used for
        the carcass), not the small haul collision radius. ``part_id`` then
        picks a fraction of that full size so wings/legs match the body art.
        """
        frac = _PART_SIZE_FRAC.get(part_id, 0.55)
        # world_size = full prey footprint; part fills a share of that box
        size = max(14.0, float(world_size) * frac)
        layers = self.load_kind_layers(kind, sprite_dir)
        raw = layers.get(part_id)

        tw, th = _fit_size_from_dims(
            raw.get_width() if raw else 64,
            raw.get_height() if raw else 64,
            size,
            zoom,
            min_px=16,
        )
        # Quantize angle to limit cache (degrees // 8)
        ang_deg = math.degrees(angle) % 360.0
        bucket = int(round(ang_deg / 8.0)) % 45
        rkey = (kind, part_id, tw, th, bucket)
        hit = self._part_rot.get(rkey)
        if hit is not None:
            return hit

        if raw is not None:
            scaled = pygame.transform.smoothscale(raw, (tw, th))
            scaled = _harden_subject_alpha(scaled, subject_min=70)
        else:
            scaled = _fallback_part_chip(part_id, tw, th, color)

        if bucket != 0:
            rot = -bucket * 8.0  # pygame: positive = CCW
            scaled = pygame.transform.rotozoom(scaled, rot, 1.0)
            scaled = _harden_subject_alpha(scaled, subject_min=60)

        if len(self._part_rot) > 256:
            self._part_rot.clear()
        self._part_rot[rkey] = scaled
        return scaled


def _fit_size(
    raw: pygame.Surface, world_size: float, zoom: float, min_px: int = 20
) -> Tuple[int, int]:
    return _fit_size_from_dims(
        raw.get_width(), raw.get_height(), world_size, zoom, min_px
    )


def _fit_size_from_dims(
    rw: int, rh: int, world_size: float, zoom: float, min_px: int = 20
) -> Tuple[int, int]:
    px = max(min_px, int(round(float(world_size) * max(zoom, 0.05))))
    rw = max(1, rw)
    rh = max(1, rh)
    if rw >= rh:
        tw, th = px, max(1, int(round(px * rh / rw)))
    else:
        th, tw = px, max(1, int(round(px * rw / rh)))
    return tw, th


def _fallback_part_chip(
    part_id: str, tw: int, th: int, color: Tuple[int, int, int]
) -> pygame.Surface:
    """Quiet non-yellow chip when art is missing (dev fallback)."""
    surf = pygame.Surface((tw, th), pygame.SRCALPHA)
    # Muted brown/grey — never the old food yellow
    base = (
        min(200, max(40, color[0] // 2 + 40)),
        min(180, max(40, color[1] // 2 + 30)),
        min(140, max(30, color[2] // 2 + 20)),
    )
    cx, cy = tw // 2, th // 2
    label = part_id.split("_")[0]
    if label == "wing":
        pts = [
            (cx - tw // 3, cy),
            (cx + tw // 3, cy - th // 3),
            (cx + tw // 4, cy + th // 4),
        ]
        pygame.draw.polygon(surf, base, pts)
    elif label == "leg":
        pygame.draw.line(
            surf, base, (cx - tw // 3, cy + th // 4), (cx + tw // 3, cy - th // 4), max(2, tw // 6)
        )
    elif label == "head":
        pygame.draw.circle(surf, base, (cx, cy), max(2, min(tw, th) // 3))
    else:
        pygame.draw.ellipse(
            surf, base, (tw // 6, th // 5, tw * 2 // 3, th * 3 // 5)
        )
    return surf


def _harden_subject_alpha(
    surf: pygame.Surface, subject_min: int = 40
) -> pygame.Surface:
    """
    Make the insect solid and readable:
      - true background stays transparent
      - any subject pixel (alpha >= subject_min, not magenta) → alpha 255
    """
    out = surf.copy()
    try:
        rgba = pygame.surfarray.pixels3d(out)
        alpha = pygame.surfarray.pixels_alpha(out)
        r = rgba[:, :, 0].astype("int32")
        g = rgba[:, :, 1].astype("int32")
        b = rgba[:, :, 2].astype("int32")
        dist = (r - 255) ** 2 + g**2 + (b - 255) ** 2
        magenta = ((r > 220) & (b > 220) & (g < 90)) | (dist < 40 * 40)
        subject = (alpha >= subject_min) & ~magenta
        alpha[subject] = 255
        alpha[magenta] = 0
        rgba[magenta] = 0
        weak = (alpha < subject_min) & ~subject
        alpha[weak] = 0
        rgba[weak] = 0
        del rgba, alpha
    except Exception:
        pass
    return out


_BANK: Optional[FoodSpriteBank] = None


def get_food_sprites() -> FoodSpriteBank:
    global _BANK
    if _BANK is None:
        _BANK = FoodSpriteBank()
    return _BANK

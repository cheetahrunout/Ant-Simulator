"""Food patches on the tile grid + typed prey kinds + random respawn when empty."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

from src.sim.carcass import Carcass, FoodPart, part_specs_for_kind, total_prey_nutrition
from src.util.vec import Vec2

if TYPE_CHECKING:
    from src.util.rng import Rng


# Built-in prey kinds (bigger body → more food). Config `food.types` can override.
# radius_tiles = rings from center tile → footprint is (2*r+1) × (2*r+1) tiles.
# Parts: ordered break list (appendages first, body last) — see carcass.DEFAULT_PART_TABLES.
DEFAULT_FOOD_TYPES: Dict[str, Dict[str, Any]] = {
    "fruit_fly": {
        "label": "fruit fly",
        "amount": 90,
        "quality": 0.45,
        "radius_tiles": 1,  # 3×3 tiles
        "sprite": "assets/food/fruit_fly.png",
        "sprite_dir": "assets/food/fruit_fly",
        "color": [210, 170, 60],
    },
    "dung_fly": {
        # "fat shit fly" — chunky blowfly / dung fly
        "label": "fat fly",
        "amount": 360,
        "quality": 0.85,
        "radius_tiles": 2,  # 5×5 tiles
        "sprite": "assets/food/dung_fly.png",
        "sprite_dir": "assets/food/dung_fly",
        "color": [80, 90, 140],
    },
    "cricket": {
        "label": "cricket",
        "amount": 900,
        "quality": 1.15,
        "radius_tiles": 3,  # 7×7 tiles
        "sprite": "assets/food/cricket.png",
        "sprite_dir": "assets/food/cricket",
        "color": [150, 110, 55],
    },
}


@dataclass
class FoodSource:
    pos: Vec2
    amount: float
    quality: float  # 0..1+ recruitment strength scale
    radius: float
    max_amount: float
    kind: str = "fruit_fly"
    label: str = "food"
    sprite_path: str = ""
    sprite_world_size: float = 40.0
    color: tuple = (220, 180, 50)

    def contains(self, p: Vec2, wrap_delta_fn=None) -> bool:
        """Axis-aligned square footprint (matches tile-aligned draw)."""
        if wrap_delta_fn is not None:
            d = wrap_delta_fn(self.pos, p)
            return abs(d.x) <= self.radius and abs(d.y) <= self.radius
        return (
            abs(p.x - self.pos.x) <= self.radius
            and abs(p.y - self.pos.y) <= self.radius
        )

    def take(self, requested: float) -> float:
        got = min(self.amount, max(0.0, requested))
        self.amount -= got
        return got

    @property
    def depleted(self) -> bool:
        return self.amount <= 1e-6


def resolve_food_types(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Merge config food.types over defaults (shallow)."""
    types: Dict[str, Dict[str, Any]] = {
        k: dict(v) for k, v in DEFAULT_FOOD_TYPES.items()
    }
    for k, v in (cfg.get("food", {}).get("types") or {}).items():
        if not isinstance(v, dict):
            continue
        base = types.get(k, {})
        merged = dict(base)
        merged.update(v)
        types[k] = merged
    return types


def _kind_defaults(types: Dict[str, Dict[str, Any]], kind: str) -> Dict[str, Any]:
    if kind in types:
        return types[kind]
    # unknown kind → fruit_fly fallback, or first available
    if "fruit_fly" in types:
        return types["fruit_fly"]
    if types:
        return next(iter(types.values()))
    return DEFAULT_FOOD_TYPES["fruit_fly"]


def _make_carcass(
    pos: Vec2,
    entry: Dict[str, Any],
    types: Dict[str, Dict[str, Any]],
    tile: float,
) -> Carcass:
    kind = str(entry.get("kind", entry.get("type", "fruit_fly")))
    td = _kind_defaults(types, kind)

    quality = (
        float(entry["quality"]) if "quality" in entry else float(td.get("quality", 1.0))
    )

    # radius_tiles = rings from the center tile → odd square (2r+1)² cells.
    if "radius_tiles" in entry:
        rt = max(0, int(entry["radius_tiles"]))
        radius = (rt + 0.5) * tile
    elif "radius" in entry:
        radius = float(entry["radius"])
        radius = max(0.5 * tile, round(radius / (0.5 * tile)) * (0.5 * tile))
    else:
        rt = max(0, int(td.get("radius_tiles", 1)))
        radius = (rt + 0.5) * tile

    footprint = 2.0 * radius
    sprite_size = float(
        entry.get(
            "sprite_world_size",
            td.get("sprite_world_size", footprint),
        )
    )

    color_raw = entry.get("color", td.get("color", [220, 180, 50]))
    color = tuple(int(c) for c in color_raw[:3])

    # Total food value for this carcass; parts split by fixed type ratios (share).
    total_amount = float(
        entry["amount"] if "amount" in entry else td.get("amount", 100.0)
    )
    remaining = part_specs_for_kind(kind, td, total_amount=total_amount)
    max_nut = sum(p.nutrition for p in remaining)
    sprite_dir = str(
        entry.get("sprite_dir", td.get("sprite_dir", f"assets/food/{kind}"))
    )
    return Carcass(
        pos=pos,
        kind=kind,
        label=str(entry.get("label", td.get("label", kind))),
        quality=quality,
        radius=radius,
        sprite_path=str(entry.get("sprite", td.get("sprite", ""))),
        sprite_world_size=sprite_size,
        color=color,
        remaining=remaining,
        max_nutrition=max_nut,
        sprite_dir=sprite_dir,
    )


# Back-compat alias used by older call sites
def _make_food(pos, entry, types, tile):
    return _make_carcass(pos, entry, types, tile)


def _snap_to_tile_center(x: float, y: float, tile: float) -> Vec2:
    tile = max(float(tile), 1.0)
    c = int(x / tile)
    r = int(y / tile)
    return Vec2((c + 0.5) * tile, (r + 0.5) * tile)


def build_food_sources(cfg: Dict[str, Any], tile: float = 20.0) -> List[Carcass]:
    """Build carcasses (dismantleable prey) from config sources."""
    foods: List[Carcass] = []
    tile = max(float(tile), 1.0)
    types = resolve_food_types(cfg)
    for entry in cfg.get("food", {}).get("sources", []):
        if "tile" in entry:
            c, r = int(entry["tile"][0]), int(entry["tile"][1])
            pos = Vec2((c + 0.5) * tile, (r + 0.5) * tile)
        else:
            raw = Vec2.from_iterable(entry["pos"])
            pos = _snap_to_tile_center(raw.x, raw.y, tile)
        foods.append(_make_carcass(pos, entry, types, tile))
    return foods


def spawn_food_at(
    cfg: Dict[str, Any],
    kind: str,
    pos: Vec2,
    tile: float = 20.0,
    snap: bool = True,
) -> Carcass:
    """
    Create one carcass of ``kind`` at ``pos`` (optional tile snap).
    Used by the bottom food-placement bar and any debug spawn.
    """
    tile = max(float(tile), 1.0)
    types = resolve_food_types(cfg)
    if kind not in types:
        kind = next(iter(types.keys()), "fruit_fly")
    p = _snap_to_tile_center(pos.x, pos.y, tile) if snap else pos.copy()
    return _make_carcass(p, {"kind": kind}, types, tile)


def find_food_at(
    pos: Vec2,
    foods: Sequence[Any],
    wrap_delta_fn=None,
) -> Optional[Any]:
    for f in foods:
        if f.depleted:
            continue
        if f.contains(pos, wrap_delta_fn):
            return f
    return None


def find_part_at(
    pos: Vec2,
    parts: Sequence[FoodPart],
    wrap_delta_fn=None,
) -> Optional[FoodPart]:
    for p in parts:
        if p.delivered:
            continue
        if p.contains(pos, wrap_delta_fn):
            return p
    return None


def find_part_near(
    pos: Vec2,
    parts: Sequence[FoodPart],
    reach: float,
    wrap_delta_fn=None,
    prefer_free_slots: bool = True,
    max_carriers: int = 4,
) -> Optional[FoodPart]:
    """
    Nearest undelivered part within ``reach`` of its surface.
    Prefers pieces that still have free grip slots (abandoned / under-crewed).
    """
    best: Optional[FoodPart] = None
    best_key: Optional[tuple] = None  # (full?, dist)
    reach = max(0.0, float(reach))
    for p in parts:
        if p.delivered:
            continue
        if wrap_delta_fn is not None:
            d = wrap_delta_fn(pos, p.pos).length()
        else:
            d = (p.pos - pos).length()
        surf = max(0.0, d - float(p.radius))
        if surf > reach:
            continue
        full = 1 if len(p.carrier_ids) >= max(1, int(max_carriers)) else 0
        if not prefer_free_slots:
            full = 0
        key = (full, surf)
        if best_key is None or key < best_key:
            best_key = key
            best = p
    return best


def _delta_to(pos: Vec2, target: Vec2, wrap_delta_fn=None) -> Vec2:
    if wrap_delta_fn is not None:
        return wrap_delta_fn(pos, target)
    return target - pos


def distance_to_food_surface(
    pos: Vec2,
    food: FoodSource,
    wrap_delta_fn=None,
) -> float:
    """
    World distance from ``pos`` to the food's axis-aligned square surface.
    0 when already inside the footprint.
    """
    d = _delta_to(pos, food.pos, wrap_delta_fn)
    # Outside distance to AABB half-extents (food.radius on each axis)
    ox = max(0.0, abs(d.x) - food.radius)
    oy = max(0.0, abs(d.y) - food.radius)
    return math.hypot(ox, oy)


def sense_nearest_food(
    pos: Vec2,
    heading: float,
    foods: Sequence[Any],
    max_distance: float,
    max_angle: float = math.pi,
    wrap_delta_fn=None,
    prefer_loose_parts: bool = True,
) -> Optional[tuple]:
    """
    Antenna-range food sense (carcass or loose part).

    Returns ``(direction, surface_distance, target)`` for the nearest prey
    within ``max_distance`` of its footprint and within ±``max_angle`` of
    ``heading`` (radians).

    Loose parts (abandoned hauls) are slightly preferred and use a wider
    angle cone so ants notice food left on the ground behind/beside them.
    """
    if max_distance <= 0.0 or not foods:
        return None

    best: Optional[tuple] = None
    best_key: Optional[tuple] = None  # (priority, surf) lower better
    h = Vec2.from_angle(heading)

    for food in foods:
        if getattr(food, "depleted", False) or getattr(food, "delivered", False):
            continue
        is_part = hasattr(food, "part_id") or (
            hasattr(food, "carrier_ids") and not hasattr(food, "remaining")
        )
        # Parts: full 360° so abandoned loads behind the ant are still food
        ang_lim = math.pi if is_part else max_angle
        to_center = _delta_to(pos, food.pos, wrap_delta_fn)
        surf = distance_to_food_surface(pos, food, wrap_delta_fn)
        if surf > max_distance:
            continue
        if to_center.length_sq() < 1e-12:
            dir_v = h
        else:
            dir_v = to_center
            if ang_lim < math.pi - 1e-6:
                ang = abs(
                    math.atan2(
                        h.x * dir_v.y - h.y * dir_v.x,
                        h.x * dir_v.x + h.y * dir_v.y,
                    )
                )
                if ang > ang_lim:
                    continue
        # Prefer free loose parts (priority 0) over full multi-hauls (1) over carcass (2)
        if is_part:
            n_carry = len(getattr(food, "carrier_ids", ()) or ())
            prio = 0 if n_carry == 0 else (1 if n_carry < 4 else 2)
            if not prefer_loose_parts:
                prio = 1
        else:
            prio = 3
        key = (prio, surf)
        if best_key is None or key < best_key:
            best_key = key
            best = (dir_v, surf, food)
    return best


def count_ants_at_food(
    food: FoodSource,
    positions: Sequence[Vec2],
    wrap_delta_fn=None,
) -> int:
    n = 0
    for p in positions:
        if food.contains(p, wrap_delta_fn):
            n += 1
    return n


def all_food_gone(
    foods: Sequence[Any],
    parts: Sequence[FoodPart] | None = None,
) -> bool:
    carcass_gone = len(foods) == 0 or all(f.depleted for f in foods)
    if parts is None:
        return carcass_gone
    loose = any(not p.delivered for p in parts)
    return carcass_gone and not loose


def spawn_random_food(
    cfg: Dict[str, Any],
    home_pos: Vec2,
    world_w: float,
    world_h: float,
    nests_bounds: Sequence[tuple],
    rng: "Rng",
    wrap: bool = True,
    tile: float = 20.0,
) -> List[Carcass]:
    """
    Spawn 1–2 new carcasses in a ring around the home nest.
    Kind is picked from food.respawn_kinds (or all known types).
    """
    fcfg = cfg.get("food", {})
    types = resolve_food_types(cfg)
    n_min = int(fcfg.get("respawn_count_min", 1))
    n_max = int(fcfg.get("respawn_count_max", 2))
    count = rng.randint(n_min, max(n_min, n_max))

    kind_list = fcfg.get("respawn_kinds")
    if not kind_list:
        kind_list = list(types.keys())
    weights = fcfg.get("respawn_weights")

    d_min = float(fcfg.get("respawn_min_dist_from_home", 220.0))
    d_max = float(fcfg.get("respawn_max_dist_from_home", 750.0))

    spawned: List[Carcass] = []
    for _ in range(count):
        pos = _random_forage_pos(
            home_pos, d_min, d_max, world_w, world_h, nests_bounds, rng, wrap, tile
        )
        kind = _pick_kind(kind_list, weights, rng)
        td = _kind_defaults(types, kind)
        quality = float(td.get("quality", 1.0))
        q_jitter = fcfg.get("respawn_quality")
        if q_jitter is not None:
            qlo, qhi = _pair(q_jitter, quality * 0.9, quality * 1.1)
            quality = rng.uniform(qlo, qhi)

        entry = {"kind": kind, "quality": quality}
        spawned.append(_make_carcass(pos, entry, types, tile))
    return spawned


def _pick_kind(
    kinds: Sequence[str],
    weights: Any,
    rng: "Rng",
) -> str:
    kinds = list(kinds) if kinds else ["fruit_fly"]
    if weights and isinstance(weights, (list, tuple)) and len(weights) == len(kinds):
        # weighted choice without importing random.choices dependency on std
        total = sum(max(0.0, float(w)) for w in weights)
        if total <= 0:
            return str(kinds[rng.randint(0, len(kinds) - 1)])
        roll = rng.uniform(0.0, total)
        acc = 0.0
        for k, w in zip(kinds, weights):
            acc += max(0.0, float(w))
            if roll <= acc:
                return str(k)
        return str(kinds[-1])
    return str(kinds[rng.randint(0, len(kinds) - 1)])


def _pair(val, default_lo: float, default_hi: float) -> tuple[float, float]:
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        return float(val[0]), float(val[1])
    if isinstance(val, (int, float)):
        v = float(val)
        return v * 0.8, v * 1.2
    return default_lo, default_hi


def _random_forage_pos(
    home: Vec2,
    d_min: float,
    d_max: float,
    world_w: float,
    world_h: float,
    nests_bounds: Sequence[tuple],
    rng: "Rng",
    wrap: bool,
    tile: float,
    max_tries: int = 40,
) -> Vec2:
    for _ in range(max_tries):
        ang = rng.uniform(0.0, math.pi * 2.0)
        dist = rng.uniform(d_min, d_max)
        x = home.x + math.cos(ang) * dist
        y = home.y + math.sin(ang) * dist
        if wrap:
            x %= world_w
            y %= world_h
            if x < 0:
                x += world_w
            if y < 0:
                y += world_h
        else:
            x = min(max(x, tile), world_w - tile)
            y = min(max(y, tile), world_h - tile)
        p = _snap_to_tile_center(x, y, tile)
        if _inside_any_nest(p, nests_bounds):
            continue
        return p
    return _snap_to_tile_center(home.x, min(home.y + d_min, world_h - tile * 2), tile)


def _inside_any_nest(p: Vec2, nests_bounds: Sequence[tuple]) -> bool:
    for bx, by, bw, bh in nests_bounds:
        if bx <= p.x <= bx + bw and by <= p.y <= by + bh:
            return True
    return False

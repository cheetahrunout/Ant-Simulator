"""
Prey carcasses that break into weighted parts + multi-ant rigid hauling.

Carcass  — whole prey on ground; ants accumulate break work → detach one part at a time.
FoodPart — loose piece; ants grip and lock on; group moves as sum of pull vectors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, TYPE_CHECKING

from src.util.vec import Vec2

if TYPE_CHECKING:
    from src.agents.ant import WorkerAnt
    from src.sim.world import World
    from src.util.rng import Rng


# Ordered break lists: appendages first, body last.
# `share` = fixed food-value proportion within that prey type (normalized to
# the type's total `amount`). Same ratios for every instance of the kind.
# `weight` = haul mass only (independent of nutrition).
DEFAULT_PART_TABLES: Dict[str, List[Dict[str, Any]]] = {
    # Haul mass (weight) is independent of nutrition (share).
    # With ant_mass≈1: solo speed ∝ 1/(1+weight). Bodies need multi-ant help.
    # fruit_fly total amount 90 → shares sum 90
    "fruit_fly": [
        {"id": "wing_l", "label": "wing", "weight": 0.6, "share": 8},
        {"id": "wing_r", "label": "wing", "weight": 0.6, "share": 8},
        {"id": "leg_1", "label": "leg", "weight": 0.9, "share": 10},
        {"id": "leg_2", "label": "leg", "weight": 0.9, "share": 10},
        {"id": "head", "label": "head", "weight": 2.2, "share": 18},
        {"id": "body", "label": "body", "weight": 5.5, "share": 36},
    ],
    # dung_fly total 360
    "dung_fly": [
        {"id": "wing_l", "label": "wing", "weight": 1.2, "share": 25},
        {"id": "wing_r", "label": "wing", "weight": 1.2, "share": 25},
        {"id": "leg_1", "label": "leg", "weight": 1.8, "share": 30},
        {"id": "leg_2", "label": "leg", "weight": 1.8, "share": 30},
        {"id": "leg_3", "label": "leg", "weight": 1.8, "share": 30},
        {"id": "head", "label": "head", "weight": 4.5, "share": 60},
        {"id": "body", "label": "body", "weight": 14.0, "share": 160},
    ],
    # cricket: wing 5% each, leg 10% each, head 15%, body 35%
    "cricket": [
        {"id": "wing_l", "label": "wing", "weight": 1.5, "share": 5},
        {"id": "wing_r", "label": "wing", "weight": 1.5, "share": 5},
        {"id": "leg_1", "label": "leg", "weight": 4.0, "share": 10},
        {"id": "leg_2", "label": "leg", "weight": 4.0, "share": 10},
        {"id": "leg_3", "label": "leg", "weight": 4.0, "share": 10},
        {"id": "leg_4", "label": "leg", "weight": 4.5, "share": 10},
        {"id": "head", "label": "head", "weight": 8.0, "share": 15},
        {"id": "body", "label": "body", "weight": 24.0, "share": 35},
    ],
}


_next_part_uid = 1


def _alloc_part_uid() -> int:
    global _next_part_uid
    uid = _next_part_uid
    _next_part_uid += 1
    return uid


@dataclass
class PartSpec:
    """Template for one detachable piece (still on carcass until broken off)."""

    id: str
    label: str
    weight: float
    nutrition: float


@dataclass
class FoodPart:
    """Loose prey piece on the ground or being hauled as a rigid group."""

    uid: int
    part_id: str
    label: str
    weight: float
    nutrition: float
    quality: float
    pos: Vec2
    radius: float
    parent_kind: str
    color: tuple = (180, 140, 80)
    angle: float = 0.0
    carrier_ids: Set[int] = field(default_factory=set)
    delivered: bool = False
    # Draw scale: match part chips to the parent prey footprint (not haul radius)
    parent_radius: float = 0.0
    parent_sprite_size: float = 0.0
    # Shared multi-haul unstick (stops 4 ants canceling each other in a corner)
    haul_jam_time: float = 0.0
    haul_unstick_t: float = 0.0  # remaining seconds of coordinated unstick
    haul_unstick_side: float = 1.0  # ±1 wall-follow side for all carriers

    @property
    def depleted(self) -> bool:
        return self.delivered

    def contains(self, p: Vec2, wrap_delta_fn=None) -> bool:
        if wrap_delta_fn is not None:
            d = wrap_delta_fn(self.pos, p)
            return abs(d.x) <= self.radius and abs(d.y) <= self.radius
        return (
            abs(p.x - self.pos.x) <= self.radius
            and abs(p.y - self.pos.y) <= self.radius
        )


@dataclass
class Carcass:
    """
    Whole prey being dismantled. Duck-types enough of old FoodSource for sense/draw:
    pos, radius, quality, kind, label, sprite_path, amount, depleted, contains.
    """

    pos: Vec2
    kind: str
    label: str
    quality: float
    radius: float
    sprite_path: str
    sprite_world_size: float
    color: tuple
    remaining: List[PartSpec] = field(default_factory=list)
    break_progress: float = 0.0
    max_nutrition: float = 0.0  # sum of all original parts
    # Folder of registered part layers (assets/food/{kind}/); empty → auto path
    sprite_dir: str = ""

    @property
    def amount(self) -> float:
        """Nutrition still locked in unbroken parts (loose parts counted elsewhere)."""
        return sum(p.nutrition for p in self.remaining)

    @property
    def max_amount(self) -> float:
        return self.max_nutrition

    @property
    def depleted(self) -> bool:
        return len(self.remaining) == 0

    def contains(self, p: Vec2, wrap_delta_fn=None) -> bool:
        if wrap_delta_fn is not None:
            d = wrap_delta_fn(self.pos, p)
            return abs(d.x) <= self.radius and abs(d.y) <= self.radius
        return (
            abs(p.x - self.pos.x) <= self.radius
            and abs(p.y - self.pos.y) <= self.radius
        )

    def parts_left(self) -> int:
        return len(self.remaining)


def part_specs_for_kind(
    kind: str,
    type_cfg: Optional[Dict[str, Any]] = None,
    total_amount: Optional[float] = None,
) -> List[PartSpec]:
    """
    Build part list for a prey kind.

    Each part's food value is ``total_amount * share_i / sum(shares)``.
    Shares are fixed per type (config ``parts[].share`` or built-in table);
    haul ``weight`` is separate and not scaled by amount.
    """
    raw: List[Dict[str, Any]]
    if type_cfg and isinstance(type_cfg.get("parts"), list) and type_cfg["parts"]:
        raw = list(type_cfg["parts"])
    else:
        raw = list(DEFAULT_PART_TABLES.get(kind, DEFAULT_PART_TABLES["fruit_fly"]))

    parsed: List[tuple] = []
    for entry in raw:
        share = float(
            entry.get(
                "share",
                entry.get("nutrition", entry.get("amount", 1.0)),
            )
        )
        share = max(0.0, share)
        parsed.append(
            (
                str(entry.get("id", entry.get("label", "part"))),
                str(entry.get("label", entry.get("id", "part"))),
                float(entry.get("weight", 1.0)),
                share,
            )
        )

    share_sum = sum(s for *_, s in parsed)
    if share_sum <= 1e-12:
        # Equal split fallback
        n = max(1, len(parsed))
        parsed = [(i, lab, w, 1.0) for i, lab, w, _ in parsed]
        share_sum = float(n)

    amount = float(total_amount) if total_amount is not None else share_sum
    amount = max(0.0, amount)

    out: List[PartSpec] = []
    for pid, label, weight, share in parsed:
        nutrition = amount * (share / share_sum)
        out.append(
            PartSpec(
                id=pid,
                label=label,
                weight=weight,
                nutrition=nutrition,
            )
        )
    return out


def detach_next_part(
    carcass: Carcass,
    rng: Optional["Rng"] = None,
    jitter: float = 6.0,
) -> Optional[FoodPart]:
    """Break off the next remaining part as a loose FoodPart near the carcass."""
    if not carcass.remaining:
        return None
    spec = carcass.remaining.pop(0)
    carcass.break_progress = 0.0
    ox, oy = 0.0, 0.0
    if rng is not None:
        ang = rng.uniform(0.0, math.pi * 2.0)
        dist = rng.uniform(jitter * 0.3, jitter)
        ox = math.cos(ang) * dist
        oy = math.sin(ang) * dist
    # Part footprint scales a bit with weight (still small) — physics only
    pr = max(4.0, min(14.0, 4.0 + spec.weight * 1.2))
    parent_r = max(1.0, float(carcass.radius))
    parent_sprite = max(
        2.0 * parent_r,
        float(getattr(carcass, "sprite_world_size", 0.0) or 0.0),
    )
    return FoodPart(
        uid=_alloc_part_uid(),
        part_id=spec.id,
        label=spec.label,
        weight=spec.weight,
        nutrition=spec.nutrition,
        quality=carcass.quality,
        pos=Vec2(carcass.pos.x + ox, carcass.pos.y + oy),
        radius=pr,
        parent_kind=carcass.kind,
        color=tuple(carcass.color),
        angle=rng.uniform(0.0, math.pi * 2.0) if rng else 0.0,
        parent_radius=parent_r,
        parent_sprite_size=parent_sprite,
    )


def apply_break_work(
    carcass: Carcass,
    worker_strengths: Sequence[float],
    dt: float,
    break_work: float,
    break_rate_solo: float,
    rng: Optional["Rng"] = None,
) -> Optional[FoodPart]:
    """
    Accumulate dismantle work. Returns a new FoodPart when threshold crossed.
    One piece max per call.
    """
    if carcass.depleted or dt <= 0:
        return None
    if not worker_strengths:
        return None
    work = sum(max(0.0, float(s)) * break_rate_solo for s in worker_strengths)
    carcass.break_progress += work * dt
    threshold = max(1e-3, float(break_work))
    if carcass.break_progress < threshold:
        return None
    return detach_next_part(carcass, rng=rng)


def total_prey_nutrition(
    carcasses: Sequence[Carcass], parts: Sequence[FoodPart]
) -> float:
    n = sum(c.amount for c in carcasses)
    n += sum(p.nutrition for p in parts if not p.delivered)
    return n


def resolve_hauling(
    parts: List[FoodPart],
    ants_by_id: Dict[int, "WorkerAnt"],
    world: "World",
    dt: float,
    fcfg: Dict[str, Any],
    rng: Optional["Rng"] = None,
) -> None:
    """Transport: passive load + summed ant forces (see haul_physics)."""
    from src.sim.haul_physics import step_hauling

    step_hauling(parts, ants_by_id, world, dt, fcfg)

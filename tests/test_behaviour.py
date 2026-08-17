"""Unit checks for L. niger-style deposit / satiety helpers (no window)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agents.ant import WorkerAnt
from src.util.vec import Vec2


class _FakePhero:
    def __init__(self, local: float = 0.0) -> None:
        self.trail = { (0, 0): local }
        self._local = local

    def __getitem__(self, rc):
        # trail[r, c] via numpy-like — WorkerAnt uses world.pheromones.trail[r, c]
        raise AssertionError("use .trail[r, c]")


class _TrailArr:
    def __init__(self, value: float) -> None:
        self.value = value

    def __getitem__(self, rc):
        return self.value


class _FakeWorld:
    def __init__(self, local_trail: float = 0.0, home: Vec2 | None = None) -> None:
        self.home_tile = home or Vec2(0.0, 0.0)
        self.pheromones = type("P", (), {"trail": _TrailArr(local_trail)})()

    def wrap_delta(self, a: Vec2, b: Vec2) -> Vec2:
        return b - a


def _ant(**kw) -> WorkerAnt:
    forage = {
        "food_quality_deposit_scale": 1.0,
        "deposit_distance_scale": 0.001,
        "deposit_near_food": 2.0,
        "deposit_near_nest": 0.5,
        "deposit_trail_suppress": 0.05,
        "crowd_threshold": 4,
        "crowd_deposit_penalty": 0.5,
        "scout_deposit_boost": 1.25,
        "trail_encounter_radius": 12.0,
        "trail_encounter_deposit": 0.7,
    }
    forage.update(kw.pop("forage", {}))
    a = WorkerAnt(
        ant_id=0,
        pos=Vec2(100.0, 0.0),
        heading=0.0,
        cfg={"radius": 3.5, "speed": 70.0},
        loco_cfg={},
        forage_cfg=forage,
        pheromone_cfg={"deposit_amount": 10.0},
    )
    a.food_quality = 1.0
    a.pickup_pos = Vec2(100.0, 0.0)
    a.trip_distance = 0.0
    a.found_as_scout = False
    a.nearby_nestmates = 0
    a.nestmates_at_pickup = 0
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_deposit_higher_near_food_than_nest() -> None:
    world = _FakeWorld(home=Vec2(0.0, 0.0))
    at_food = _ant(pos=Vec2(100.0, 0.0), pickup_pos=Vec2(100.0, 0.0))
    at_nest = _ant(pos=Vec2(1.0, 0.0), pickup_pos=Vec2(100.0, 0.0))
    near = at_food._compute_deposit_amount(world, 0, 0)
    far = at_nest._compute_deposit_amount(world, 0, 0)
    assert near > far * 1.5, (near, far)


def test_deposit_grows_with_trip_distance() -> None:
    world = _FakeWorld(home=Vec2(0.0, 0.0))
    short = _ant(trip_distance=0.0)
    long = _ant(trip_distance=400.0)
    a = short._compute_deposit_amount(world, 0, 0)
    b = long._compute_deposit_amount(world, 0, 0)
    assert b > a * 1.3, (a, b)


def test_deposit_suppressed_on_strong_trail() -> None:
    empty = _FakeWorld(local_trail=0.0)
    busy = _FakeWorld(local_trail=40.0)
    ant = _ant()
    a = ant._compute_deposit_amount(empty, 0, 0)
    b = ant._compute_deposit_amount(busy, 0, 0)
    assert b < a * 0.5, (a, b)


def test_crowd_and_scout_modulate() -> None:
    world = _FakeWorld()
    base = _ant()._compute_deposit_amount(world, 0, 0)
    crowded = _ant(nestmates_at_pickup=8)._compute_deposit_amount(world, 0, 0)
    scout = _ant(found_as_scout=True)._compute_deposit_amount(world, 0, 0)
    assert crowded < base
    assert scout > base


def test_leave_rate_zero_when_starved_and_store_full() -> None:
    ant = _ant()
    ant.energy = 0.05
    ant.nest_food_memory = 200.0
    ant.thresholds = {"forage": 0.5}
    ant.forage_cfg["leave_nest_rate"] = 0.45
    assert ant._effective_leave_nest_rate() == 0.0


def main() -> int:
    tests = [
        test_deposit_higher_near_food_than_nest,
        test_deposit_grows_with_trip_distance,
        test_deposit_suppressed_on_strong_trail,
        test_crowd_and_scout_modulate,
        test_leave_rate_zero_when_starved_and_store_full,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    if failed:
        print(f"{failed}/{len(tests)} failed")
        return 1
    print(f"{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

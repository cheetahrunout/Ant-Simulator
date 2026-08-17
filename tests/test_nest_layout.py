"""Organic nest: reachable dump, no box silhouette, no food overlap."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.sim.food import build_food_sources
from src.sim.nest import nest_from_config, build_default_nests
from src.util.config import load_config
from src.util.vec import Vec2


def _cfg():
    return load_config(_ROOT / "config" / "default.yaml")


def test_home_is_organic_and_connected() -> None:
    cfg = _cfg()
    nest = nest_from_config(cfg["nest"]["home"], occupied=True, tile=10.0)
    assert nest.layout == "organic"
    assert len(nest.nest_cells) > 80
    assert len(nest.wall_cells) > 80
    assert nest.reachable_from_entrance(), "dump chamber cut off from entrance"
    assert nest.contains_point(nest.home_tile)
    # Not a rectangle: soil outline should be irregular (many unique row widths)
    from collections import Counter

    widths = Counter()
    for r, c in nest.wall_cells:
        widths[r] += 1
    unique = len(set(widths.values()))
    assert unique >= 6, f"wall row-widths look rectangular ({unique} unique)"


def test_box_layout_still_builds() -> None:
    nest = nest_from_config(
        {
            "name": "box_home",
            "layout": "box",
            "origin_tile": [4, 4],
            "chamber_tiles": [10, 8],
            "tunnel_length_tiles": 5,
            "tunnel_width_tiles": 3,
            "wall_tiles": 2,
            "door_tiles": 3,
            "door_width_tiles": 2,
            "cargo_path": False,
        },
        occupied=True,
        tile=10.0,
    )
    assert nest.layout == "box"
    assert nest.reachable_from_entrance()
    assert nest.contains_point(nest.home_tile)


def test_default_nests_miss_starting_food() -> None:
    cfg = _cfg()
    tile = 10.0
    nests = build_default_nests(cfg["nest"], tile=tile)
    home = nests[0]
    occupied = set(home.wall_cells) | set(home.nest_cells)
    foods = build_food_sources(cfg, tile=tile)
    for food in foods:
        half = max(tile * 0.5, float(food.radius))
        c0 = int((food.pos.x - half) / tile)
        r0 = int((food.pos.y - half) / tile)
        c1 = int((food.pos.x + half - 1e-6) / tile)
        r1 = int((food.pos.y + half - 1e-6) / tile)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                assert (r, c) not in occupied, (
                    f"{food.kind} overlaps nest at tile {(c, r)}"
                )


def test_presets_connected() -> None:
    for name, preset in (("g", "good"), ("p", "poor")):
        nest = nest_from_config(
            {
                "name": name,
                "layout": "organic",
                "preset": preset,
                "origin_tile": [4, 4],
                "soil_tiles": [34, 24],
                "gallery_width_tiles": 2,
                "haul_width_tiles": 5,
                "entrance_length_tiles": 6,
                "wall_tiles": 2,
            },
            occupied=False,
            tile=10.0,
        )
        assert nest.reachable_from_entrance(), f"{preset} not connected"


def test_contains_point_is_floor_not_aabb() -> None:
    nest = nest_from_config(
        {
            "name": "home",
            "layout": "organic",
            "preset": "home",
            "origin_tile": [10, 10],
            "soil_tiles": [40, 28],
            "gallery_width_tiles": 2,
            "haul_width_tiles": 5,
            "entrance_length_tiles": 6,
        },
        occupied=True,
        tile=10.0,
    )
    bx, by, bw, bh = nest.bounds
    # Corner of the AABB is almost certainly soil/open, not dump floor
    corner = Vec2(bx + 2.0, by + 2.0)
    # home tile must be inside; a far AABB corner must not count as "in nest"
    assert nest.contains_point(nest.home_tile)
    if (int(corner.y / 10.0), int(corner.x / 10.0)) not in nest._nest_lookup:
        assert not nest.contains_point(corner)


def main() -> int:
    tests = [
        test_home_is_organic_and_connected,
        test_box_layout_still_builds,
        test_default_nests_miss_starting_food,
        test_presets_connected,
        test_contains_point_is_floor_not_aabb,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

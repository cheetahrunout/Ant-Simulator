"""
Automated small-map test: let ants forage until food is gone, then check trail fade.

No forced food empty — a real trail must form from carrying ants first.

  python -m tests.run_trail_test

Screenshots → debug screenshots/auto/
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from src.main import build_sim, load_runtime_config
from src.render.camera import Camera
from src.render.draw import Renderer
from src.sim.food import all_food_gone
from src.util.screenshot import save_screenshot


def main() -> int:
    out_dir = _ROOT / "debug screenshots" / "auto"
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_runtime_config(_ROOT / "config" / "test_small.yaml")
    # Ensure finite food and no respawn so "gone" is permanent
    cfg.setdefault("food", {})["respawn_when_empty"] = False
    # Slightly more ants so they clear food and lay trail in reasonable time
    cfg.setdefault("ants", {})["count"] = max(int(cfg["ants"].get("count", 25)), 30)

    pygame.init()
    w = int(cfg["window"]["width"])
    h = int(cfg["window"]["height"])
    screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption("trail fade test (natural food empty)")

    world, colony, rng = build_sim(cfg)
    camera = Camera(cfg, screen.get_size(), (world.width, world.height))
    camera.center = world.home_spawn.copy()
    camera.zoom = 1.15
    renderer = Renderer(cfg, screen, camera)
    renderer.show_pheromone = True

    fixed_dt = float(cfg["sim"]["fixed_dt"])
    sim_time = 0.0
    fade = float(cfg["pheromone"].get("trail_evaporation", 8.0))

    def food_left() -> float:
        return sum(f.amount for f in world.foods)

    def frame(label: str) -> Path:
        # Keep camera near home / trail zone
        camera.center = world.home_spawn.copy()
        renderer.draw(world, colony, 60.0, sim_time, False)
        pygame.display.flip()
        path = out_dir / f"trail_test_{label}.png"
        save_screenshot(screen, path)
        print(
            f"  t={sim_time:6.1f}s  {path.name}  "
            f"trail_act={len(world.pheromones._trail_active):4d}  "
            f"max={world.pheromones.max_trail():7.1f}  "
            f"food={food_left():6.0f}  deliv={colony.forage_deliveries}"
        )
        return path

    def step_seconds(seconds: float) -> None:
        nonlocal sim_time
        n = max(1, int(seconds / fixed_dt))
        for _ in range(n):
            colony.step(fixed_dt)
            sim_time += fixed_dt

    print("=== natural food-empty trail test ===")
    print(
        f"world {world.width:.0f}x{world.height:.0f}  "
        f"grid {world.pheromones.cols}x{world.pheromones.rows}"
    )
    print(
        f"ants={cfg['ants']['count']}  "
        f"trail_evaporation={fade}  "
        f"start_food={food_left():.0f}"
    )

    frame("00_start")

    # --- Phase 1: ants forage until food is naturally gone ---
    max_forage_s = 300.0
    peak_trail = 0.0
    peak_active = 0
    check_every = 10.0
    next_shot = 30.0
    shot_i = 1

    while sim_time < max_forage_s and not all_food_gone(world.foods):
        step_seconds(check_every)
        peak_trail = max(peak_trail, world.pheromones.max_trail())
        peak_active = max(peak_active, len(world.pheromones._trail_active))
        if sim_time >= next_shot:
            frame(f"{shot_i:02d}_foraging_t{int(sim_time)}s")
            shot_i += 1
            next_shot += 30.0

    if all_food_gone(world.foods):
        frame(f"{shot_i:02d}_food_naturally_empty")
        shot_i += 1
        print(f"  food emptied by ants at t={sim_time:.1f}s  deliveries={colony.forage_deliveries}")
    else:
        frame(f"{shot_i:02d}_timeout_food_still_left")
        shot_i += 1
        print(
            f"  TIMEOUT: food still {food_left():.0f} after {max_forage_s:.0f}s "
            f"(deliveries={colony.forage_deliveries})"
        )
        pygame.quit()
        print("FAIL: ants never cleared food — increase time/ants or lower food amount.")
        return 1

    trail_at_empty = world.pheromones.max_trail()
    active_at_empty = len(world.pheromones._trail_active)
    print(
        f"  at empty: trail max={trail_at_empty:.1f} active={active_at_empty}  "
        f"(peak during forage max={peak_trail:.1f} act={peak_active})"
    )

    if trail_at_empty < 1.0 or active_at_empty < 5:
        print(
            "FAIL: food emptied but no strong trail formed "
            "(need carriers laying path first)."
        )
        pygame.quit()
        return 1

    # --- Phase 2: no food → no new deposits → trail should fade ---
    # Expect roughly clear within ~deposit_scale / evaporation seconds
    clear_deadline = 45.0
    fade_checks = (10.0, 20.0, 30.0, 45.0)
    t0 = sim_time
    last_label_t = 0.0
    for mark in fade_checks:
        while sim_time - t0 < mark:
            step_seconds(min(1.0, mark - (sim_time - t0)))
        frame(f"{shot_i:02d}_fade_{+int(mark)}s")
        shot_i += 1
        last_label_t = mark
        tr = world.pheromones.max_trail()
        ac = len(world.pheromones._trail_active)
        print(f"  +{mark:.0f}s after empty: max={tr:.1f} active={ac}")

    trail_final = world.pheromones.max_trail()
    active_final = len(world.pheromones._trail_active)
    pygame.quit()

    print("--- results ---")
    print(f"trail max: at_empty={trail_at_empty:.1f}  final={trail_final:.1f}")
    print(f"active:    at_empty={active_at_empty}  final={active_final}")
    print(f"screenshots: {out_dir}")

    # Strong trail existed; after clear_deadline should be nearly gone
    ok_clear = trail_final < max(1.0, trail_at_empty * 0.05) and active_final <= 3
    # Also require it was actually strong at empty
    ok_strong = trail_at_empty >= 15.0 and active_at_empty >= 10

    if ok_strong and ok_clear:
        print(
            f"PASS: strong trail (max {trail_at_empty:.0f}) cleared after food "
            f"naturally gone (fade={fade}/s)."
        )
        return 0

    if ok_strong and not ok_clear:
        # Suggest tune
        # Rough: time to clear ~ max/evap; want clear in ~25–40s
        suggest = max(3.0, trail_at_empty / 25.0)
        print(
            f"FAIL: trail still present after +{clear_deadline:.0f}s "
            f"(max={trail_final:.1f}, active={active_final})."
        )
        print(
            f"SUGGEST: raise trail_evaporation from {fade} toward ~{suggest:.1f} "
            f"(or lower deposit) in config/test_small.yaml"
        )
        return 1

    print("FAIL: trail at empty was too weak for a meaningful fade test.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

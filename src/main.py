"""
Ant Simulator — entry point.

Run from project root:
    python -m src.main
    python -m src.main config/test_small.yaml
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Allow `python src/main.py` as well as `python -m src.main`
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pygame

from src.render.camera import Camera
from src.render.draw import Renderer
from src.render.food_bar import FoodBar
from src.render.sidebar import Sidebar, apply_camera_from_cfg
from src.sim.colony import Colony
from src.sim.world import World
from src.util.config import deep_merge, load_config, load_config_stack
from src.util.rng import Rng
from src.util.screenshot import capture, default_shot_dir
from src.util.vec import Vec2


def default_config_path() -> Path:
    return _ROOT / "config" / "default.yaml"


def saved_config_path() -> Path:
    return _ROOT / "config" / "saved.yaml"


def build_sim(cfg: Dict[str, Any]) -> tuple[World, Colony, Rng]:
    seed = cfg.get("sim", {}).get("seed", None)
    rng = Rng(seed)
    world = World(cfg)
    colony = Colony(world, cfg, rng)
    return world, colony, rng


def load_runtime_config(config_path: Path | None = None) -> Dict[str, Any]:
    """
    default.yaml always base.
    If an override path is given (e.g. test_small.yaml), merge it and
    **skip** saved.yaml so test/experiment knobs are not clobbered.
    """
    default = default_config_path()
    if config_path is None:
        return load_config_stack(default, saved_config_path())
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    # Treat named override as full alternate base only if it has world section
    # that looks complete — always layer on default for partial test configs.
    cfg = load_config(default)
    deep_merge(cfg, load_config(path))
    return cfg


def run(config_path: Path | None = None) -> None:
    cfg = load_runtime_config(config_path)

    pygame.init()
    pygame.display.set_caption(cfg["window"]["title"])
    flags = pygame.RESIZABLE
    screen = pygame.display.set_mode(
        (int(cfg["window"]["width"]), int(cfg["window"]["height"])), flags
    )

    world, colony, rng = build_sim(cfg)
    camera = Camera(
        cfg,
        screen.get_size(),
        (world.width, world.height),
    )
    camera.center = world.home_spawn.copy()
    renderer = Renderer(cfg, screen, camera)
    # Don't write test-session sliders over main saved.yaml unless default run
    save_path = (
        None
        if config_path is not None
        else saved_config_path()
    )
    sidebar = Sidebar(cfg, save_path=save_path)
    food_bar = FoodBar(cfg)
    shot_dir = default_shot_dir(_ROOT)

    def on_cfg_change() -> None:
        apply_camera_from_cfg(cfg, camera)

    clock = pygame.time.Clock()
    fixed_dt = float(cfg["sim"]["fixed_dt"])
    max_substeps = int(cfg["sim"]["max_substeps"])
    fps_cap = int(cfg["window"]["fps_cap"])

    accumulator = 0.0
    sim_time = 0.0
    paused = False
    running = True
    last_shot: Optional[Path] = None
    # When placing food: suppress camera click-pan until drag threshold
    place_click_active = False
    # Last sim step cost (ms) — used to avoid catch-up death spiral when overloaded
    last_step_ms = 0.0

    while running:
        # Cap wait only; do not sleep away real work when already under budget
        frame_dt = clock.tick(fps_cap) / 1000.0
        # Never try to "catch up" more than one fixed step of wall time when lagging
        frame_dt = min(frame_dt, fixed_dt * max(1, max_substeps))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue

            if sidebar.handle_event(event, screen, on_change=on_cfg_change):
                food_bar.cancel_press()
                place_click_active = False
                continue

            if food_bar.handle_event(event, screen):
                place_click_active = False
                n_add = food_bar.consume_add_ants()
                if n_add > 0:
                    colony.spawn_ants(n_add, start_outbound=True)
                continue

            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), flags)
                renderer.screen = screen
                camera.set_screen_size(screen.get_size())
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if food_bar.selected is not None:
                        food_bar.selected = None
                        food_bar.cancel_press()
                        place_click_active = False
                    else:
                        running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_h:
                    renderer.show_help = not renderer.show_help
                elif event.key == pygame.K_v:
                    renderer.show_loco_debug = not renderer.show_loco_debug
                elif event.key == pygame.K_p:
                    renderer.show_pheromone = not renderer.show_pheromone
                elif event.key == pygame.K_r:
                    world, colony, rng = build_sim(cfg)
                    camera.center = world.home_spawn.copy()
                    sim_time = 0.0
                    accumulator = 0.0
                elif event.key == pygame.K_F12:
                    last_shot = capture(
                        screen, shot_dir, prefix=f"t{sim_time:.0f}s"
                    )
                    print(f"[screenshot] {last_shot}")
                elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    # Quick-select food types
                    idx = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2}[event.key]
                    if idx < len(food_bar._items):
                        kind = food_bar._items[idx][0]
                        food_bar.selected = (
                            None if food_bar.selected == kind else kind
                        )
            elif event.type == pygame.MOUSEWHEEL and (
                sidebar.contains_screen_pos(screen, pygame.mouse.get_pos())
                or food_bar.contains_screen_pos(screen, pygame.mouse.get_pos())
            ):
                pass
            elif (
                food_bar.selected is not None
                and event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and not food_bar.contains_screen_pos(screen, event.pos)
                and not sidebar.contains_screen_pos(screen, event.pos)
            ):
                # Food tool: click places, drag still pans
                food_bar.begin_map_press(event.pos)
                place_click_active = True
                camera._drag_pan = False
            elif place_click_active and event.type == pygame.MOUSEMOTION:
                if food_bar.update_map_drag(event.pos):
                    # Crossed drag threshold → hand off to camera pan
                    if not camera._drag_pan:
                        camera._drag_pan = True
                        camera._drag_last = event.pos
                    camera.handle_event(event)
            elif place_click_active and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if food_bar.end_map_press():
                    world_pos = camera.screen_to_world(event.pos[0], event.pos[1])
                    if world.wrap:
                        world_pos = world.wrap_position(world_pos)
                    kind = food_bar.selected
                    if kind:
                        world.spawn_food(kind, world_pos, snap=True)
                camera._drag_pan = False
                place_click_active = False
            else:
                camera.handle_event(event)

        keys = pygame.key.get_pressed()
        camera.update_keyboard_pan(frame_dt, keys)
        sidebar.update(on_change=on_cfg_change)

        # B2: sidebar spawn buttons
        n_spawn = sidebar.consume_spawn()
        if n_spawn > 0:
            colony.spawn_ants(n_spawn, start_outbound=True)
        elif n_spawn < 0:
            # Remove idle ants first, then any ant
            to_remove = min(-n_spawn, len(colony.ants))
            idle = [a for a in colony.ants if a.state.name == "IDLE_IN_NEST"]
            victims = idle[:to_remove] or colony.ants[:to_remove]
            for a in victims:
                colony.ants.remove(a)

        if not paused:
            accumulator += frame_dt
            # If last step already cost more than a frame, never multi-step:
            # running 2× expensive steps turns 7 fps into ~3–5 fps death spiral.
            budget_steps = max_substeps
            if last_step_ms > (1000.0 / max(fps_cap, 1)) * 0.85:
                budget_steps = 1
            if accumulator > fixed_dt * budget_steps:
                accumulator = fixed_dt * budget_steps
            steps = 0
            while accumulator >= fixed_dt and steps < budget_steps:
                t0 = time.perf_counter()
                colony.step(fixed_dt)
                last_step_ms = (time.perf_counter() - t0) * 1000.0
                sim_time += fixed_dt
                accumulator -= fixed_dt
                steps += 1
            # Drop leftover debt so we don't keep stacking lag forever
            if last_step_ms > 40.0:
                accumulator = 0.0

        fps = clock.get_fps()
        renderer.draw(
            world, colony, fps, sim_time, paused, sim_step_ms=last_step_ms
        )
        # Ghost preview of selected prey under the cursor
        if (
            food_bar.selected
            and not food_bar.contains_screen_pos(screen, pygame.mouse.get_pos())
            and not sidebar.contains_screen_pos(screen, pygame.mouse.get_pos())
        ):
            mx, my = pygame.mouse.get_pos()
            ghost = renderer.food_sprites.get_scaled(
                f"assets/food/{food_bar.selected}.png",
                48.0,
                camera.zoom,
            )
            if ghost is not None:
                g = ghost.copy()
                g.set_alpha(120)
                rect = g.get_rect(center=(mx, my))
                screen.blit(g, rect)
        food_bar.draw(screen, ant_count=len(colony.ants))
        sidebar.update_stats(colony)
        sidebar.draw(screen)
        pygame.display.flip()

    pygame.quit()


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    run(path)


if __name__ == "__main__":
    main()

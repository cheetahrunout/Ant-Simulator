"""Pygame drawing for world, nests, ants, pheromones, HUD."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pygame

from src.agents.ant import AntState, WorkerAnt
from src.render.ant_sprite import get_ant_sprites
from src.render.camera import Camera
from src.render.food_sprite import get_food_sprites
from src.render.nest_tiles import get_nest_tiles, wall_mask_at
from src.sim import tiles as T
from src.sim.colony import Colony
from src.sim.world import World
from src.util.vec import Vec2


class Renderer:
    def __init__(
        self, cfg: Dict[str, Any], screen: pygame.Surface, camera: Camera
    ) -> None:
        self.cfg = cfg
        self.screen = screen
        self.camera = camera
        self.rcfg = cfg["render"]
        self.font = pygame.font.SysFont("consolas", 16)
        self.font_sm = pygame.font.SysFont("consolas", 13)
        self.font_tiny = pygame.font.SysFont("consolas", 10)
        self.show_help = True
        self.show_loco_debug = bool(self.rcfg.get("show_loco_debug", False))
        # P toggles heatmap + per-tile numbers together
        self.show_pheromone = bool(self.rcfg.get("show_pheromone", True))
        self.ant_sprites = get_ant_sprites()
        self.food_sprites = get_food_sprites()
        self.nest_tiles = get_nest_tiles()

    def draw(
        self,
        world: World,
        colony: Colony,
        fps: float,
        sim_time: float,
        paused: bool,
        sim_step_ms: float = 0.0,
    ) -> None:
        bg = tuple(self.rcfg["bg_color"])
        self.screen.fill(bg)

        self._draw_arena_floor(world)
        self._draw_tile_roles(world)
        if self.show_pheromone:
            self._draw_pheromone(world)
        self._draw_nest_markers(world, colony)
        self._draw_food(world)
        self._draw_ants(colony.ants)
        if self.show_loco_debug:
            # Haul grip lines + steer vectors (V key)
            self._draw_haul_links(world, colony.ants)
            self._draw_loco_debug(colony.ants)
        self._draw_hud(world, colony, fps, sim_time, paused, sim_step_ms)

    def _draw_arena_floor(self, world: World) -> None:
        color = tuple(self.rcfg["arena_floor"])
        tl = self.camera.world_to_screen(Vec2(0, 0))
        br = self.camera.world_to_screen(Vec2(world.width, world.height))
        rect = pygame.Rect(tl[0], tl[1], br[0] - tl[0], br[1] - tl[1])
        pygame.draw.rect(self.screen, color, rect)

    def _draw_pheromone(self, world: World) -> None:
        """Draw trail heatmap with per-tile values (always on with P heat)."""
        grid = world.pheromones
        cs = grid.cell_size
        # Visible world AABB
        corners = [
            self.camera.screen_to_world(0, 0),
            self.camera.screen_to_world(self.camera.screen_w, 0),
            self.camera.screen_to_world(0, self.camera.screen_h),
            self.camera.screen_to_world(
                self.camera.screen_w, self.camera.screen_h
            ),
        ]
        min_x = min(c.x for c in corners) - cs
        max_x = max(c.x for c in corners) + cs
        min_y = min(c.y for c in corners) - cs
        max_y = max(c.y for c in corners) + cs

        c0 = max(0, int(min_x / cs) - 1)
        c1 = min(grid.cols - 1, int(max_x / cs) + 1)
        r0 = max(0, int(min_y / cs) - 1)
        r1 = min(grid.rows - 1, int(max_y / cs) + 1)

        if c1 < c0 or r1 < r0:
            return

        tmax = grid.max_trail()
        if tmax < 1e-6:
            return

        cell_px = max(1, int(cs * self.camera.zoom))
        tr = tuple(self.rcfg.get("trail_heatmap_color", [255, 90, 40]))
        alpha_max = int(self.rcfg.get("pheromone_alpha", 160))
        show_nums = self.camera.zoom > 1.5

        blocked = grid.blocked
        # Sparse: only active trail cells in the view (no full-grid nonzero scan)
        for gr, gc in grid.active_trail_cells():
            if gr < r0 or gr > r1 or gc < c0 or gc > c1:
                continue
            v = float(grid.trail[gr, gc])
            if v < 1e-6:
                continue

            is_wall = bool(blocked[gr, gc])
            wx = gc * cs
            wy = gr * cs
            tl = self.camera.world_to_screen(Vec2(wx, wy))
            br = self.camera.world_to_screen(Vec2(wx + cs, wy + cs))
            w = max(1, int(br[0] - tl[0]))
            h = max(1, int(br[1] - tl[1]))
            rect = pygame.Rect(int(tl[0]), int(tl[1]), w, h)

            # Heat color only on free tiles — walls keep their normal color
            if not is_wall:
                t_rel = min(1.0, v / max(tmax, 1e-6))
                t_abs = min(1.0, v / 40.0)
                t = max(t_rel * 0.45, t_abs)
                a = int(alpha_max * (0.2 + 0.8 * t))
                color = (
                    min(255, int(tr[0] * (0.35 + 0.65 * t))),
                    min(255, int(tr[1] * (0.25 + 0.55 * t))),
                    min(255, int(tr[2] * (0.15 + 0.35 * t))),
                )
                dim = (
                    color[0] * a // 255,
                    color[1] * a // 255,
                    color[2] * a // 255,
                )
                if dim[0] + dim[1] + dim[2] >= 6:
                    pygame.draw.rect(self.screen, dim, rect)

            if show_nums:
                if v >= 10:
                    txt = f"{v:.0f}"
                elif v >= 1:
                    txt = f"{v:.1f}"
                else:
                    txt = f"{v:.2f}"
                surf = self.font_tiny.render(txt, True, (255, 240, 180))
                tx = rect.x + max(0, (rect.w - surf.get_width()) // 2)
                ty = rect.y + max(0, (rect.h - surf.get_height()) // 2)
                self.screen.blit(surf, (tx, ty))

    def _view_cell_window(self, world: World) -> Tuple[int, int, int, int, float]:
        """Visible (r0,r1,c0,c1) cell range + cell size."""
        grid = world.pheromones
        cs = grid.cell_size
        corners = [
            self.camera.screen_to_world(0, 0),
            self.camera.screen_to_world(self.camera.screen_w, 0),
            self.camera.screen_to_world(0, self.camera.screen_h),
            self.camera.screen_to_world(
                self.camera.screen_w, self.camera.screen_h
            ),
        ]
        min_x = min(c.x for c in corners) - cs
        max_x = max(c.x for c in corners) + cs
        min_y = min(c.y for c in corners) - cs
        max_y = max(c.y for c in corners) + cs
        c0 = max(0, int(min_x / cs) - 1)
        c1 = min(grid.cols - 1, int(max_x / cs) + 1)
        r0 = max(0, int(min_y / cs) - 1)
        r1 = min(grid.rows - 1, int(max_y / cs) + 1)
        return r0, r1, c0, c1, cs

    def _draw_tile_roles(self, world: World) -> None:
        """
        Draw structural tile roles from the grid (perfect nest/wall alignment):
          NEST  — sandy floor tiles
          WALL  — clay autotile walls (corners / straights / T / ends)
          FOOD  — not filled (prey sprites only)
          OPEN  — arena (already drawn as floor)
        """
        grid = world.pheromones
        r0, r1, c0, c1, cs = self._view_cell_window(world)
        if c1 < c0 or r1 < r0:
            return

        cell_px = max(1, int(round(cs * self.camera.zoom)))
        # When zoomed far out, skip per-cell sprites (walls via solid rects)
        if cell_px < 2 and (c1 - c0) * (r1 - r0) > 12000:
            self._draw_walls_from_nests(world)
            return

        use_tiles = bool(self.rcfg.get("use_nest_tiles", True)) and self.nest_tiles.ok
        dark = tuple(self.rcfg["nest_floor"])
        bright = tuple(self.rcfg["nest_floor_bright"])
        wall_c = tuple(self.rcfg["wall_color"])
        role_full = grid.role
        role = role_full[r0 : r1 + 1, c0 : c1 + 1]
        rows, cols = int(role_full.shape[0]), int(role_full.shape[1])
        nest_bright_bounds = [
            n.bounds for n in world.nests if n.light_level >= 0.4
        ]
        nest_dark_lookups = [
            (getattr(n, "_nest_lookup", set()), float(n.light_level))
            for n in world.nests
            if n.light_level < 0.35
        ]
        bank = self.nest_tiles

        # Only non-open cells (numpy), not a full Python double loop.
        nz = np.nonzero((role == T.WALL) | (role == T.NEST))
        for ri, ci in zip(nz[0].tolist(), nz[1].tolist()):
            role_v = int(role[ri, ci])
            r = r0 + ri
            c = c0 + ci
            wx, wy = c * cs, r * cs
            # Exact screen footprint so tiles abut with no gaps/overlaps
            tl = self.camera.world_to_screen(Vec2(wx, wy))
            br = self.camera.world_to_screen(Vec2(wx + cs, wy + cs))
            sx, sy = int(tl[0]), int(tl[1])
            pw = max(1, int(br[0]) - sx)
            ph = max(1, int(br[1]) - sy)
            px = max(pw, ph)

            if role_v == T.WALL:
                if use_tiles:
                    mask = wall_mask_at(role_full, r, c, rows, cols)
                    surf = bank.wall_for_mask(mask, px)
                    if surf is not None:
                        if surf.get_width() != pw or surf.get_height() != ph:
                            surf = pygame.transform.scale(surf, (pw, ph))
                        self.screen.blit(surf, (sx, sy))
                        continue
                self._fill_world_rect(wx, wy, cs, cs, wall_c)
            elif role_v == T.NEST:
                if use_tiles:
                    surf = bank.floor_for_cell(r, c, px)
                    if surf is not None:
                        if surf.get_width() != pw or surf.get_height() != ph:
                            surf = pygame.transform.scale(surf, (pw, ph))
                        self.screen.blit(surf, (sx, sy))
                        # Occupied / dark nests read as subterranean soil
                        darkened = False
                        for lookup, ll in nest_dark_lookups:
                            if (r, c) in lookup:
                                shade = pygame.Surface((pw, ph), pygame.SRCALPHA)
                                shade.fill((20, 12, 6, int(28 * (0.35 - ll) / 0.35)))
                                self.screen.blit(shade, (sx, sy))
                                darkened = True
                                break
                        if not darkened:
                            # Slight brighten for well-lit nests (empty_poor etc.)
                            for bx, by, bw, bh in nest_bright_bounds:
                                if bx <= wx < bx + bw and by <= wy < by + bh:
                                    glow = pygame.Surface((pw, ph), pygame.SRCALPHA)
                                    glow.fill((255, 240, 200, 36))
                                    self.screen.blit(glow, (sx, sy))
                                    break
                        continue
                color = dark
                for bx, by, bw, bh in nest_bright_bounds:
                    if bx <= wx < bx + bw and by <= wy < by + bh:
                        color = bright
                        break
                self._fill_world_rect(wx, wy, cs, cs, color)

    def _draw_walls_from_nests(self, world: World) -> None:
        color = tuple(self.rcfg["wall_color"])
        for x, y, w, h in world.walls:
            self._fill_world_rect(x, y, w, h, color)

    def _draw_nest_markers(self, world: World, colony: Colony) -> None:
        ui = tuple(self.rcfg["ui_text"])
        for nest in world.nests:
            ex, ey = self.camera.world_to_screen(nest.entrance_pos)
            col = (80, 180, 100) if nest.occupied else (120, 120, 140)
            r = max(3, int(5 * self.camera.zoom))
            pygame.draw.circle(self.screen, col, (int(ex), int(ey)), r, 1)
            label = f"{nest.name}"
            surf = self.font_sm.render(label, True, ui)
            self.screen.blit(surf, (ex + 6, ey - 10))
            if nest.occupied:
                hx, hy = self.camera.world_to_screen(nest.home_tile)
                ur = float(self.cfg.get("forage", {}).get("unload_radius", 14.0))
                hr = max(3, int(ur * self.camera.zoom))
                pygame.draw.circle(
                    self.screen, (90, 200, 255), (int(hx), int(hy)), hr, 2
                )
                store = float(colony.food_store)
                # Prominent nest food readout at the drop-off point
                food_tag = f"nest food: {store:.0f}"
                tag = self.font.render(food_tag, True, (255, 230, 120))
                shadow = self.font.render(food_tag, True, (0, 0, 0))
                tx, ty = int(hx + hr + 4), int(hy - 10)
                self.screen.blit(shadow, (tx + 1, ty + 1))
                self.screen.blit(tag, (tx, ty))
                sub = self.font_sm.render("home tile", True, (140, 210, 255))
                self.screen.blit(sub, (tx, ty + 18))

    def _draw_food(self, world: World) -> None:
        """Carcasses (layered damage) + loose part sprites (no yellow blobs)."""
        default_base = tuple(self.rcfg.get("food_color", [220, 180, 50]))
        cs = world.tile_size
        ui = tuple(self.rcfg["ui_text"])
        break_work = float(self.cfg.get("forage", {}).get("break_work", 6.0))
        zoom = self.camera.zoom

        for food in world.foods:
            if food.depleted:
                continue
            half = max(cs * 0.5, float(food.radius))
            c0 = int((food.pos.x - half) / cs)
            r0 = int((food.pos.y - half) / cs)
            c1 = int((food.pos.x + half - 1e-6) / cs)
            r1 = int((food.pos.y + half - 1e-6) / cs)
            wx = c0 * cs
            wy = r0 * cs
            size_x = (c1 - c0 + 1) * cs
            size_y = (r1 - r0 + 1) * cs
            fit = max(size_x, size_y)

            base = tuple(getattr(food, "color", None) or default_base)
            kind = str(getattr(food, "kind", "fruit_fly"))
            remaining = getattr(food, "remaining", None)
            if remaining is not None:
                remain_ids = {p.id for p in remaining}
            else:
                remain_ids = set()

            sprite_dir = str(getattr(food, "sprite_dir", "") or "")
            fallback = str(getattr(food, "sprite_path", "") or "")
            sprite = None
            if remain_ids:
                sprite = self.food_sprites.compose_carcass(
                    kind,
                    remain_ids,
                    fit,
                    zoom,
                    sprite_dir=sprite_dir,
                    fallback_path=fallback,
                )
            elif fallback:
                sprite = self.food_sprites.get_scaled(fallback, fit, zoom)

            if sprite is not None:
                cx, cy = self.camera.world_to_screen(food.pos)
                rect = sprite.get_rect(center=(int(cx), int(cy)))
                self.screen.blit(sprite, rect)
            else:
                # Last-resort footprint (muted, not bright yellow blob)
                color = (
                    int(base[0] * 0.55),
                    int(base[1] * 0.55),
                    int(base[2] * 0.55),
                )
                self._fill_world_rect(wx, wy, size_x, size_y, color)

            # Labels + dislodge bar only with P heat overlay
            if self.show_pheromone:
                label_pos = self.camera.world_to_screen(Vec2(wx + size_x, wy))
                name = getattr(food, "label", None) or kind
                n_left = food.parts_left() if hasattr(food, "parts_left") else 0
                label = f"{name} {n_left} left"
                surf = self.font_sm.render(label, True, ui)
                self.screen.blit(surf, (int(label_pos[0]) + 2, int(label_pos[1])))
                prog = float(getattr(food, "break_progress", 0.0))
                if prog > 0 and break_work > 0:
                    bar_w = max(20, int(40 * zoom))
                    bar_h = max(3, int(4 * zoom))
                    bx, by = int(label_pos[0]) + 2, int(label_pos[1]) + 16
                    pygame.draw.rect(self.screen, (40, 40, 40), (bx, by, bar_w, bar_h))
                    fill = int(bar_w * min(1.0, prog / break_work))
                    pygame.draw.rect(
                        self.screen, (220, 180, 60), (bx, by, fill, bar_h)
                    )

        # Loose / hauled parts — same scale family as full prey, not haul radius
        for part in getattr(world, "parts", []):
            if part.delivered:
                continue
            cx, cy = self.camera.world_to_screen(part.pos)
            kind = str(getattr(part, "parent_kind", "fruit_fly"))
            # Match carcass draw fit (parent footprint), not small collision radius
            parent_r = float(getattr(part, "parent_radius", 0.0) or 0.0)
            parent_spr = float(getattr(part, "parent_sprite_size", 0.0) or 0.0)
            if parent_r <= 1e-6:
                # Fallback: live carcass of same kind, else inflate haul radius
                for food in world.foods:
                    if (
                        not food.depleted
                        and str(getattr(food, "kind", "")) == kind
                    ):
                        parent_r = float(food.radius)
                        parent_spr = max(
                            parent_spr,
                            float(getattr(food, "sprite_world_size", 0.0) or 0.0),
                        )
                        break
            if parent_r <= 1e-6:
                parent_r = max(12.0, float(part.radius) * 5.0)
            half = max(cs * 0.5, parent_r)
            # Same tile-span logic as carcass so part scale matches full body
            span = 2.0 * half
            world_size = max(span, parent_spr, 24.0)
            sprite = self.food_sprites.get_part_sprite(
                kind,
                str(part.part_id),
                world_size,
                zoom,
                angle=float(getattr(part, "angle", 0.0)),
                sprite_dir=f"assets/food/{kind}",
                color=tuple(part.color[:3]) if part.color else (120, 100, 70),
            )
            if sprite is not None:
                rect = sprite.get_rect(center=(int(cx), int(cy)))
                self.screen.blit(sprite, rect)
                tag_off = max(rect.width, rect.height) // 2 + 2
            else:
                tag_off = max(4, int(part.radius * zoom))
            # Part tags (body / leg / x3) only with P heat overlay
            if self.show_pheromone and zoom >= 0.85:
                n_carry = len(part.carrier_ids)
                tag = f"{part.label}"
                if n_carry:
                    tag += f" x{n_carry}"
                surf = self.font_tiny.render(tag, True, ui)
                self.screen.blit(surf, (int(cx) + tag_off, int(cy) - 6))

    def _draw_haul_links(self, world: World, ants: List[WorkerAnt]) -> None:
        """Faint lines from gripping ants to their part."""
        by_id = {a.ant_id: a for a in ants}
        for part in getattr(world, "parts", []):
            if part.delivered or not part.carrier_ids:
                continue
            px, py = self.camera.world_to_screen(part.pos)
            for aid in part.carrier_ids:
                ant = by_id.get(aid)
                if ant is None:
                    continue
                ax, ay = self.camera.world_to_screen(ant.pos)
                pygame.draw.line(
                    self.screen,
                    (200, 160, 80),
                    (int(ax), int(ay)),
                    (int(px), int(py)),
                    max(1, int(self.camera.zoom)),
                )

    def _fill_world_rect(
        self, x: float, y: float, w: float, h: float, color: Tuple[int, int, int]
    ) -> None:
        tl = self.camera.world_to_screen(Vec2(x, y))
        br = self.camera.world_to_screen(Vec2(x + w, y + h))
        rect = pygame.Rect(
            int(tl[0]),
            int(tl[1]),
            max(1, int(br[0] - tl[0])),
            max(1, int(br[1] - tl[1])),
        )
        pygame.draw.rect(self.screen, color, rect)

    def _draw_ants(self, ants: List[WorkerAnt]) -> None:
        acfg = self.cfg["ants"]
        base = tuple(acfg["color"])
        # use_sprites may be bool or 0/1 from the live sidebar
        use_sprites = (
            bool(int(acfg.get("use_sprites", 1))) and self.ant_sprites.ok
        )
        # World-space body length → screen scale from sheet height
        body_h = float(acfg.get("sprite_world_height", 14.0))
        stride = float(acfg.get("sprite_stride", 10.0))
        bank = self.ant_sprites

        for ant in ants:
            sx, sy = self.camera.world_to_screen(ant.pos)

            if use_sprites:
                scale = (body_h * self.camera.zoom) / max(bank.frame_h, 1)
                # Slightly smaller when zoomed way out so swarms stay readable
                if self.camera.zoom < 0.25:
                    scale *= 0.85
                frame_i = bank.frame_index(ant.walk_phase, stride=stride)
                if ant.state == AntState.IDLE_IN_NEST and not ant.is_carrying:
                    # Mostly idle pose (slow crawl still advances walk_phase)
                    frame_i = bank.frame_index(ant.walk_phase * 0.25, stride=stride)

                tint = None
                if ant.is_carrying:
                    tint = (255, 200, 140)  # warm when hauling food
                elif ant.state == AntState.FORAGE_RETURN:
                    tint = (255, 230, 200)

                surf = bank.get(frame_i, ant.heading, scale, tint=tint)
                if surf is not None:
                    rect = surf.get_rect(center=(int(sx), int(sy)))
                    self.screen.blit(surf, rect)
                    # Hauling is shown by the part sprite + haul link (no yellow pellet)
                    continue

            # Fallback dots if sprites missing
            r = max(1.5, ant.radius * self.camera.zoom)
            if ant.is_carrying:
                c = (180, 90, 30)
            elif ant.state == AntState.FORAGE_OUTBOUND:
                c = (50, 50, 50)
            elif ant.state == AntState.FORAGE_RETURN:
                c = (160, 80, 25)
            elif ant.state == AntState.IDLE_IN_NEST:
                c = base
            else:
                c = (min(255, base[0] + 30), min(255, base[1] + 20), base[2])
            pygame.draw.circle(self.screen, c, (int(sx), int(sy)), int(r))

    def _draw_vector(
        self, origin: Vec2, vec: Vec2, scale: float, color: Tuple[int, int, int]
    ) -> None:
        if vec.length_sq() < 1e-8:
            return
        end = origin + vec.normalized() * scale
        ox, oy = self.camera.world_to_screen(origin)
        ex, ey = self.camera.world_to_screen(end)
        pygame.draw.line(
            self.screen, color, (int(ox), int(oy)), (int(ex), int(ey)), 1
        )

    def _draw_loco_debug(self, ants: List[WorkerAnt]) -> None:
        """
        Debug overlay for every ant (toggle with V — not WASD):
          gold   — heading
          cyan   — wall-follow
          magenta — meander
          orange — separation
          white  — combined steering
        """
        scale = 18.0
        line_w = max(1, int(self.camera.zoom))
        for ant in ants:
            sx, sy = self.camera.world_to_screen(ant.pos)
            # Heading stick (same as former always-on marker)
            tip = ant.pos + Vec2.from_angle(ant.heading, ant.radius * 2.2)
            tx, ty = self.camera.world_to_screen(tip)
            pygame.draw.line(
                self.screen,
                (200, 160, 60),
                (int(sx), int(sy)),
                (int(tx), int(ty)),
                line_w,
            )
            dbg = ant.last_debug
            if dbg is None:
                continue
            self._draw_vector(ant.pos, dbg.wall, scale, (80, 220, 220))
            self._draw_vector(ant.pos, dbg.meander, scale * 0.8, (220, 80, 200))
            self._draw_vector(ant.pos, dbg.avoid, scale * 0.7, (240, 160, 60))
            self._draw_vector(ant.pos, dbg.combined, scale * 1.2, (240, 240, 240))

    def _draw_hud(
        self,
        world: World,
        colony: Colony,
        fps: float,
        sim_time: float,
        paused: bool,
        sim_step_ms: float = 0.0,
    ) -> None:
        text_color = tuple(self.rcfg["ui_text"])
        counts = colony.count_by_state()
        out_b = counts.get("FORAGE_OUTBOUND", 0)
        ret = counts.get("FORAGE_RETURN", 0)
        idle = counts.get("IDLE_IN_NEST", 0)
        food_left = (
            world.map_food_left()
            if hasattr(world, "map_food_left")
            else sum(f.amount for f in world.foods)
        )
        n_parts = len(getattr(world, "parts", []))
        n_ants = len(colony.ants)
        trail_max = world.pheromones.max_trail()
        nest_food = float(colony.food_store)
        sim_note = f"  sim={sim_step_ms:.0f}ms" if sim_step_ms > 0.5 else ""
        lines = [
            f"NEST FOOD: {nest_food:.0f}  |  deliveries={colony.forage_deliveries}  "
            f"map food={food_left:.0f}  parts={n_parts}  trail_max={trail_max:.1f}",
            f"ants={n_ants} out={out_b} return={ret} idle={idle}  "
            f"t={sim_time:6.1f}s  fps={fps:5.1f}{sim_note}"
            + ("  [PAUSED]" if paused else ""),
            f"phero={'ON' if self.show_pheromone else 'OFF'}  "
            f"debug={'ON' if self.show_loco_debug else 'OFF'}  "
            f"zoom={self.camera.zoom:.2f}",
        ]
        if self.show_help:
            lines.append(
                "drag/WASD pan | wheel zoom | Space pause | R reset | "
                "P heat+food labels | V debug | Tab/cfg | Esc quit"
            )
            lines.append(
                "bottom bar: pick prey, click map to drop  |  1/2/3 quick pick"
            )



        y = 8
        for line in lines:
            surf = self.font.render(line, True, text_color)
            shadow = self.font.render(line, True, (0, 0, 0))
            self.screen.blit(shadow, (9, y + 1))
            self.screen.blit(surf, (8, y))
            y += 18

"""Tile-aligned world: roles (open/wall/nest/food) + continuous ants."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, TYPE_CHECKING  # noqa: F401

from src.sim import tiles as T
from src.sim.carcass import Carcass, FoodPart, resolve_hauling, total_prey_nutrition
from src.sim.food import (
    all_food_gone,
    build_food_sources,
    spawn_food_at,
    spawn_random_food,
)
from src.sim.grid import PheromoneGrid
from src.sim.nest import NestSite, all_wall_rects, build_default_nests
from src.util.rng import Rng
from src.util.vec import Vec2

if TYPE_CHECKING:
    from src.sim.colony import Colony

Rect = Tuple[float, float, float, float]


class World:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        wcfg = cfg["world"]
        pcfg = cfg.get("pheromone", {})
        # Single tile size for structure + pheromone
        tile = float(
            wcfg.get("tile_size", pcfg.get("cell_size", wcfg.get("cell_size", 20.0)))
        )
        self.tile_size = tile
        self.cell_size = tile  # alias used elsewhere
        self.wrap = bool(wcfg.get("wrap", True))
        self.cfg = cfg

        width = float(wcfg["width"])
        height = float(wcfg["height"])

        self.pheromones = PheromoneGrid(width, height, tile, wrap=self.wrap)
        # World size snaps to whole tiles
        self.width = self.pheromones.world_w
        self.height = self.pheromones.world_h

        self.nests: List[NestSite] = build_default_nests(cfg["nest"], tile=tile)
        self.home_nest = next(n for n in self.nests if n.occupied)

        # Paint structural roles: OPEN default, then WALL + NEST from nests
        self.pheromones.reset_roles()
        for nest in self.nests:
            self.pheromones.paint_nest(nest)

        # Legacy wall rect list (wall-sense / draw fallback)
        self.walls: List[Rect] = list(all_wall_rects(self.nests))

        # Carcasses (whole prey) + detached parts
        self.foods: List[Carcass] = build_food_sources(cfg, tile=tile)
        self.parts: List[FoodPart] = []
        self._paint_food_roles()

        self._seed_nest_scent(strength=float(pcfg.get("nest_seed", 40.0)))
        # D2: dirty flag — repaint food roles only when something changes
        self._food_dirty: bool = True

    def _paint_food_roles(self) -> None:
        """Mark FOOD tiles from carcasses + loose parts."""
        g = self.pheromones
        g.clear_food_roles()
        cs = g.cell_size

        def stamp(pos: Vec2, radius: float) -> None:
            half = max(cs * 0.5, float(radius))
            c0 = int((pos.x - half) / cs)
            r0 = int((pos.y - half) / cs)
            c1 = int((pos.x + half - 1e-6) / cs)
            r1 = int((pos.y + half - 1e-6) / cs)
            for rr in range(r0, r1 + 1):
                for cc in range(c0, c1 + 1):
                    r, c = rr, cc
                    if g.wrap:
                        r %= g.rows
                        c %= g.cols
                    g.set_food_cell(r, c, True)

        for food in self.foods:
            if food.depleted:
                continue
            stamp(food.pos, food.radius)
        for part in self.parts:
            if part.delivered:
                continue
            stamp(part.pos, part.radius)

    @property
    def home_spawn(self) -> Vec2:
        return self.home_nest.interior_spawn.copy()

    @property
    def home_tile(self) -> Vec2:
        """Single drop-off point for foragers."""
        return self.home_nest.home_tile.copy()

    @property
    def home_entrance(self) -> Vec2:
        return self.home_nest.entrance_pos.copy()

    @property
    def cargo_entrance(self) -> Vec2:
        """Wide/long right-side mouth if present; else main entrance."""
        nest = self.home_nest
        if getattr(nest, "cargo_path", False) and nest.cargo_entrance_pos.length_sq() > 1e-6:
            return nest.cargo_entrance_pos.copy()
        return self.home_entrance

    def at_home_tile(self, pos: Vec2) -> bool:
        r = float(self.cfg.get("forage", {}).get("unload_radius", 14.0))
        return self.wrap_delta(pos, self.home_tile).length() <= r

    def wrap_position(self, pos: Vec2) -> Vec2:
        if not self.wrap:
            return pos.copy()
        x = pos.x % self.width
        y = pos.y % self.height
        if x < 0:
            x += self.width
        if y < 0:
            y += self.height
        return Vec2(x, y)

    def wrap_delta(self, from_pos: Vec2, to_pos: Vec2) -> Vec2:
        dx = to_pos.x - from_pos.x
        dy = to_pos.y - from_pos.y
        if self.wrap:
            if dx > self.width * 0.5:
                dx -= self.width
            elif dx < -self.width * 0.5:
                dx += self.width
            if dy > self.height * 0.5:
                dy -= self.height
            elif dy < -self.height * 0.5:
                dy += self.height
        return Vec2(dx, dy)

    def is_inside_nest(self, pos: Vec2) -> bool:
        return self.pheromones.role_at(pos) == T.NEST

    def is_inside_home(self, pos: Vec2) -> bool:
        if self.pheromones.role_at(pos) != T.NEST:
            return False
        return self.home_nest.contains_point(pos)

    def circle_hits_wall(self, pos: Vec2, radius: float) -> bool:
        return self.pheromones.circle_hits_wall(pos, radius)

    def resolve_circle(
        self, pos: Vec2, radius: float, max_iters: int = 4
    ) -> Vec2:
        return self.pheromones.resolve_circle(pos, radius, max_iters)

    def map_food_left(self) -> float:
        return total_prey_nutrition(self.foods, self.parts)

    def _seed_nest_scent(self, strength: float) -> None:
        nest = self.home_nest
        self.pheromones.deposit_disk(nest.home_tile, strength * 1.4, radius_cells=2)
        self.pheromones.deposit_disk(nest.entrance_pos, strength, radius_cells=2)

    def refresh_nest_scent(self, dt: float) -> None:
        pcfg = self.cfg.get("pheromone", {})
        rate = float(pcfg.get("nest_emit_rate", 25.0)) * dt
        if rate <= 0:
            return
        nest = self.home_nest
        self.pheromones.deposit_disk(nest.home_tile, rate, radius_cells=2, layer="nest")
        self.pheromones.deposit_disk(
            nest.entrance_pos, rate * 0.45, radius_cells=1, layer="nest"
        )

    def resolve_hauling(self, colony: "Colony", dt: float) -> None:
        """Move gripped parts as rigid groups (sum of ant pull vectors)."""
        ants_by_id = {a.ant_id: a for a in colony.ants}
        fcfg = self.cfg.get("forage", {})
        resolve_hauling(
            self.parts, ants_by_id, self, dt, fcfg, rng=getattr(colony, "rng", None)
        )
        # Deliver any part that reached home
        self._try_deliver_parts(colony, ants_by_id)
        # D2: only repaint when a delivery (or other mutation) marked dirty
        if self._food_dirty:
            self._paint_food_roles()
            self._food_dirty = False

    def _try_deliver_parts(self, colony: "Colony", ants_by_id: Dict[int, Any]) -> None:
        from src.agents.ant import AntState

        fcfg = self.cfg.get("forage", {})
        for part in self.parts:
            if part.delivered or not part.carrier_ids:
                continue
            if not self.at_home_tile(part.pos):
                continue
            if self.circle_hits_wall(part.pos, part.radius * 0.4):
                continue
            # Deliver
            colony.food_store += part.nutrition
            colony.forage_deliveries += 1
            part.delivered = True
            self._food_dirty = True  # D2: roles need repaint after delivery
            for aid in list(part.carrier_ids):
                ant = ants_by_id.get(aid)
                if ant is None:
                    continue
                ant.carried_part_id = None
                ant.grip_slot = -1
                ant.carrying_food = 0.0
                ant.food_quality = 0.0
                ant.last_trail_cell = None
                ant.stuck_time = 0.0
                ant.haul_frustration = 0.0
                ant.haul_detour_active = False
                ant.pickup_pos = None
                ant.nestmates_at_pickup = 0
                ant.found_as_scout = False
                ant.trip_distance = 0.0
                sip = float(fcfg.get("energy_delivery_sip", 0.12))
                ant.energy = min(1.0, float(ant.energy) + sip)
                ant._set_state(AntState.IDLE_IN_NEST)
            part.carrier_ids.clear()
        # Prune delivered
        self.parts = [p for p in self.parts if not p.delivered]

    def step_environment(self, dt: float, rng: Rng | None = None) -> None:
        pcfg = self.cfg.get("pheromone", {})
        self.refresh_nest_scent(dt)
        self.pheromones.step(
            dt,
            floor=float(pcfg.get("floor", 0.5)),
            trail_evaporation=float(pcfg.get("trail_evaporation", 2.0)),
            nest_evaporation=float(pcfg.get("nest_evaporation", 0.5)),
            alarm_evaporation=float(pcfg.get("alarm_evaporation", 12.0)),
            diffusion=float(pcfg.get("diffusion", 0.0)),
            trail_high_threshold=float(pcfg.get("trail_high_threshold", 40.0)),
            trail_high_fade_rate=float(pcfg.get("trail_high_fade_rate", 0.5)),
        )
        if rng is not None:
            self._maybe_respawn_food(rng)

    def _maybe_respawn_food(self, rng: Rng) -> None:
        fcfg = self.cfg.get("food", {})
        if not fcfg.get("respawn_when_empty", True):
            return
        if not all_food_gone(self.foods, self.parts):
            return
        self.foods = spawn_random_food(
            self.cfg,
            home_pos=self.home_entrance,
            world_w=self.width,
            world_h=self.height,
            nests_bounds=[n.bounds for n in self.nests],
            rng=rng,
            wrap=self.wrap,
            tile=self.tile_size,
        )
        self.parts = []
        self._paint_food_roles()

    def spawn_food(self, kind: str, pos: Vec2, snap: bool = True) -> Carcass:
        """Player / UI: drop a prey carcass at a world position."""
        carcass = spawn_food_at(
            self.cfg, kind, pos, tile=self.tile_size, snap=snap
        )
        # Avoid landing dead-center inside a wall: nudge to free space
        if self.circle_hits_wall(carcass.pos, carcass.radius * 0.35):
            carcass.pos = self.resolve_circle(
                carcass.pos, max(2.0, carcass.radius * 0.35)
            )
            if self.wrap:
                carcass.pos = self.wrap_position(carcass.pos)
        self.foods.append(carcass)
        self._paint_food_roles()
        return carcass

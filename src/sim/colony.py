"""Colony container: workers, food store, foraging stats."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agents.ant import AntState, WorkerAnt
from src.sim.world import World
from src.util.rng import Rng
from src.util.vec import Vec2


class Colony:
    def __init__(self, world: World, cfg: Dict[str, Any], rng: Rng) -> None:
        self.world = world
        self.cfg = cfg
        self.rng = rng
        self.ants: List[WorkerAnt] = []
        self.food_store: float = 0.0
        self.forage_deliveries: int = 0
        # C2: queen egg production timer
        self._queen_timer: float = 0.0
        # D1: reused spatial hash (avoids per-frame allocation)
        self._spatial: Optional[object] = None
        self._spawn_workers(int(cfg["ants"]["count"]))

    def _next_ant_id(self) -> int:
        if not self.ants:
            return 0
        return max(a.ant_id for a in self.ants) + 1

    def _spawn_workers(self, count: int) -> None:
        for i in range(count):
            outbound = i < max(3, count // 3)
            self.spawn_ant(start_outbound=outbound)

    def spawn_ant(self, start_outbound: bool = True) -> WorkerAnt:
        """Add one worker at the home nest (UI / debug spawn)."""
        spawn = self.world.home_spawn
        acfg = self.cfg["ants"]
        loco = self.cfg.get("locomotion", {})
        forage = self.cfg.get("forage", {})
        ph = self.cfg.get("pheromone", {})
        strength = float(acfg.get("strength", 1.0))
        jitter = (
            self.rng.uniform(-20.0, 20.0),
            self.rng.uniform(-15.0, 15.0),
        )
        pos = spawn.copy()
        pos.x += jitter[0]
        pos.y += jitter[1]
        pos = self.world.resolve_circle(pos, float(acfg["radius"]))
        side = 1.0 if self.rng.random() < 0.5 else -1.0
        ant = WorkerAnt(
            ant_id=self._next_ant_id(),
            pos=pos,
            heading=self.rng.angle(),
            cfg=acfg,
            loco_cfg=loco,
            forage_cfg=forage,
            pheromone_cfg=ph,
            colony_id=0,
            meander_phase=self.rng.uniform(0.0, 6.283185307179586),
            preferred_wall_side=side,
            strength=strength,
        )
        if start_outbound:
            ant.state = AntState.FORAGE_OUTBOUND
            ant.trip_distance = 0.0
        else:
            ant.state = AntState.IDLE_IN_NEST

        # Age-biased response thresholds (Bonabeau model).
        # Every new ant is "young" — high forage threshold (reluctant forager /
        # quasi-nurse); threshold drifts down over mature_forage_time seconds.
        fcfg = self.cfg.get("forage", {})
        young_max = float(fcfg.get("young_forage_theta_max", 0.85))
        young_min = float(fcfg.get("young_forage_theta_min", 0.55))
        ant.thresholds = {
            "forage": self.rng.uniform(young_min, young_max),
            "explore": self.rng.uniform(0.15, 0.40),
            "brood_care": self.rng.uniform(0.05, 0.30),  # stub for future brood
        }

        # C2: randomised lifespan around configured mean
        acfg = self.cfg["ants"]
        mean_life = float(acfg.get("mean_lifespan", 0.0))  # 0 = immortal
        if mean_life > 0:
            spread = float(acfg.get("lifespan_spread", 0.25))
            ant.max_age = max(10.0, self.rng.uniform(
                mean_life * (1.0 - spread), mean_life * (1.0 + spread)
            ))

        self.ants.append(ant)
        return ant

    def spawn_ants(self, count: int = 5, start_outbound: bool = True) -> int:
        """Spawn ``count`` workers at home. Returns how many were added."""
        n = max(0, int(count))
        for _ in range(n):
            self.spawn_ant(start_outbound=start_outbound)
        return n

    def step(self, dt: float) -> None:
        # C2: age-based death — remove ants that have exceeded their lifespan
        dead = [
            a for a in self.ants if a.max_age > 0 and a.age >= a.max_age
        ]
        for a in dead:
            if a.carried_part_id is not None:
                a._release_part(self.world, cooldown=0.0)
            self.ants.remove(a)

        # C2: queen egg production — replace lost workers at a configured rate
        acfg = self.cfg["ants"]
        queen_rate = float(acfg.get("queen_rate", 0.0))  # ants/s; 0 = off
        max_pop = int(acfg.get("max_population", int(acfg.get("count", 35)) * 3))
        if queen_rate > 0 and len(self.ants) < max_pop:
            self._queen_timer += dt
            interval = 1.0 / queen_rate
            while self._queen_timer >= interval and len(self.ants) < max_pop:
                self.spawn_ant(start_outbound=False)
                self._queen_timer -= interval

        positions: List[Vec2] = [a.pos.copy() for a in self.ants]
        # D1: reuse spatial hash (avoid per-frame dict allocation)
        sep_r = float(self.cfg.get("locomotion", {}).get("separation_radius", 12.0))
        cell = max(sep_r, 8.0)
        if self._spatial is None or self._spatial.cell_size != cell:
            from src.util.spatial_hash import SpatialHash2D
            self._spatial = SpatialHash2D(
                positions,
                cell_size=cell,
                world_w=self.world.width,
                world_h=self.world.height,
                wrap=self.world.wrap,
            )
        else:
            self._spatial.rebuild(positions)
        spatial = self._spatial
        # 1) Individual plan + free movement (haulers skip free move)
        for i, ant in enumerate(self.ants):
            ant.step(self.world, self, dt, self.rng, positions, i, spatial=spatial)
        # 2) Rigid multi-ant haul: sum of pulls moves part + locked carriers
        self.world.resolve_hauling(self, dt)
        # Trail deposit for haulers after group move
        for ant in self.ants:
            if ant.carried_part_id is None:
                continue
            prev = getattr(ant, "_haul_prev_pos", ant.pos)
            ant._try_deposit_trail(self.world, prev, ant.pos)
        self.world.step_environment(dt, self.rng)

    def count_by_state(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for a in self.ants:
            name = a.state.name
            counts[name] = counts.get(name, 0) + 1
        return counts

"""Shared worker ant — M1: forage + trail recruitment."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence

from src.agents.locomotion import (
    LocoDebug,
    apply_turn,
    compute_steering,
    slide_move,
)
from src.sim.carcass import Carcass, FoodPart, apply_break_work
from src.sim.food import find_food_at, find_part_at, find_part_near, sense_nearest_food
from src.util.rng import Rng
from src.util.vec import Vec2

if TYPE_CHECKING:
    from src.sim.colony import Colony
    from src.sim.world import World


class AntState(Enum):
    IDLE_IN_NEST = auto()
    EXPLORE = auto()
    FORAGE_OUTBOUND = auto()
    FORAGE_RETURN = auto()
    BROOD_CARE = auto()
    ASSESS_NEST = auto()
    RECRUIT = auto()
    EMIGRATE = auto()
    ALARM = auto()


@dataclass
class WorkerAnt:
    ant_id: int
    pos: Vec2
    heading: float
    cfg: Dict[str, Any]
    loco_cfg: Dict[str, Any]
    forage_cfg: Dict[str, Any]
    pheromone_cfg: Dict[str, Any]
    colony_id: int = 0
    state: AntState = AntState.IDLE_IN_NEST
    age: float = 0.0
    energy: float = 1.0

    carrying_food: float = 0.0  # legacy scalar; prefer gripping FoodPart
    food_quality: float = 0.0
    trip_distance: float = 0.0
    nestmates_at_pickup: int = 0
    steps_since_deposit: float = 0.0
    time_in_state: float = 0.0
    # Snapshot of colony.food_store last seen while inside the home nest.
    nest_food_memory: float = 0.0
    # Base monomorphic strength (1.0); future castes/age can change this
    strength: float = 1.0
    # Gripped loose part (locked to piece; haul physics moves the load)
    carried_part_id: Optional[int] = None
    grip_slot: int = -1  # angular socket on the part (0..max_carriers-1)
    desired_heading: float = 0.0  # individual walk/pull intent
    # Personal frustration when *my* pull does not move the load
    haul_frustration: float = 0.0
    haul_detour_active: bool = False
    haul_detour_side: float = 1.0  # +1 = +90°, -1 = -90°
    haul_detour_dist: float = 0.0
    haul_last_detour_side: float = 0.0
    haul_regrip_cooldown: float = 0.0  # brief calm after a detour ends
    # No progress toward nest → release part; cannot re-grip until this hits 0
    grip_cooldown: float = 0.0
    haul_goal_best_dist: float = -1.0  # best distance-to-goal seen this haul
    haul_no_home_progress_time: float = 0.0
    haul_failed_detours: int = 0
    # Trail: only lay when entering a new pheromone cell
    last_trail_cell: Optional[tuple[int, int]] = None
    # Stuck detection → teleport home after timeout
    stuck_time: float = 0.0

    meander_phase: float = 0.0
    preferred_wall_side: float = 1.0
    # Sprite walk-cycle distance accumulator (world units)
    walk_phase: float = 0.0
    last_debug: Optional[LocoDebug] = field(default=None, repr=False)
    thresholds: Dict[str, float] = field(default_factory=dict)
    # Path integration: accumulated displacement from home (dead-reckoning homing vector)
    path_integration: Vec2 = field(default_factory=Vec2)
    # Lifecycle: ant dies when age exceeds max_age (0 = immortal / not set yet)
    max_age: float = 0.0
    # C4: private route memory — remembered direction toward last food find
    food_memory_dir: Vec2 = field(default_factory=Vec2)
    food_memory_strength: float = 0.0
    # Real-foraging extras (U-turns, ARS, encounters, deposit context)
    uturn_cooldown: float = 0.0
    ars_time: float = 0.0
    ars_origin: Vec2 = field(default_factory=Vec2)
    contact_boost_time: float = 0.0
    contact_cooldown: float = 0.0
    was_on_trail: bool = False
    found_as_scout: bool = False
    pickup_pos: Optional[Vec2] = None
    nearby_nestmates: int = 0

    @property
    def radius(self) -> float:
        return float(self.cfg["radius"])

    @property
    def speed(self) -> float:
        return float(self.cfg["speed"])

    @property
    def is_carrying(self) -> bool:
        return self.carried_part_id is not None or self.carrying_food > 1e-6

    def gripped_part(self, world: "World") -> Optional[FoodPart]:
        if self.carried_part_id is None:
            return None
        for p in world.parts:
            if p.uid == self.carried_part_id and not p.delivered:
                return p
        self.carried_part_id = None
        return None

    def carcass_underfoot(self, world: "World") -> Optional[Carcass]:
        """Non-depleted carcass this ant is standing on (for dismantle linger)."""
        if self.carried_part_id is not None:
            return None
        food = find_food_at(self.pos, world.foods, world.wrap_delta)
        if food is None or not isinstance(food, Carcass) or food.depleted:
            return None
        return food

    def _set_state(self, state: AntState) -> None:
        if state != self.state:
            self.state = state
            self.time_in_state = 0.0

    def _should_ignore_trail(self, strength: float, rng: Rng) -> bool:
        """
        If trail strength is at or below
        ``pheromone_ignore_below_fraction * deposit_amount``, ignore with
        probability ``1 - strength/deposit_amount``.

        Example (base deposit 20, fraction 0.5):
          strength 10 → 50% ignore; strength 5 → 75% ignore; strength 15 → never.
        """
        base = float(
            self.pheromone_cfg.get(
                "deposit_amount",
                self.pheromone_cfg.get("reinforce_amount", 8.0),
            )
        )
        if base <= 1e-9 or strength <= 0.0:
            return strength <= 0.0
        below_frac = float(self.cfg.get("pheromone_ignore_below_fraction", 0.5))
        below_frac = max(0.0, min(below_frac, 1.0))
        threshold = base * below_frac
        if strength > threshold:
            return False
        # Inverse proportional to strength relative to deposit base
        ignore_p = 1.0 - (strength / base)
        ignore_p = max(0.0, min(1.0, ignore_p))
        return rng.random() < ignore_p

    def _refresh_nest_food_memory(self, colony: "Colony") -> None:
        """While inside home, the ant knows live store; snapshot freezes when away."""
        self.nest_food_memory = float(colony.food_store)

    def _effective_leave_nest_rate(self) -> float:
        """
        Base leave rate scaled by remembered nest stock, further modulated by
        this ant's individual forage response threshold (Bonabeau/Beshers model).

        High θ (young ant) → reluctant to leave even when hungry.
        Low θ (mature forager) → responds readily to colony need.

        Personal crop/energy (Mailleux): a starved worker stays to feed if the
        nest still has stores; otherwise personal hunger raises leave urge.
        """
        fcfg = self.forage_cfg
        # Too empty to walk a trip, and the nest can feed her → stay
        min_leave = float(fcfg.get("energy_min_leave", 0.22))
        if self.energy < min_leave and self.nest_food_memory > 4.0:
            return 0.0

        base = float(fcfg.get("leave_nest_rate", 0.45))
        ref = max(1e-3, float(fcfg.get("leave_nest_store_ref", 400.0)))
        empty_scale = float(fcfg.get("leave_nest_empty_scale", 1.8))
        full_scale = float(fcfg.get("leave_nest_full_scale", 0.25))
        mem = max(0.0, float(self.nest_food_memory))
        # sat → 0 empty, approaches 1 as store grows past ref
        sat = mem / (mem + ref)
        scale = empty_scale * (1.0 - sat) + full_scale * sat
        base_rate = max(0.0, base * scale)

        # Response-threshold modulation (Hill function, n=2)
        # hunger stimulus: 0 = store full, 1 = store empty
        hunger_stim = 1.0 - sat
        theta = self.thresholds.get("forage", 0.5)
        # P(task) = s² / (s² + θ²);  neutral (s=0.5, θ=0.5) → P=0.5 → mult=1.0
        p = (hunger_stim ** 2) / (hunger_stim ** 2 + theta ** 2 + 1e-12)
        threshold_mult = max(0.1, p / 0.5)  # normalised at neutral

        # Personal satiety: hungrier workers leave more readily (once fed enough)
        hungry = max(0.0, 1.0 - self.energy)
        personal = 1.0 + float(fcfg.get("energy_leave_hungry_boost", 1.35)) * (
            hungry * hungry
        )
        return base_rate * threshold_mult * personal

    def _update_thresholds(self, dt: float) -> None:
        """
        Age-driven threshold drift (Bonabeau response threshold model).

        Young ants start with a high forage threshold (reluctant foragers /
        quasi-nurses). Over ``mature_forage_time`` seconds it decays toward
        ``mature_forage_theta`` so older ants become eager, efficient foragers.
        Same code for every worker — specialisation is emergent.
        """
        fcfg = self.forage_cfg
        mature_theta = float(fcfg.get("mature_forage_theta", 0.20))
        mature_time = max(1.0, float(fcfg.get("mature_forage_time", 120.0)))
        theta = self.thresholds.get("forage", 0.5)
        # Exponential approach: 63 % of distance covered in one mature_time
        decay = 1.0 - math.exp(-dt / mature_time)
        self.thresholds["forage"] = theta + (mature_theta - theta) * decay
        # C4: food memory fades slowly (forager "forgets" old routes)
        if self.food_memory_strength > 0.0:
            mem_decay = float(self.forage_cfg.get("food_memory_decay_rate", 0.003))
            self.food_memory_strength = max(
                0.0, self.food_memory_strength - mem_decay * dt
            )

    def _current_search_range(self) -> float:
        """
        Scout radius grows with time spent outbound without food.

        Starts at min_search_range; reaches max_search_range after
        search_range_grow_time seconds of fruitless FORAGE_OUTBOUND.
        """
        fcfg = self.forage_cfg
        r_min = float(fcfg.get("min_search_range", 120.0))
        r_max = float(fcfg.get("max_search_range", 850.0))
        if r_max < r_min:
            r_min, r_max = r_max, r_min
        grow_t = max(1e-3, float(fcfg.get("search_range_grow_time", 45.0)))
        if self.state == AntState.FORAGE_OUTBOUND and not self.is_carrying:
            t = max(0.0, float(self.time_in_state))
            frac = min(1.0, t / grow_t)
            # Ease-in: slow expansion early, then open up
            frac = frac * frac * (3.0 - 2.0 * frac)  # smoothstep
            return r_min + (r_max - r_min) * frac
        if self.state == AntState.EXPLORE and not self.is_carrying:
            # Explorers may roam out to the full cap (no timed expand)
            return r_max
        # Idle / returning: soft near-home bound
        return r_min

    def _tick_behaviour_timers(self, dt: float) -> None:
        if self.uturn_cooldown > 0.0:
            self.uturn_cooldown = max(0.0, self.uturn_cooldown - dt)
        if self.ars_time > 0.0:
            self.ars_time = max(0.0, self.ars_time - dt)
        if self.contact_boost_time > 0.0:
            self.contact_boost_time = max(0.0, self.contact_boost_time - dt)
        if self.contact_cooldown > 0.0:
            self.contact_cooldown = max(0.0, self.contact_cooldown - dt)

    def _update_energy(self, dt: float) -> None:
        """Crop drain. Carrying and outdoor walking cost more than nest rest."""
        fcfg = self.forage_cfg
        if self.is_carrying:
            drain = float(fcfg.get("energy_carry_drain", 0.016))
        elif self.state in (
            AntState.FORAGE_OUTBOUND,
            AntState.EXPLORE,
            AntState.ALARM,
        ):
            drain = float(fcfg.get("energy_forage_drain", 0.010))
        else:
            drain = float(fcfg.get("energy_idle_drain", 0.003))
        self.energy = max(0.0, min(1.0, self.energy - drain * dt))

    def _try_feed_in_nest(self, colony: "Colony", dt: float) -> None:
        """Social-stomach stand-in: idle workers sip the communal store."""
        fcfg = self.forage_cfg
        until = float(fcfg.get("energy_feed_until", 0.92))
        if self.energy >= until:
            return
        store = float(colony.food_store)
        if store <= 0.05:
            return
        rate = float(fcfg.get("energy_feed_rate", 0.34))
        cost = max(1e-6, float(fcfg.get("energy_food_cost", 2.4)))
        de = min(rate * dt, until - self.energy)
        food = de * cost
        if food > store:
            de = store / cost
            food = store
        colony.food_store = max(0.0, store - food)
        self.energy = min(1.0, self.energy + de)

    def _start_ars(self, pos: Vec2) -> None:
        """Area-restricted search: loop locally after losing a cue."""
        self.ars_time = float(self.forage_cfg.get("ars_duration", 6.5))
        self.ars_origin = pos.copy()

    def _nestmates_on_target(
        self,
        colony: "Colony",
        world: "World",
        target: Any,
        extra_radius: float = 0.0,
    ) -> int:
        """Count other workers standing on / next to a carcass or part."""
        reach = float(getattr(target, "radius", 8.0)) + extra_radius
        n = 0
        for a in colony.ants:
            if a.ant_id == self.ant_id:
                continue
            if world.wrap_delta(a.pos, target.pos).length() <= reach:
                n += 1
        return n

    def _count_nearby_nestmates(
        self,
        others: Sequence[Vec2],
        self_index: int,
        world: "World",
        radius: float,
    ) -> int:
        if radius <= 0.0:
            return 0
        r2 = radius * radius
        n = 0
        for i, o in enumerate(others):
            if i == self_index:
                continue
            if world.wrap_delta(self.pos, o).length_sq() <= r2:
                n += 1
        return n

    def _try_antennation(
        self,
        colony: "Colony",
        world: "World",
        rng: Rng,
        dt: float,
    ) -> None:
        """
        Contact with a returning loaded nestmate recruits this explorer
        onto the outbound path (turn the way the forager came from).
        """
        if self.contact_cooldown > 0.0 or self.is_carrying:
            return
        if self.state not in (AntState.FORAGE_OUTBOUND, AntState.EXPLORE):
            return
        fcfg = self.forage_cfg
        radius = float(fcfg.get("antennation_radius", 11.0))
        if radius <= 0.0:
            return
        r2 = radius * radius
        rate = float(fcfg.get("antennation_rate", 1.6))
        for other in colony.ants:
            if other.ant_id == self.ant_id or not other.is_carrying:
                continue
            if world.wrap_delta(self.pos, other.pos).length_sq() > r2:
                continue
            # Overlapping a loaded nestmate: Poisson chance to turn around
            p = 1.0 - math.exp(-max(0.0, rate) * dt)
            if rng.random() < p:
                self.heading = other.heading + math.pi
                self.desired_heading = self.heading
                self._set_state(AntState.FORAGE_OUTBOUND)
                self.contact_boost_time = float(fcfg.get("contact_boost_time", 3.2))
                self.contact_cooldown = 2.0
            else:
                self.contact_cooldown = 0.12
            return

    def _maybe_trail_uturn(
        self,
        world: "World",
        rng: Rng,
        dt: float,
        trail_str: float,
        trail_min: float,
        sense_dist: float,
    ) -> bool:
        """
        Beckers U-turn: reverse when the trail fades ahead or is lost.
        Only outbound / explore — returning ants must keep heading home.
        """
        fcfg = self.forage_cfg
        if not bool(fcfg.get("uturn_enabled", True)):
            return False
        if self.uturn_cooldown > 0.0 or self.is_carrying:
            return False
        if self.state not in (AntState.FORAGE_OUTBOUND, AntState.EXPLORE):
            return False
        if self.carcass_underfoot(world) is not None:
            return False

        ahead = world.pheromones.sample(
            self.pos + Vec2.from_angle(self.heading) * sense_dist,
            "trail",
        )
        here = world.pheromones.sample(self.pos, "trail")
        ratio = float(fcfg.get("uturn_ahead_ratio", 0.50))
        lost = self.was_on_trail and trail_str < trail_min
        fading = here > trail_min and ahead < here * ratio
        if not (lost or fading):
            return False

        fade = 1.0 if here < 1e-6 else max(0.0, 1.0 - ahead / max(here, 1e-6))
        rate = float(fcfg.get("uturn_lost_rate", 1.1)) if lost else (
            float(fcfg.get("uturn_rate", 0.50)) * (0.35 + 0.65 * fade)
        )
        if rng.random() >= 1.0 - math.exp(-max(0.0, rate) * dt):
            return False

        self.heading += math.pi
        self.desired_heading = self.heading
        self.uturn_cooldown = float(fcfg.get("uturn_cooldown", 1.8))
        if lost:
            self._start_ars(self.pos)
        return True

    def _apply_ars_steer(
        self,
        world: "World",
        v_food: Vec2,
        w_food: float,
        meander_scale: float,
    ) -> tuple:
        """Keep looping near the last lost cue until ARS expires."""
        if self.ars_time <= 0.0 or self.is_carrying:
            return v_food, w_food, meander_scale
        fcfg = self.forage_cfg
        meander_scale = max(
            meander_scale, float(fcfg.get("ars_meander", 1.80))
        )
        radius = float(fcfg.get("ars_radius", 52.0))
        to_o = world.wrap_delta(self.pos, self.ars_origin)
        dist = to_o.length()
        if dist > radius * 0.55 and w_food <= 0.15 and to_o.length_sq() > 1e-8:
            v_food = to_o
            w_food = 1.15
        return v_food, w_food, meander_scale

    def _compute_deposit_amount(
        self,
        world: "World",
        cell_r: int,
        cell_c: int,
    ) -> float:
        """
        Enter-once drop size, modulated like *L. niger* trail laying.

        Quality, trip distance, near-food vs near-nest, already-strong trail
        suppression, crowding at the feeder, scout vs recruit, and on-trail
        encounters. Never multiplies by existing trail (no volcano).
        """
        pcfg = self.pheromone_cfg
        fcfg = self.forage_cfg
        amount = float(pcfg.get("deposit_amount", pcfg.get("reinforce_amount", 10.0)))
        if amount <= 0.0:
            return 0.0

        q_scale = float(fcfg.get("food_quality_deposit_scale", 1.0))
        amount *= max(0.1, self.food_quality * q_scale)

        dist_scale = float(fcfg.get("deposit_distance_scale", 0.0012))
        amount *= 1.0 + dist_scale * max(0.0, self.trip_distance)

        near_food = float(fcfg.get("deposit_near_food", 2.6))
        near_nest = float(fcfg.get("deposit_near_nest", 0.40))
        if self.pickup_pos is not None:
            d_food = world.wrap_delta(self.pos, self.pickup_pos).length()
            d_home = world.wrap_delta(self.pos, world.home_tile).length()
            total = d_food + d_home
            # t = 0 at prey, 1 at nest; square so most of the boost is near food
            t = 0.0 if total < 1e-6 else d_food / total
            t = t * t
            amount *= near_food * (1.0 - t) + near_nest * t
        else:
            amount *= 0.5 * (near_food + near_nest)

        suppress = float(fcfg.get("deposit_trail_suppress", 0.028))
        if suppress > 0.0:
            local = float(world.pheromones.trail[cell_r, cell_c])
            amount *= 1.0 / (1.0 + suppress * local)

        crowd_n = int(fcfg.get("crowd_threshold", 4))
        if self.nestmates_at_pickup > crowd_n:
            amount *= float(fcfg.get("crowd_deposit_penalty", 0.48))

        if self.found_as_scout:
            amount *= float(fcfg.get("scout_deposit_boost", 1.30))

        enc_r = float(fcfg.get("trail_encounter_radius", 12.0))
        if enc_r > 0.0 and self.nearby_nestmates > 0:
            amount *= float(fcfg.get("trail_encounter_deposit", 0.72))

        return max(0.0, amount)

    def _mill_in_nest(
        self,
        world: "World",
        rng: Rng,
        others: Sequence[Vec2],
        self_index: int,
        spatial,
        dt: float,
    ) -> None:
        """Slow thigmotactic mill — nest workers do not stand frozen."""
        speed_scale = float(self.forage_cfg.get("nest_mill_speed", 0.22))
        if speed_scale <= 0.0:
            return
        desired, meander_len, debug = compute_steering(
            pos=self.pos,
            heading=self.heading,
            meander_phase=self.meander_phase,
            preferred_wall_side=self.preferred_wall_side,
            walls=world.walls,
            others=others,
            self_index=self_index,
            inside_nest=True,
            loco=self.loco_cfg,
            rng=rng,
            wrap_delta_fn=world.wrap_delta,
            meander_scale=0.7,
            tile_grid=world.pheromones,
            spatial=spatial,
        )
        self.last_debug = debug
        max_turn = float(self.loco_cfg.get("max_turn_rate", 3.5)) * 0.7
        self.heading = apply_turn(self.heading, desired, max_turn, dt)
        if meander_len > 1e-6:
            self.meander_phase += (2.0 * math.pi) * (
                (self.speed * speed_scale * dt) / (meander_len * 2.0)
            )
        old = self.pos.copy()
        new_pos, new_heading = slide_move(
            pos=self.pos,
            heading=self.heading,
            speed=self.speed * speed_scale,
            radius=self.radius,
            dt=dt,
            walls=world.walls,
            resolve_fn=world.resolve_circle,
            hits_fn=world.circle_hits_wall,
            tile_grid=world.pheromones,
        )
        self.heading = new_heading
        moved = world.wrap_delta(old, new_pos).length()
        self.pos = new_pos
        if moved > 0.15:
            self.walk_phase += moved

    def step(
        self,
        world: "World",
        colony: "Colony",
        dt: float,
        rng: Rng,
        others: Sequence[Vec2],
        self_index: int,
        spatial=None,
    ) -> None:
        self.age += dt
        self.time_in_state += dt
        self.steps_since_deposit += dt
        if self.grip_cooldown > 0.0:
            self.grip_cooldown = max(0.0, self.grip_cooldown - dt)
        self._tick_behaviour_timers(dt)
        self._update_energy(dt)
        self._update_thresholds(dt)

        inside_home = world.is_inside_home(self.pos)
        inside_any = world.is_inside_nest(self.pos)

        # Live nest stock only while physically in the home nest
        if inside_home:
            self._refresh_nest_food_memory(colony)

        self._update_state(world, colony, rng, inside_home, dt)
        self.nearby_nestmates = self._count_nearby_nestmates(
            others,
            self_index,
            world,
            float(self.forage_cfg.get("trail_encounter_radius", 12.0)),
        )
        self._try_antennation(colony, world, rng, dt)

        # In-nest: mill slowly and feed — real workers do not freeze
        if (
            self.state == AntState.IDLE_IN_NEST
            and inside_home
            and self.carried_part_id is None
        ):
            self.stuck_time = 0.0
            self._try_feed_in_nest(colony, dt)
            self._mill_in_nest(world, rng, others, self_index, spatial, dt)
            return

        v_trail = Vec2(0.0, 0.0)
        w_trail = 0.0
        v_home = Vec2(0.0, 0.0)
        w_home = 0.0
        v_food = Vec2(0.0, 0.0)
        w_food = 0.0
        meander_scale = 1.0

        trail_sample = world.pheromones.sample(self.pos, "trail")
        nest_grad = world.pheromones.gradient(self.pos, "nest")
        alarm_grad = world.pheromones.gradient(self.pos, "alarm")  # C1

        fcfg = self.forage_cfg
        trail_follow = float(fcfg.get("trail_follow_weight", 1.8))
        nest_follow = float(fcfg.get("nest_follow_weight", 1.6))
        entrance_w = float(fcfg.get("entrance_seek_weight", 1.2))
        trail_min = float(fcfg.get("trail_follow_min", 0.15))
        sense_dist = float(fcfg.get("trail_sense_distance", 30.0))
        sense_ang = float(fcfg.get("trail_sense_angle", 0.55))
        food_sense_dist = float(fcfg.get("food_sense_distance", 48.0))
        food_sense_ang = float(fcfg.get("food_sense_angle", 0.95))
        food_seek = float(fcfg.get("food_seek_weight", 2.6))

        dist_home = world.wrap_delta(self.pos, world.home_entrance).length()
        max_search = self._current_search_range()

        # Antenna-style trail steering (avoids orbiting pheromone peaks)
        trail_steer, trail_str = world.pheromones.trail_follow_steering(
            self.pos,
            self.heading,
            sense_distance=sense_dist,
            sense_angle=sense_ang,
            layer="trail",
        )
        # Weak trails: inverse-proportional chance to ignore (see ants.pheromone_ignore_*)
        if self._should_ignore_trail(trail_str, rng):
            trail_steer = Vec2(0.0, 0.0)
            trail_str = 0.0
            trail_sample = 0.0

        self._maybe_trail_uturn(
            world, rng, dt, trail_str, trail_min, sense_dist
        )

        # On a carcass: stay put and dismantle (don't wander off mid-work)
        butchering = self.carcass_underfoot(world)
        linger_speed = 1.0

        # Antenna prey sense: prefer loose/abandoned parts, else carcasses
        food_hit = None
        if self.state in (AntState.FORAGE_OUTBOUND, AntState.EXPLORE) and not self.is_carrying:
            targets: list = [p for p in world.parts if not p.delivered]
            targets.extend(c for c in world.foods if not c.depleted)
            food_hit = sense_nearest_food(
                self.pos,
                self.heading,
                targets,
                max_distance=food_sense_dist,
                max_angle=food_sense_ang,
                wrap_delta_fn=world.wrap_delta,
                prefer_loose_parts=True,
            )
            if food_hit is not None:
                food_dir, food_surf, food_tgt = food_hit
                if food_dir.length_sq() > 1e-12:
                    prox = 1.0 - min(1.0, food_surf / max(food_sense_dist, 1e-6))
                    v_food = food_dir
                    w_food = food_seek * (0.45 + 0.55 * prox)
                    # Abandoned (0 carriers) or under-crewed parts: pull harder
                    if hasattr(food_tgt, "carrier_ids"):
                        n_c = len(food_tgt.carrier_ids)
                        if n_c == 0:
                            w_food *= float(fcfg.get("abandoned_part_seek_boost", 1.45))
                        elif n_c < int(fcfg.get("max_carriers_per_part", 4)):
                            w_food *= 1.15
                    # Packed feeder: down-weight so others keep searching (Wendt)
                    n_crowd = self._nestmates_on_target(colony, world, food_tgt)
                    if n_crowd >= int(fcfg.get("crowd_avoid_count", 6)):
                        w_food *= float(fcfg.get("crowd_seek_scale", 0.28))
                    meander_scale = min(
                        meander_scale, float(fcfg.get("food_meander_scale", 0.2))
                    )

        if butchering is not None and not self.is_carrying:
            n_here = self._nestmates_on_target(colony, world, butchering)
            if (
                n_here >= int(fcfg.get("crowd_butcher_max", 8))
                and rng.random()
                < float(fcfg.get("crowd_leave_rate", 0.40)) * dt
            ):
                # Too many nestmates on this prey — peel off and search locally
                self._start_ars(self.pos)
                away = world.wrap_delta(butchering.pos, self.pos)
                if away.length_sq() < 1e-8:
                    away = Vec2.from_angle(self.heading)
                self.heading = away.angle()
                butchering = None
            else:
                # Linger: pull toward carcass center, ignore trail/home, crawl slowly
                to_c = world.wrap_delta(self.pos, butchering.pos)
                if to_c.length_sq() > 1e-8:
                    v_food = to_c
                else:
                    v_food = Vec2.from_angle(self.heading)
                w_food = float(fcfg.get("butcher_linger_weight", 4.0))
                w_trail = 0.0
                w_home = 0.0
                meander_scale = float(fcfg.get("butcher_meander_scale", 0.08))
                linger_speed = float(fcfg.get("butcher_linger_speed", 0.22))
                # Commit to outbound while working the carcass
                if self.state == AntState.EXPLORE:
                    self._set_state(AntState.FORAGE_OUTBOUND)

        if self.state == AntState.FORAGE_OUTBOUND and butchering is None:
            # Commit to a U-turn for the first half of the cooldown so
            # trail-following does not immediately yank the ant back.
            uturn_cd = float(fcfg.get("uturn_cooldown", 1.8))
            committing_uturn = (
                self.uturn_cooldown > uturn_cd * 0.5 and uturn_cd > 0.0
            )
            if trail_str >= trail_min and trail_steer.length_sq() > 1e-8 and not committing_uturn:
                v_trail = trail_steer
                # Cap weight so persistence still breaks residual circling
                w_trail = trail_follow * min(
                    1.8, 0.35 + 0.4 * math.sqrt(max(trail_str, 0.0))
                )
                if self.contact_boost_time > 0.0:
                    w_trail *= float(fcfg.get("contact_trail_boost", 1.40))
                # Food in antenna range outranks trail (they found the source)
                if w_food > 0.0:
                    w_trail *= float(fcfg.get("food_vs_trail_scale", 0.35))
                meander_scale = min(
                    meander_scale, float(fcfg.get("outbound_meander_scale", 0.35))
                )
            else:
                if w_food <= 0.0:
                    meander_scale = float(fcfg.get("search_meander_scale", 1.25))
                    # C4: private route memory — bias toward last known food direction
                    if self.food_memory_strength > 0.1:
                        mem_w = (
                            float(fcfg.get("food_memory_weight", 0.8))
                            * self.food_memory_strength
                        )
                        if self.food_memory_dir.length_sq() > 1e-8:
                            v_food = self.food_memory_dir
                            w_food = mem_w
                # Central-place foraging: don't vanish into the infinite outworld
                if dist_home > max_search:
                    to_ent = world.wrap_delta(self.pos, world.home_entrance)
                    if to_ent.length_sq() > 1e-6:
                        v_home = to_ent
                        w_home = float(fcfg.get("lost_home_weight", 1.8))
                        meander_scale = 0.5
                elif dist_home > max_search * 0.55:
                    to_ent = world.wrap_delta(self.pos, world.home_entrance)
                    if to_ent.length_sq() > 1e-6:
                        v_home = to_ent
                        w_home = float(fcfg.get("edge_home_weight", 0.55))
            if inside_home:
                to_ent = world.wrap_delta(self.pos, world.home_entrance)
                if to_ent.length_sq() > 1e-6:
                    v_home = to_ent
                    w_home = float(fcfg.get("leave_nest_weight", 1.0))

        elif self.state == AntState.FORAGE_RETURN:
            # Must reach the single home_tile to unload (no deliver-through-wall).
            meander_scale = float(fcfg.get("return_meander_scale", 0.15))
            # Pick main vs cargo mouth: heavy always cargo; light uses clearer approach
            # so every hauler from the same outdoor side does not pin on one exterior corner.
            part = self.gripped_part(world) if self.carried_part_id is not None else None
            heavy_thresh = float(fcfg.get("cargo_path_min_weight", 2.0))
            approach = self._pick_haul_entrance(world, part, heavy_thresh)
            to_ent = world.wrap_delta(self.pos, approach)
            to_home = world.wrap_delta(self.pos, world.home_tile)
            arrive_r = float(fcfg.get("entrance_arrive_radius", 22.0))
            at_mouth = to_ent.length() <= arrive_r
            if not inside_home and not at_mouth:
                # Outside: aim the chosen mouth first. Nest scent only blends
                # when it agrees with the approach — otherwise it yanks haulers
                # into the same exterior corner of the nest shell every time.
                if to_ent.length_sq() > 1e-6:
                    v_home = to_ent.normalized()
                    w_home = entrance_w * 1.35
                if nest_grad.length_sq() > 1e-8 and to_ent.length_sq() > 1e-6:
                    ng = nest_grad.normalized()
                    ent_u = to_ent.normalized()
                    if ng.dot(ent_u) > 0.25:
                        v_home = (v_home + ng * 0.35).normalized()
                        w_home = max(w_home, nest_follow * 0.6)
                if (
                    trail_str > trail_min * 0.5
                    and trail_steer.length_sq() > 1e-8
                    and to_ent.length_sq() > 1e-6
                ):
                    home_dir = to_ent.normalized()
                    if trail_steer.normalized().dot(home_dir) > 0.15:
                        v_trail = trail_steer
                        w_trail = float(fcfg.get("return_trail_weight", 0.25))
                # Path integration: dead-reckoning fallback when nest scent is faint.
                # -path_integration points back toward where the ant started (home).
                pi_len = self.path_integration.length()
                if pi_len > 1.0:
                    pi_dir = (-self.path_integration).normalized()
                    pi_nest_max = float(fcfg.get("pi_nest_scent_max", 3.0))
                    pi_w = float(fcfg.get("pi_weight", 1.2))
                    # Weaken as local nest gradient grows (gradient more reliable up close)
                    nest_scent_strength = nest_grad.length()
                    pi_blend = max(0.0, 1.0 - nest_scent_strength / max(pi_nest_max, 1e-6))
                    # Also taper as PI magnitude shrinks (ant is almost home)
                    pi_blend *= min(1.0, pi_len / 60.0)
                    if pi_blend > 0.05:
                        if v_home.length_sq() < 1e-8:
                            v_home = pi_dir
                            w_home = pi_w * pi_blend
                        else:
                            v_home = (v_home + pi_dir * pi_blend * 0.6).normalized()
                            w_home = max(w_home, pi_w * pi_blend * 0.7)
            else:
                # At mouth or inside nest: commit to home tile (next waypoint).
                # Without this, haulers sit on the outdoor entrance marker forever.
                if to_home.length_sq() > 1e-6:
                    v_home = to_home.normalized()
                    w_home = entrance_w * 1.5
                if nest_grad.length_sq() > 1e-8:
                    ng = nest_grad.normalized()
                    if v_home.length_sq() > 1e-8 and ng.dot(v_home) > 0.0:
                        v_home = (v_home + ng * 0.35).normalized()
                    elif v_home.length_sq() < 1e-8:
                        v_home = ng
                    w_home = max(w_home, nest_follow * 0.75)

        elif self.state == AntState.EXPLORE:
            if trail_str >= trail_min and trail_steer.length_sq() > 1e-8:
                v_trail = trail_steer
                w_trail = trail_follow * 0.75
                if w_food > 0.0:
                    w_trail *= float(fcfg.get("food_vs_trail_scale", 0.35))
                meander_scale = min(meander_scale, 0.45)
            elif w_food <= 0.0 and dist_home > max_search * 0.4:
                to_ent = world.wrap_delta(self.pos, world.home_entrance)
                if nest_grad.length_sq() > 1e-8:
                    v_home = nest_grad.normalized() * 0.5 + (
                        to_ent.normalized() if to_ent.length_sq() > 1e-6 else Vec2()
                    )
                    w_home = nest_follow * 0.85
                elif to_ent.length_sq() > 1e-6:
                    v_home = to_ent
                    w_home = entrance_w

        elif self.state == AntState.ALARM:
            # Move toward alarm gradient (rush to scene); deposit own alarm (C1)
            alarm_w = float(fcfg.get("alarm_follow_weight", 2.2))
            if alarm_grad.length_sq() > 1e-8:
                v_food = alarm_grad.normalized()
                w_food = alarm_w
                meander_scale = 0.2
            # Re-deposit alarm to relay the signal
            world.pheromones.deposit(
                self.pos,
                float(fcfg.get("alarm_relay_amount", 8.0)) * dt,
                layer="alarm",
            )
            # Auto-expire ALARM if no alarm sensed nearby
            alarm_here = world.pheromones.sample(self.pos, "alarm")
            if alarm_here < float(fcfg.get("alarm_sense_min", 0.5)):
                self.time_in_state = float(fcfg.get("alarm_expire_time", 5.0))  # trigger expire

        if self.state in (AntState.FORAGE_OUTBOUND, AntState.EXPLORE):
            on_trail = trail_str >= trail_min
            if self.was_on_trail and not on_trail and not self.is_carrying:
                self._start_ars(self.pos)
            self.was_on_trail = on_trail
            v_food, w_food, meander_scale = self._apply_ars_steer(
                world, v_food, w_food, meander_scale
            )
        else:
            self.was_on_trail = False

        desired, meander_len, debug = compute_steering(
            pos=self.pos,
            heading=self.heading,
            meander_phase=self.meander_phase,
            preferred_wall_side=self.preferred_wall_side,
            walls=world.walls,
            others=others,
            self_index=self_index,
            inside_nest=inside_any,
            loco=self.loco_cfg,
            rng=rng,
            wrap_delta_fn=world.wrap_delta,
            v_trail=v_trail,
            w_trail=w_trail,
            v_home=v_home,
            w_home=w_home,
            v_food=v_food,
            w_food=w_food,
            meander_scale=meander_scale,
            tile_grid=world.pheromones,
            spatial=spatial,
        )
        self.last_debug = debug

        max_turn = float(self.loco_cfg.get("max_turn_rate", 3.5))
        if debug.wall_hit is not None and debug.weights.get("wall", 0) > 0:
            max_turn *= 1.25
        if w_trail > 0.5 or w_home > 0.5 or w_food > 0.5:
            max_turn *= 1.2
        if w_food > 1.0:
            # Snap toward prey when antennae lock on
            max_turn *= 1.15

        # Individual pathfinding intent → force on the load (if gripping)
        self.desired_heading = desired
        if self.carried_part_id is not None:
            near_drop = (
                world.wrap_delta(self.pos, world.home_tile).length()
                < float(fcfg.get("unload_radius", 14.0)) * 3.0
            )
            if near_drop:
                self.haul_detour_active = False
                self.haul_frustration = 0.0
                self.haul_no_home_progress_time = 0.0
            else:
                self._apply_haul_frustration_detour(world, rng, dt)
            desired = self.desired_heading
            if self.haul_detour_active:
                max_turn *= 2.0
        self.heading = apply_turn(self.heading, desired, max_turn, dt)

        if meander_len > 1e-6:
            self.meander_phase += (2.0 * math.pi) * (
                (self.speed * dt) / (meander_len * 2.0)
            )

        old_pos = self.pos.copy()
        hauling = self.carried_part_id is not None

        if hauling:
            # Locked to gripped piece — colony.resolve_hauling moves the group
            moved = 0.0
            new_pos = self.pos.copy()
        else:
            move_speed = self.speed * max(0.05, min(1.0, linger_speed))
            new_pos, new_heading = slide_move(
                pos=self.pos,
                heading=self.heading,
                speed=move_speed,
                radius=self.radius,
                dt=dt,
                walls=world.walls,
                resolve_fn=world.resolve_circle,
                hits_fn=world.circle_hits_wall,
                tile_grid=world.pheromones,
            )
            self.heading = new_heading
            moved = world.wrap_delta(old_pos, new_pos).length()
            self.pos = new_pos
            # Soft clamp: if still on carcass, don't leave its footprint while working
            if butchering is not None and not butchering.contains(
                self.pos, world.wrap_delta
            ):
                # Step back toward center so dismantle work continues
                back = world.wrap_delta(self.pos, butchering.pos)
                if back.length_sq() > 1e-8:
                    pull = min(butchering.radius * 0.35, back.length())
                    self.pos = self.pos + back.normalized() * pull
                    self.pos = world.resolve_circle(self.pos, self.radius)
                    if world.wrap:
                        self.pos = world.wrap_position(self.pos)

        if self.state in (AntState.FORAGE_OUTBOUND, AntState.FORAGE_RETURN):
            self.trip_distance += moved
        if moved > 0.15:
            self.walk_phase += moved

        # Stuck: free ants only; don't rescue while dismantling a carcass
        if not hauling and butchering is None:
            self._update_stuck(world, colony, dt, moved)
        elif butchering is not None:
            self.stuck_time = 0.0

        # Trail while hauling (after group move, colony may shift pos — deposit later too)
        if self.is_carrying and not hauling:
            self._try_deposit_trail(world, old_pos, self.pos)

        # Path integration: accumulate displacement from home; reset when home.
        # -self.path_integration is the dead-reckoning homing vector.
        # Small angular drift — real PI is noisy; nest scent wins near home.
        if world.is_inside_home(self.pos):
            self.path_integration = Vec2()
        elif not hauling:
            delta = world.wrap_delta(old_pos, self.pos)
            err = float(fcfg.get("pi_error_sigma", 0.035))
            if err > 0.0 and delta.length_sq() > 1e-8:
                ang = rng.gauss(0.0, err)
                ca, sa = math.cos(ang), math.sin(ang)
                delta = Vec2(delta.x * ca - delta.y * sa, delta.x * sa + delta.y * ca)
            self.path_integration = self.path_integration + delta

        # Free ants may grab loose/abandoned parts (not only while "outbound")
        if not hauling and not self.is_carrying:
            if self.state in (
                AntState.FORAGE_OUTBOUND,
                AntState.EXPLORE,
            ):
                self._try_butcher_or_grip(world, colony, rng, others, dt)

    def _update_state(
        self,
        world: "World",
        colony: "Colony",
        rng: Rng,
        inside_home: bool,
        dt: float,
    ) -> None:
        fcfg = self.forage_cfg

        if self.is_carrying:
            self._set_state(AntState.FORAGE_RETURN)
            return

        if self.state == AntState.FORAGE_RETURN and not self.is_carrying:
            self._set_state(
                AntState.IDLE_IN_NEST if inside_home else AntState.EXPLORE
            )
            return

        trail_here = world.pheromones.sample(self.pos, "trail")
        trail_min = float(fcfg.get("trail_follow_min", 0.15))
        leave_rate = self._effective_leave_nest_rate()
        explore_rate = float(fcfg.get("start_explore_rate", 0.35))

        if inside_home:
            if self.state not in (
                AntState.FORAGE_OUTBOUND,
                AntState.FORAGE_RETURN,
            ):
                self._set_state(AntState.IDLE_IN_NEST)
            trail_ent = world.pheromones.sample(world.home_entrance, "trail")
            boost = 1.0 + min(4.0, trail_ent * 0.6)
            if self.state != AntState.FORAGE_OUTBOUND:
                if rng.random() < leave_rate * boost * dt:
                    # Freeze stock memory at departure (already refreshed this frame)
                    self._refresh_nest_food_memory(colony)
                    self._set_state(AntState.FORAGE_OUTBOUND)
                    self.trip_distance = 0.0
            return

        # Outside
        if self.state == AntState.IDLE_IN_NEST:
            self._set_state(AntState.EXPLORE)

        # C1: Alarm pheromone — sense and respond (non-carrying ants only)
        if not self.is_carrying and self.state not in (
            AntState.FORAGE_RETURN, AntState.ALARM
        ):
            alarm_here = world.pheromones.sample(self.pos, "alarm")
            alarm_thresh = float(fcfg.get("alarm_sense_min", 0.5))
            if alarm_here >= alarm_thresh and rng.random() < 0.35:
                self._set_state(AntState.ALARM)

        # C1: Expire ALARM state after a timeout (or when no alarm nearby)
        if self.state == AntState.ALARM:
            alarm_expire = float(fcfg.get("alarm_expire_time", 5.0))
            if self.time_in_state >= alarm_expire:
                self._set_state(AntState.EXPLORE)
            return

        if self.state == AntState.EXPLORE:
            food_sense_dist = float(fcfg.get("food_sense_distance", 48.0))
            food_sense_ang = float(fcfg.get("food_sense_angle", 0.95))
            # Loose parts first — abandoned hauls must still recruit foragers
            loose = [p for p in world.parts if not p.delivered]
            prey = loose + [c for c in world.foods if not c.depleted]
            if trail_here >= trail_min:
                self._set_state(AntState.FORAGE_OUTBOUND)
            elif sense_nearest_food(
                self.pos,
                self.heading,
                prey,
                max_distance=food_sense_dist,
                max_angle=food_sense_ang,
                wrap_delta_fn=world.wrap_delta,
                prefer_loose_parts=True,
            ) is not None:
                self._set_state(AntState.FORAGE_OUTBOUND)
            elif loose and find_part_near(
                self.pos,
                loose,
                reach=food_sense_dist * 0.85,
                wrap_delta_fn=world.wrap_delta,
                prefer_free_slots=True,
                max_carriers=int(fcfg.get("max_carriers_per_part", 4)),
            ) is not None:
                # Part on the ground nearby (any facing) → go get it
                self._set_state(AntState.FORAGE_OUTBOUND)
            elif rng.random() < explore_rate * dt:
                self._set_state(AntState.FORAGE_OUTBOUND)

        if self.state == AntState.FORAGE_OUTBOUND:
            # Stay on carcass until a part is free / carcass gone — no trip give-up
            if self.carcass_underfoot(world) is not None:
                return
            max_out = float(fcfg.get("max_outbound_time", 90.0))
            dist_h = world.wrap_delta(self.pos, world.home_entrance).length()
            max_search = self._current_search_range()
            starved = self.energy < float(fcfg.get("energy_return_threshold", 0.12))
            if (
                self.time_in_state > max_out
                or dist_h > max_search * 1.15
                or starved
            ):
                # Give up this trip — head home empty (no trail deposit)
                self._set_state(AntState.EXPLORE)
                to_ent = world.wrap_delta(self.pos, world.home_entrance)
                if to_ent.length_sq() > 1e-6:
                    self.heading = to_ent.angle()

    def _try_butcher_or_grip(
        self,
        world: "World",
        colony: "Colony",
        rng: Rng,
        others: Sequence[Vec2],
        dt: float,
    ) -> None:
        """Grip a loose part, or help dismantle a carcass (one piece at a time)."""
        if self.carried_part_id is not None:
            return

        # Prefer loose / abandoned parts (underfoot or within short reach)
        max_c = int(self.forage_cfg.get("max_carriers_per_part", 4))
        reach = float(self.forage_cfg.get("part_grip_reach", 10.0))
        part = find_part_at(self.pos, world.parts, world.wrap_delta)
        if part is None:
            part = find_part_near(
                self.pos,
                world.parts,
                reach=reach + self.radius,
                wrap_delta_fn=world.wrap_delta,
                prefer_free_slots=True,
                max_carriers=max_c,
            )
        if part is not None and not part.delivered:
            if self.grip_cooldown > 0.0:
                return  # just released a haul — don't re-grab for a while
            # Scrub ghosts so abandoned piles aren't "full"
            part.carrier_ids = {
                a.ant_id
                for a in colony.ants
                if a.carried_part_id == part.uid
            }
            if len(part.carrier_ids) < max_c or self.ant_id in part.carrier_ids:
                occ = {
                    int(a.grip_slot): a.ant_id
                    for a in colony.ants
                    if a.carried_part_id == part.uid and a.grip_slot >= 0
                }
                self.nestmates_at_pickup = self._nestmates_on_target(
                    colony, world, part
                )
                self.found_as_scout = not self.was_on_trail
                self._grip_part(world, part, others_slots=occ)
                if self.carried_part_id is not None:
                    self._set_state(AntState.FORAGE_RETURN)
            return

        carcass = find_food_at(self.pos, world.foods, world.wrap_delta)
        if carcass is None or not isinstance(carcass, Carcass):
            return
        if carcass.depleted:
            return

        # Collect strengths of free ants currently on this carcass
        strengths: list[float] = []
        for a in colony.ants:
            if a.carried_part_id is not None:
                continue
            if carcass.contains(a.pos, world.wrap_delta):
                strengths.append(a.strength)

        fcfg = self.forage_cfg
        # Only the "lead" worker on this carcass applies work once per frame
        # (lowest ant_id on the carcass) so multi-ant doesn't multi-apply.
        on_here = [
            a
            for a in colony.ants
            if a.carried_part_id is None
            and carcass.contains(a.pos, world.wrap_delta)
        ]
        if not on_here:
            return
        leader = min(on_here, key=lambda a: a.ant_id)
        if leader.ant_id != self.ant_id:
            return

        new_part = apply_break_work(
            carcass,
            strengths,
            dt,
            break_work=float(fcfg.get("break_work", 6.0)),
            break_rate_solo=float(fcfg.get("break_rate_solo", 1.0)),
            rng=rng,
        )
        if new_part is not None:
            world.parts.append(new_part)
            world._food_dirty = True  # D2: mark dirty; world.resolve_hauling will repaint
            world._paint_food_roles()

    def _pick_haul_entrance(
        self,
        world: "World",
        part: Optional[FoodPart],
        heavy_thresh: float,
    ) -> Vec2:
        """
        Choose main vs cargo mouth.

        Heavy pieces always use the wide cargo path. Light pieces score both
        entrances by distance + wall blockage so they do not all aim at the
        same mouth and pin on the same exterior corner.
        """
        from src.sim.wall_sense import wall_ahead_grid

        main = world.home_entrance
        if not getattr(world.home_nest, "cargo_path", False):
            return main
        cargo = world.cargo_entrance
        weight = float(part.weight) if part is not None else 0.0
        if weight >= heavy_thresh:
            return cargo

        def score(target: Vec2) -> float:
            d = world.wrap_delta(self.pos, target)
            dist = d.length()
            if dist < 1e-6:
                return 0.0
            heading = d.angle()
            block = wall_ahead_grid(
                self.pos, heading, world.pheromones, min(80.0, dist)
            )
            # Lower is better. Wall blockage is expensive — prefer open mouth.
            return dist + block * 140.0

        return cargo if score(cargo) < score(main) else main

    def _grip_part(
        self,
        world: "World",
        part: FoodPart,
        others_slots: Optional[Dict[int, int]] = None,
    ) -> None:
        """Bite a free socket on a loose part (cannot free-walk until release/delivery)."""
        from src.sim.haul_physics import assign_grip_slot, max_carriers

        max_c = max_carriers(self.forage_cfg)
        if self.ant_id not in part.carrier_ids and len(part.carrier_ids) >= max_c:
            return
        occ = dict(others_slots or {})
        slot = assign_grip_slot(
            part,
            self.pos,
            occ,
            max_c,
            world.wrap_delta,
            world=world,
            ant_radius=float(self.radius),
        )
        if slot < 0:
            return
        self.carried_part_id = part.uid
        self.grip_slot = slot
        part.carrier_ids.add(self.ant_id)
        self.carrying_food = part.nutrition
        self.food_quality = part.quality
        self.steps_since_deposit = 999.0
        self.last_trail_cell = None
        self.pickup_pos = part.pos.copy()
        self.ars_time = 0.0
        # C4: record food direction (vector from home to here = outbound bearing to remember)
        to_food = world.wrap_delta(world.home_entrance, self.pos)
        if to_food.length_sq() > 1e-6:
            self.food_memory_dir = to_food.normalized()
            self.food_memory_strength = 1.0
        self.haul_frustration = 0.0
        self.haul_detour_active = False
        self.haul_detour_dist = 0.0
        self.haul_regrip_cooldown = 0.0
        self.haul_goal_best_dist = -1.0
        self.haul_no_home_progress_time = 0.0
        self.haul_failed_detours = 0
        self._set_state(AntState.FORAGE_RETURN)
        heavy_thresh = float(self.forage_cfg.get("cargo_path_min_weight", 2.0))
        approach = self._pick_haul_entrance(world, part, heavy_thresh)
        to_home = world.wrap_delta(self.pos, approach)
        if to_home.length_sq() > 1e-6:
            self.desired_heading = to_home.angle()
            self.heading = self.desired_heading
            self.haul_goal_best_dist = to_home.length()

    def _release_part(
        self,
        world: "World",
        cooldown: Optional[float] = None,
    ) -> None:
        """Drop gripped food in place; optional re-grip cooldown."""
        if self.carried_part_id is None:
            return
        part = self.gripped_part(world)
        if part is not None:
            part.carrier_ids.discard(self.ant_id)
        self.carried_part_id = None
        self.grip_slot = -1
        self.carrying_food = 0.0
        self.food_quality = 0.0
        self.haul_frustration = 0.0
        self.haul_detour_active = False
        self.haul_detour_dist = 0.0
        self.haul_goal_best_dist = -1.0
        self.haul_no_home_progress_time = 0.0
        self.haul_failed_detours = 0
        if cooldown is None:
            cooldown = float(self.forage_cfg.get("haul_grip_cooldown", 8.0))
        self.grip_cooldown = max(0.0, float(cooldown))
        # Resume free forage (part stays for others). Search locally first —
        # real foragers loop around a dropped load rather than abandoning the area.
        if world.is_inside_home(self.pos):
            self._set_state(AntState.IDLE_IN_NEST)
        else:
            self._start_ars(self.pos)
            self._set_state(AntState.EXPLORE)

    def _haul_goal_pos(self, world: "World") -> Vec2:
        """Current approach target for homeward progress (entrance or home tile)."""
        part = self.gripped_part(world)
        heavy_thresh = float(self.forage_cfg.get("cargo_path_min_weight", 2.0))
        if world.is_inside_home(self.pos):
            return world.home_tile
        return self._pick_haul_entrance(world, part, heavy_thresh)

    def update_haul_frustration(
        self,
        pull_along: float,
        expected_along: float,
        dt: float,
        fcfg: Dict[str, Any],
        world: Optional["World"] = None,
    ) -> None:
        """
        pull_along = load displacement · my_pull_dir this frame.
        expected_along ≈ speed*dt if the load followed my pull fully.

        Heavy/slow pieces must not auto-frustrate: success is relative.
        If the load is not getting closer to the nest for long enough, release
        the grip and start a re-grip cooldown.
        """
        need = float(fcfg.get("haul_stuck_time", 1.2))
        block = float(fcfg.get("haul_unstick_blocks", 4.0))
        tile = float(fcfg.get("haul_unstick_block_size", 10.0))
        detour_need = max(tile, block * tile)
        # Succeed if we got a decent fraction of expected motion (not absolute units)
        frac = float(fcfg.get("haul_pull_success_frac", 0.25))
        success_eps = max(0.02, expected_along * frac)

        # --- Progress toward base (give up if stuck away from nest) ---
        if world is not None and self.carried_part_id is not None:
            near_drop = (
                world.wrap_delta(self.pos, world.home_tile).length()
                < float(fcfg.get("unload_radius", 14.0)) * 3.0
            )
            if not near_drop:
                goal = self._haul_goal_pos(world)
                # Use part position when available (true load progress)
                part = self.gripped_part(world)
                probe = part.pos if part is not None else self.pos
                dist = world.wrap_delta(probe, goal).length()
                prog_eps = float(fcfg.get("haul_progress_eps", 4.0))
                if self.haul_goal_best_dist < 0.0:
                    self.haul_goal_best_dist = dist
                if dist < self.haul_goal_best_dist - prog_eps:
                    self.haul_goal_best_dist = dist
                    self.haul_no_home_progress_time = 0.0
                    self.haul_failed_detours = 0
                else:
                    # Not closing on the nest — count as stalled homeward progress
                    self.haul_no_home_progress_time += dt

                give_up = float(fcfg.get("haul_give_up_time", 6.0))
                max_detours = int(fcfg.get("haul_give_up_detours", 3))
                if (
                    self.haul_no_home_progress_time >= give_up
                    or self.haul_failed_detours >= max_detours
                ):
                    cd = float(fcfg.get("haul_grip_cooldown", 8.0))
                    self._release_part(world, cooldown=cd)
                    return

        if self.haul_detour_active:
            if pull_along > success_eps:
                self.haul_detour_active = False
                self.haul_frustration = 0.0
                self.haul_detour_dist = 0.0
                return
            # Time-based detour length (don't use abs(pull_along) which thrives on noise)
            self.haul_detour_dist += dt * 10.0  # ~world units of "attempt budget"
            if self.haul_detour_dist >= detour_need:
                self.haul_detour_active = False
                self.haul_frustration = 0.0
                self.haul_detour_dist = 0.0
                self.haul_regrip_cooldown = 0.8  # brief calm before next detour
                self.haul_failed_detours += 1
            return

        if self.haul_regrip_cooldown > 0.0:
            self.haul_regrip_cooldown = max(0.0, self.haul_regrip_cooldown - dt)
            return

        if pull_along > success_eps:
            self.haul_frustration = max(0.0, self.haul_frustration - dt * 3.0)
            return

        # Only count as failure if we expected meaningful motion
        if expected_along < 1e-4:
            return

        self.haul_frustration += dt
        if self.haul_frustration >= need:
            if self.haul_last_detour_side == 0.0:
                self.haul_detour_side = 1.0
            else:
                self.haul_detour_side = -self.haul_last_detour_side
            self.haul_last_detour_side = self.haul_detour_side
            self.haul_detour_active = True
            self.haul_detour_dist = 0.0
            self.haul_frustration = 0.0

    def _apply_haul_frustration_detour(
        self, world: "World", rng: Rng, dt: float
    ) -> None:
        """
        Personal detour: ±90° from *this frame's* pathfinding goal.
        Wall slide when the goal ray is blocked; at exterior corners also peel
        into free space so the load does not sit in the same pocket forever.
        """
        from src.sim.wall_sense import nearest_wall_grid, wall_ahead_grid

        goal_h = self.desired_heading  # pure nav goal from steering this frame
        goal_v = Vec2.from_angle(goal_h)

        if self.haul_detour_active:
            # Blend ±90° with free-space normal so detours leave wall pockets
            detour = goal_h + self.haul_detour_side * (math.pi * 0.5)
            hit = nearest_wall_grid(
                self.pos, world.pheromones, max_range=24.0
            )
            if hit is not None and hit.distance < 14.0:
                free = hit.normal.angle()
                # Weighted average in vector space
                v = Vec2.from_angle(detour) * 0.7 + hit.normal * 0.55
                if v.length_sq() > 1e-8:
                    self.desired_heading = v.angle()
                else:
                    self.desired_heading = detour
            else:
                self.desired_heading = detour
            return

        # Only divert along wall if we would walk into it
        sense = float(self.loco_cfg.get("arena_wall_sense_range", 36.0))
        front = wall_ahead_grid(
            self.pos, goal_h, world.pheromones, min(sense, 28.0)
        )
        if front < 0.2:
            return
        hit = nearest_wall_grid(self.pos, world.pheromones, max_range=sense)
        if hit is None or hit.distance > 20.0:
            return
        n = hit.normal
        t1 = Vec2(-n.y, n.x)
        t2 = Vec2(n.y, -n.x)

        # Score both wall slides by whether the goal ray opens after stepping.
        # Critical when goal is straight into a corridor side-wall: N/S both
        # have ~0 goal-dot, but one walks around the mouth tip.
        def _opens_after(tang: Vec2) -> float:
            probe = self.pos + tang.normalized() * 14.0
            if world.circle_hits_wall(probe, 2.0):
                return -1.0
            # Fraction of a short goal-ray that stays free
            u = goal_v.normalized() if goal_v.length_sq() > 1e-12 else goal_v
            clear = 0.0
            for k in range(1, 5):
                p = probe + u * (k * 5.0)
                if world.circle_hits_wall(p, 2.0):
                    break
                clear = k / 4.0
            return clear

        s1, s2 = _opens_after(t1), _opens_after(t2)
        # Prefer goal-aligned tangent when it also opens; else best opener
        if t1.dot(goal_v) >= t2.dot(goal_v):
            primary, secondary = t1, t2
            sp, ss = s1, s2
        else:
            primary, secondary = t2, t1
            sp, ss = s2, s1
        if sp >= ss and sp >= 0.0:
            tang = primary
        elif ss >= 0.0:
            tang = secondary
        elif t1.dot(goal_v) < 0.0 and t2.dot(goal_v) < 0.0:
            peel = (n + goal_v * 0.25).normalized()
            if peel.length_sq() > 1e-8:
                self.desired_heading = peel.angle()
            return
        else:
            tang = primary
        slide = (tang.normalized() + n * 0.15 + goal_v * 0.1)
        if slide.length_sq() > 1e-8:
            self.desired_heading = slide.normalized().angle()
        else:
            self.desired_heading = tang.angle()

    def _update_stuck(
        self, world: "World", colony: "Colony", dt: float, moved: float
    ) -> None:
        """If nearly motionless for stuck_timeout seconds, teleport to home tile."""
        eps = float(self.forage_cfg.get("stuck_move_epsilon", 0.4))
        timeout = float(self.forage_cfg.get("stuck_timeout", 10.0))
        if moved < eps:
            self.stuck_time += dt
        else:
            self.stuck_time = 0.0
            return
        if self.stuck_time < timeout:
            return
        # Before teleporting, try a path-integration nudge (cheaper rescue).
        # If PI vector is large enough, it knows roughly where home is.
        pi_len = self.path_integration.length()
        if pi_len > 30.0 and self.stuck_time < timeout * 1.8:
            self.heading = (-self.path_integration).angle()
            self.stuck_time = timeout * 0.5  # partial reset — gives another try
            return
        self._teleport_home(world, colony)

    def _teleport_home(self, world: "World", colony: "Colony") -> None:
        """Rescue stuck ant — drop any grip so multi-haul isn't deleted."""
        # Deposit alarm at the stuck position so nearby ants notice the trouble (C1)
        world.pheromones.deposit(
            self.pos,
            float(self.forage_cfg.get("alarm_deposit", 30.0)),
            layer="alarm",
        )
        if self.carried_part_id is not None:
            # Teleport drop: short cooldown so she doesn't immediately re-grab
            cd = float(self.forage_cfg.get("haul_grip_cooldown", 8.0)) * 0.5
            self._release_part(world, cooldown=cd)

        home = world.home_tile
        self.pos = world.resolve_circle(home.copy(), self.radius)
        self.heading = world.wrap_delta(self.pos, world.home_entrance).angle()
        self.stuck_time = 0.0
        self.last_trail_cell = None
        self.trip_distance = 0.0
        self.time_in_state = 0.0
        self.path_integration = Vec2()
        self.pickup_pos = None
        self.ars_time = 0.0
        self.uturn_cooldown = 0.0
        self.contact_boost_time = 0.0
        self.was_on_trail = False
        self._set_state(AntState.IDLE_IN_NEST)

    def _try_deposit_trail(
        self,
        world: "World",
        old_pos: Vec2,
        new_pos: Vec2,
    ) -> None:
        """
        Simple trail laying: while carrying, drop a fixed chemical amount
        once per newly entered tile.

            add = deposit_amount

        Reinforcement = many ants (or return trips) each adding the same amount.
        No boost curves, no max×base, no existing-multiplier formulas.
        """
        if not self.is_carrying:
            return
        cells = world.pheromones.cells_along_segment(old_pos, new_pos)
        laid = False
        for rc in cells:
            if rc == self.last_trail_cell:
                continue
            self.last_trail_cell = rc
            r, c = rc
            amount = self._compute_deposit_amount(world, r, c)
            if amount <= 0.0:
                continue
            world.pheromones.deposit_at_cell(r, c, amount, layer="trail")
            laid = True
        if laid:
            self.steps_since_deposit = 0.0

    def _try_unload(self, world: "World", colony: "Colony") -> None:
        """Legacy scalar unload — part delivery is handled in world.resolve_hauling."""
        if self.carried_part_id is not None:
            return
        if self.carrying_food <= 1e-6:
            return
        if not world.at_home_tile(self.pos):
            return
        if world.circle_hits_wall(self.pos, self.radius * 0.9):
            return
        colony.food_store += self.carrying_food
        colony.forage_deliveries += 1
        self.carrying_food = 0.0
        self.food_quality = 0.0
        self.trip_distance = 0.0
        self.nestmates_at_pickup = 0
        self.last_trail_cell = None
        self.stuck_time = 0.0
        self.pickup_pos = None
        self.found_as_scout = False
        sip = float(self.forage_cfg.get("energy_delivery_sip", 0.12))
        self.energy = min(1.0, self.energy + sip)
        self._set_state(AntState.IDLE_IN_NEST)

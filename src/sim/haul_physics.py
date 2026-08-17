"""
Cooperative haul physics — passive load + summed ant forces.

The food never decides anything. Each gripping ant supplies a force from her
own desired heading; the piece moves from F_net, mass, friction, and walls.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.sim.wall_sense import nearest_wall_grid
from src.util.vec import Vec2

if TYPE_CHECKING:
    from src.agents.ant import WorkerAnt
    from src.sim.carcass import FoodPart
    from src.sim.world import World


def max_carriers(fcfg: Dict[str, Any]) -> int:
    return max(1, int(fcfg.get("max_carriers_per_part", 4)))


def grip_slot_angle(slot: int, n_slots: int) -> float:
    """Fixed world-relative socket angle (does NOT spin with part.angle)."""
    n_slots = max(1, n_slots)
    # Evenly around the rim; stable so ants don't orbit/spasm
    return (2.0 * math.pi * slot) / n_slots


def grip_world_pos(part: "FoodPart", slot: int, n_slots: int) -> Vec2:
    ang = grip_slot_angle(slot, n_slots)
    r = max(2.0, float(part.radius) * 0.75)
    return part.pos + Vec2.from_angle(ang, r)


def eject_from_wall(
    pos: Vec2,
    radius: float,
    world: "World",
    max_iters: int = 12,
) -> Vec2:
    """
    Push a circle fully out of WALL tiles.

    resolve_circle alone can leave centers near concave corners still grazing
    walls; this walks free-space normals and finally samples a free ring.
    """
    r = max(0.5, float(radius))
    p = world.resolve_circle(pos, r, max_iters=max(6, max_iters))
    if world.wrap:
        p = world.wrap_position(p)
    cs = float(getattr(world, "tile_size", 10.0))

    for _ in range(max_iters):
        if not world.circle_hits_wall(p, r):
            return p
        hit = nearest_wall_grid(p, world.pheromones, max_range=r * 6.0 + cs * 3.0)
        if hit is None:
            p = world.resolve_circle(p, r, max_iters=8)
            break
        # Push at least a good fraction of a tile so thick walls clear in few steps
        need = max(cs * 0.55, r - hit.distance + 1.25)
        p = p + hit.normal * need
        p = world.resolve_circle(p, r, max_iters=4)
        if world.wrap:
            p = world.wrap_position(p)

    if not world.circle_hits_wall(p, r):
        return p

    # Ring search: nearest free center around original / current pos
    origin = p
    best = None
    best_d2 = float("inf")
    for ring in range(1, 10):
        rad = ring * cs * 0.55 + r
        steps = 8 + ring * 4
        for i in range(steps):
            ang = (2.0 * math.pi * i) / steps
            cand = origin + Vec2.from_angle(ang, rad)
            if world.wrap:
                cand = world.wrap_position(cand)
            if world.circle_hits_wall(cand, r):
                continue
            d2 = world.wrap_delta(pos, cand).length_sq()
            if d2 < best_d2:
                best_d2 = d2
                best = cand
        if best is not None:
            return best
    return p


def project_dir_off_wall(
    direction: Vec2,
    pos: Vec2,
    world: "World",
    sense: float = 28.0,
    contact_pad: float = 10.0,
) -> Vec2:
    """
    Remove the component of `direction` that pushes into a *nearby* wall.

    Only engages when the wall is almost in contact. Projecting from far
    away (e.g. 30px) turned open westbound approaches into pure N/S
    wall-parallel slides that never reached the corridor mouth.
    """
    if direction.length_sq() < 1e-16:
        return direction
    hit = nearest_wall_grid(pos, world.pheromones, max_range=sense)
    if hit is None:
        return direction
    # Only deflect when we would hit this step / are grazing the face
    if hit.distance > contact_pad:
        return direction
    n = hit.normal  # free-space direction
    into = -n
    d = direction.normalized()
    pen = d.dot(into)
    if pen <= 0.05:
        return direction
    slide = d - into * pen
    if slide.length_sq() < 1e-10:
        esc = _corner_escape_dir(pos, d, world, sense=max(sense, 36.0))
        if esc is not None and esc.length_sq() > 1e-12:
            return esc
        return Vec2(-n.y, n.x)
    return slide.normalized()


def free_space_grip_pos(
    part: "FoodPart",
    slot: int,
    n_slots: int,
    world: "World",
    ant_radius: float,
) -> Vec2:
    """
    Grip socket that must sit in free space (not inside WALL).
    If the nominal rim slot is blocked, search nearby angles, then fall back
    to part center + free-space normal.
    """
    r_ant = max(0.5, float(ant_radius) * 0.4)
    nominal = grip_world_pos(part, slot, n_slots)
    if not world.circle_hits_wall(nominal, r_ant):
        return eject_from_wall(nominal, r_ant, world, max_iters=4)

    base_ang = grip_slot_angle(slot, n_slots)
    rim = max(2.0, float(part.radius) * 0.75)
    # Fan ± around the slot looking for free space on the rim
    for k in range(1, 10):
        for sign in (1.0, -1.0):
            ang = base_ang + sign * (k * 0.22)
            cand = part.pos + Vec2.from_angle(ang, rim)
            if not world.circle_hits_wall(cand, r_ant):
                return eject_from_wall(cand, r_ant, world, max_iters=4)

    # Last resort: stand on free side of part (out of wall)
    hit = nearest_wall_grid(part.pos, world.pheromones, max_range=part.radius * 4.0 + 30.0)
    if hit is not None:
        cand = part.pos + hit.normal * (rim + r_ant)
        if not world.circle_hits_wall(cand, r_ant):
            return eject_from_wall(cand, r_ant, world, max_iters=4)
    # Absolute fallback: part center (ejected)
    return eject_from_wall(part.pos.copy(), r_ant, world, max_iters=6)


def assign_grip_slot(
    part: "FoodPart",
    ant_pos: Vec2,
    occupied_slots: Dict[int, int],
    n_slots: int,
    wrap_delta_fn,
    world: Optional["World"] = None,
    ant_radius: float = 3.0,
) -> int:
    """Pick free socket nearest ant_pos (prefer free-space sockets). Returns -1 if full."""
    free = [s for s in range(n_slots) if s not in occupied_slots]
    if not free:
        return -1
    best = free[0]
    best_d = float("inf")
    best_blocked = True
    for s in free:
        gp = grip_world_pos(part, s, n_slots)
        blocked = False
        if world is not None:
            blocked = world.circle_hits_wall(gp, max(0.5, ant_radius * 0.35))
            if blocked:
                # Soft penalty — still allowed if all slots blocked
                gp = free_space_grip_pos(part, s, n_slots, world, ant_radius)
        d = wrap_delta_fn(ant_pos, gp).length_sq()
        if blocked:
            d += 1.0e6
        if d < best_d:
            best_d = d
            best = s
            best_blocked = blocked
    _ = best_blocked
    return best


def slots_occupied(
    part: "FoodPart", ants_by_id: Dict[int, "WorkerAnt"]
) -> Dict[int, int]:
    occ: Dict[int, int] = {}
    for aid in list(part.carrier_ids):
        ant = ants_by_id.get(aid)
        if ant is None:
            continue
        slot = int(getattr(ant, "grip_slot", -1))
        if slot >= 0:
            occ[slot] = aid
    return occ


def ant_pull_force(ant: "WorkerAnt", fcfg: Dict[str, Any]) -> Vec2:
    """Force from desired_heading. Reverse walk is weaker, not inverted."""
    strength = max(1e-6, float(getattr(ant, "strength", 1.0)))
    f_scale = float(fcfg.get("haul_pull_force", 1.0))
    reverse_scale = float(fcfg.get("reverse_haul_scale", 0.55))
    desired = float(getattr(ant, "desired_heading", ant.heading))
    u = Vec2.from_angle(desired)
    mag = strength * f_scale
    forward = Vec2.from_angle(ant.heading)
    # Only soften reverse; still pull in desired direction (not opposite)
    if u.dot(forward) < 0.0:
        mag *= reverse_scale
    return u * mag


def _path_opens(
    pos: Vec2,
    direction: Vec2,
    world: "World",
    probe_len: float = 16.0,
) -> float:
    """
    How clear is `direction` from pos? 1 = open, 0 = immediately blocked.
    Used to score wall-slides that walk around a wall tip into an opening.
    """
    if direction.length_sq() < 1e-12:
        return 0.0
    u = direction.normalized()
    step = max(3.0, min(8.0, probe_len / 3.0))
    d = step
    blocked_at = probe_len
    while d <= probe_len:
        p = pos + u * d
        if world.circle_hits_wall(p, 2.0):
            blocked_at = d
            break
        d += step
    return max(0.0, (blocked_at - step) / probe_len)


def _corner_escape_dir(
    pos: Vec2,
    direction: Vec2,
    world: "World",
    sense: float,
) -> Optional[Vec2]:
    """
    When pure goal-aligned tangent fails (pull straight into a wall face),
    slide along the wall in the direction that *opens* the intended path —
    e.g. walk past a corridor side-wall tip into the mouth, not freeze.
    """
    hit = nearest_wall_grid(pos, world.pheromones, max_range=sense)
    if hit is None:
        return None
    n = hit.normal
    t1 = Vec2(-n.y, n.x)
    t2 = Vec2(n.y, -n.x)
    step = min(14.0, sense * 0.4)
    candidates = [
        t1,
        t2,
        (t1 + n * 0.35).normalized(),
        (t2 + n * 0.35).normalized(),
        (t1 + direction * 0.4).normalized(),
        (t2 + direction * 0.4).normalized(),
    ]
    best: Optional[Vec2] = None
    best_score = -1e9
    for c in candidates:
        if c is None or c.length_sq() < 1e-12:
            continue
        u = c.normalized()
        probe = pos + u * step
        if world.circle_hits_wall(probe, 2.2):
            score = -12.0
        else:
            score = 2.0
            # Key: after sliding, does the *original* pull open up?
            score += 4.0 * _path_opens(probe, direction, world, probe_len=22.0)
            # Mild preference to still agree with pull
            score += 0.75 * u.dot(direction)
            # Prefer staying near the wall (follow) over bouncing out
            score += 0.15 * (1.0 - min(1.0, hit.distance / max(sense, 1.0)))
        if score > best_score:
            best_score = score
            best = u
    # If everything is awful, peel into free space rather than freeze
    if best is None or best_score < -5.0:
        return n if n.length_sq() > 1e-12 else best
    return best


def integrate_part(
    part: "FoodPart",
    forces: List[Vec2],
    carriers: List["WorkerAnt"],
    world: "World",
    dt: float,
    fcfg: Dict[str, Any],
) -> tuple[Vec2, float]:
    """
    Integrate one passive part.
    Returns (displacement, expected_speed) for frustration scaling.
    """
    if dt <= 0.0 or not forces or not carriers:
        return Vec2(0.0, 0.0), 0.0

    ant_mass_unit = max(1e-6, float(fcfg.get("ant_mass", 1.0)))
    mass_scale = max(0.05, float(fcfg.get("food_mass_scale", 1.0)))
    food_w = max(0.0, float(part.weight) * mass_scale)
    n = len(carriers)
    ant_mass_total = sum(
        ant_mass_unit * max(1e-6, float(a.strength)) for a in carriers
    )
    m_eff = max(ant_mass_total + food_w, 1e-6)

    F_net = Vec2(0.0, 0.0)
    f_sum = 0.0
    for f in forces:
        F_net = F_net + f
        f_sum += f.length()

    if f_sum < 1e-12:
        return Vec2(0.0, 0.0), 0.0

    alignment = F_net.length() / f_sum
    max_base = max(float(a.cfg.get("speed", 50.0)) for a in carriers)

    # v = base * alignment * (ant_mass / total_mass)
    v_mass = max_base * alignment * (ant_mass_total / m_eff)

    solo_pct = float(fcfg.get("solo_haul_speed_percent", 50.0))
    if solo_pct <= 1.0:
        solo_scale = max(0.01, min(1.0, solo_pct))
    else:
        solo_scale = max(0.01, min(1.0, solo_pct / 100.0))
    multi_scale = max(
        0.05, min(1.0, float(fcfg.get("multi_haul_speed_scale", 0.5)))
    )

    v_max = max_base * (solo_scale if n <= 1 else multi_scale)
    speed = min(v_mass, v_max) * float(fcfg.get("haul_gain", 1.0))

    # Heavy loads near walls still need a crawl floor or they never clear corners
    crawl_frac = max(0.04, float(fcfg.get("haul_wall_crawl_frac", 0.10)))
    wall_crawl = max_base * crawl_frac * max(0.35, alignment)

    if F_net.length_sq() < 1e-16 and speed < 1e-9:
        return Vec2(0.0, 0.0), speed

    r_col = max(1.0, float(part.radius) * 0.40)

    # If already embedded (common after grip snap / corner pin), eject first
    if world.circle_hits_wall(part.pos, r_col):
        part.pos = eject_from_wall(part.pos, r_col, world)

    direction = (
        F_net.normalized() if F_net.length_sq() > 1e-16 else Vec2(0.0, 0.0)
    )
    # Do not push the load into a face — slide along free space instead
    if direction.length_sq() > 1e-12:
        direction = project_dir_off_wall(
            direction, part.pos, world, sense=part.radius * 3.0 + 28.0
        )
    if direction.length_sq() < 1e-12:
        return Vec2(0.0, 0.0), max(speed, wall_crawl)

    old = part.pos.copy()
    near_wall = world.circle_hits_wall(part.pos, r_col + 4.0)
    use_speed = max(speed, wall_crawl) if near_wall else speed
    step_len = use_speed * dt
    trial = part.pos + direction * step_len

    if world.circle_hits_wall(trial, r_col):
        hit = nearest_wall_grid(
            part.pos, world.pheromones, max_range=part.radius * 4.0 + 36.0
        )
        moved = False
        # Prefer a longer wall-slide for heavy pieces (step_len already floored)
        slide_len = max(step_len, wall_crawl * dt * 1.25)
        if hit is not None:
            nrm = hit.normal
            t1 = Vec2(-nrm.y, nrm.x)
            t2 = Vec2(nrm.y, -nrm.x)
            # Prefer part's shared unstick side when multi-jam is active
            prefer = float(getattr(part, "haul_unstick_side", 0.0) or 0.0)
            best_tang: Optional[Vec2] = None
            best_ts = -1e9
            for tang in (t1, t2):
                along = tang.dot(direction)
                slide_u = tang
                cand = part.pos + slide_u * slide_len
                if world.circle_hits_wall(cand, r_col * 0.9):
                    cand = part.pos + slide_u * (slide_len * 0.5)
                    if world.circle_hits_wall(cand, r_col * 0.9):
                        continue
                opens = _path_opens(cand, direction, world, probe_len=24.0)
                score = opens * 4.0 + max(0.0, along) * 1.5
                # Shared unstick side bias (t1 is +90° of normal ≈ left-of-wall)
                cross = nrm.x * slide_u.y - nrm.y * slide_u.x
                if prefer != 0.0:
                    score += 1.2 if (cross * prefer) > 0.0 else -0.4
                score += 0.01 * slide_u.x
                if score > best_ts:
                    best_ts = score
                    best_tang = slide_u
            if best_tang is not None and best_ts > -0.5:
                trial = part.pos + best_tang * slide_len
                if world.circle_hits_wall(trial, r_col * 0.9):
                    trial = part.pos + best_tang * (slide_len * 0.5)
                moved = not world.circle_hits_wall(trial, r_col * 0.85)
            if not moved:
                esc = _corner_escape_dir(
                    part.pos, direction, world, sense=part.radius * 4.0 + 40.0
                )
                if esc is not None:
                    trial = part.pos + esc * slide_len
                    moved = True
                else:
                    trial = part.pos.copy()
        else:
            trial = part.pos.copy()

        trial = eject_from_wall(trial, r_col, world)
    else:
        trial = world.resolve_circle(trial, r_col)

    if world.wrap:
        trial = world.wrap_position(trial)

    # Prevent resolve/eject from flinging the load far opposite the pull
    disp_try = world.wrap_delta(old, trial)
    if disp_try.dot(direction) < -0.05 and disp_try.length() > step_len * 0.25:
        # Allow small free-space peels (normal-out) even if slightly against pull
        hit2 = nearest_wall_grid(old, world.pheromones, max_range=r_col * 3.0 + 16.0)
        if hit2 is None or disp_try.dot(hit2.normal) < 0.15:
            trial = old.copy()

    # Final safety: never leave the part center inside a wall
    if world.circle_hits_wall(trial, r_col):
        trial = eject_from_wall(trial, r_col, world)
        disp2 = world.wrap_delta(old, trial)
        if disp2.dot(direction) < -0.05 and disp2.length() > step_len * 0.5:
            # Eject went the wrong way — stay put rather than reverse haul
            trial = old.copy()
            if world.circle_hits_wall(trial, r_col):
                trial = eject_from_wall(trial, r_col, world)

    part.pos = trial
    disp = world.wrap_delta(old, part.pos)
    # Do NOT spin part.angle every frame — that rotated grips and caused spasms
    return disp, speed


def _consensus_pull(carriers: List["WorkerAnt"]) -> Vec2:
    """Average desired heading so multi-haul does not self-cancel."""
    acc = Vec2(0.0, 0.0)
    for ant in carriers:
        h = float(getattr(ant, "desired_heading", ant.heading))
        acc = acc + Vec2.from_angle(h)
    if acc.length_sq() < 1e-12:
        return Vec2(0.0, 0.0)
    return acc.normalized()


def _separate_parts(
    parts: List["FoodPart"], world: "World", dt: float
) -> None:
    """Soft push so heavy pieces do not stack in the same wall pocket."""
    active = [p for p in parts if not p.delivered]
    n = len(active)
    if n < 2:
        return
    for i in range(n):
        a = active[i]
        for j in range(i + 1, n):
            b = active[j]
            d = world.wrap_delta(a.pos, b.pos)
            dist = d.length()
            min_d = (float(a.radius) + float(b.radius)) * 0.65
            if dist >= min_d or dist < 1e-8:
                continue
            push = d.normalized() * ((min_d - dist) * 0.45)
            # Heavier piece moves less
            wa = max(0.2, float(a.weight))
            wb = max(0.2, float(b.weight))
            ta = wb / (wa + wb)
            tb = wa / (wa + wb)
            ra = max(1.0, float(a.radius) * 0.4)
            rb = max(1.0, float(b.radius) * 0.4)
            a.pos = eject_from_wall(a.pos - push * ta, ra, world, max_iters=4)
            b.pos = eject_from_wall(b.pos + push * tb, rb, world, max_iters=4)
            if world.wrap:
                a.pos = world.wrap_position(a.pos)
                b.pos = world.wrap_position(b.pos)


def step_hauling(
    parts: List["FoodPart"],
    ants_by_id: Dict[int, "WorkerAnt"],
    world: "World",
    dt: float,
    fcfg: Dict[str, Any],
) -> None:
    """Forces → move load → place ants on free-space grip sockets → frustration."""
    n_slots = max_carriers(fcfg)
    jam_need = float(fcfg.get("haul_group_jam_time", 1.6))
    unstick_dur = float(fcfg.get("haul_group_unstick_time", 2.8))

    # Unstack jammed piles first (bodies/heads sitting on the same corner)
    _separate_parts(parts, world, dt)

    # Always scrub stale grips so abandoned parts show free slots for new ants
    for part in parts:
        if part.delivered:
            continue
        live = {
            aid
            for aid in list(part.carrier_ids)
            if aid in ants_by_id
            and getattr(ants_by_id[aid], "carried_part_id", None) == part.uid
        }
        part.carrier_ids = live

    for part in parts:
        if part.delivered or not part.carrier_ids:
            continue

        carriers = [
            ants_by_id[i]
            for i in list(part.carrier_ids)
            if i in ants_by_id and ants_by_id[i].carried_part_id == part.uid
        ]
        part.carrier_ids = {a.ant_id for a in carriers}
        if not carriers:
            continue

        # Tick shared unstick window
        if part.haul_unstick_t > 0.0:
            part.haul_unstick_t = max(0.0, part.haul_unstick_t - dt)

        consensus = _consensus_pull(carriers)
        forces: List[Vec2] = []
        force_by_ant: Dict[int, Vec2] = {}

        # Coordinated unstick: all carriers pull the same wall-follow way
        unstick_active = part.haul_unstick_t > 0.0
        unstick_dir = Vec2(0.0, 0.0)
        if unstick_active:
            hit = nearest_wall_grid(
                part.pos, world.pheromones, max_range=part.radius * 4.0 + 36.0
            )
            goal = consensus if consensus.length_sq() > 1e-12 else Vec2.from_angle(
                float(carriers[0].desired_heading)
            )
            if hit is not None:
                n = hit.normal
                t1 = Vec2(-n.y, n.x)
                t2 = Vec2(n.y, -n.x)
                side = float(part.haul_unstick_side) or 1.0
                # t1 has positive cross with n for +side convention
                tang = t1 if side >= 0.0 else t2
                # Blend wall-slide with free normal + goal so we peel out of pockets
                unstick_dir = (tang * 1.0 + n * 0.45 + goal * 0.35)
                if unstick_dir.length_sq() > 1e-12:
                    unstick_dir = unstick_dir.normalized()
                else:
                    unstick_dir = tang
            else:
                unstick_dir = goal

        for ant in carriers:
            if unstick_active and unstick_dir.length_sq() > 1e-12:
                # Same direction for everyone — no opposing detours
                strength = max(1e-6, float(getattr(ant, "strength", 1.0)))
                f_scale = float(fcfg.get("haul_pull_force", 1.0))
                f = unstick_dir * (strength * f_scale)
                ant.desired_heading = unstick_dir.angle()
                ant.haul_detour_side = float(part.haul_unstick_side) or 1.0
                ant.haul_detour_active = True
            else:
                f = ant_pull_force(ant, fcfg)
                # Blend personal pull toward consensus so multi doesn't thrash
                if (
                    len(carriers) >= 2
                    and consensus.length_sq() > 1e-12
                    and f.length_sq() > 1e-12
                ):
                    blend = float(fcfg.get("haul_consensus_blend", 0.55))
                    mixed = (
                        f.normalized() * (1.0 - blend) + consensus * blend
                    ).normalized()
                    f = mixed * f.length()
                f_dir = project_dir_off_wall(
                    f,
                    ant.pos,
                    world,
                    sense=float(getattr(ant, "radius", 3.0)) * 6.0 + 20.0,
                )
                if f_dir.length_sq() > 1e-12 and f.length_sq() > 1e-12:
                    f = f_dir * f.length()
            forces.append(f)
            force_by_ant[ant.ant_id] = f

        disp, speed = integrate_part(part, forces, carriers, world, dt, fcfg)
        expected_along = max(speed * dt, 1e-6)

        # Group jam detection: almost no movement while we had expected speed
        moved = disp.length()
        near_wall = world.circle_hits_wall(
            part.pos, max(1.0, float(part.radius) * 0.4) + 5.0
        )
        if moved < expected_along * 0.12 and (near_wall or len(carriers) >= 2):
            part.haul_jam_time += dt
        else:
            part.haul_jam_time = max(0.0, part.haul_jam_time - dt * 1.5)

        if part.haul_unstick_t <= 0.0 and part.haul_jam_time >= jam_need:
            # Flip shared side so we try the other way around the obstacle
            part.haul_unstick_side = -float(part.haul_unstick_side or 1.0)
            if part.haul_unstick_side == 0.0:
                part.haul_unstick_side = 1.0
            part.haul_unstick_t = unstick_dur
            part.haul_jam_time = 0.0
            for ant in carriers:
                ant.haul_frustration = 0.0
                ant.haul_detour_active = True
                ant.haul_detour_side = part.haul_unstick_side
                ant.haul_detour_dist = 0.0

        for ant in carriers:
            prev = ant.pos.copy()
            slot = int(getattr(ant, "grip_slot", -1))
            if slot < 0 or slot >= n_slots:
                occ = {
                    s: aid
                    for s, aid in slots_occupied(part, ants_by_id).items()
                    if aid != ant.ant_id
                }
                slot = assign_grip_slot(
                    part,
                    ant.pos,
                    occ,
                    n_slots,
                    world.wrap_delta,
                    world=world,
                    ant_radius=float(getattr(ant, "radius", 3.0)),
                )
                ant.grip_slot = slot
            if slot >= 0:
                target = free_space_grip_pos(
                    part,
                    slot,
                    n_slots,
                    world,
                    float(getattr(ant, "radius", 3.0)),
                )
                ant.pos = target
                if world.wrap:
                    ant.pos = world.wrap_position(ant.pos)
            ant._haul_prev_pos = prev  # type: ignore[attr-defined]

            step_len = world.wrap_delta(prev, ant.pos).length()
            if step_len > 0.15:
                ant.walk_phase += step_len
                ant.trip_distance += step_len

            my_f = force_by_ant.get(ant.ant_id, Vec2())
            if my_f.length_sq() > 1e-8:
                along = disp.dot(my_f.normalized())
            else:
                along = 0.0
            # During group unstick, don't re-trigger personal detours that fight it
            if part.haul_unstick_t > 0.0:
                ant.haul_frustration = 0.0
            else:
                ant.update_haul_frustration(
                    along, expected_along, dt, fcfg, world=world
                )
            # Carrier may have given up and released mid-step
            if ant.carried_part_id is None and ant.ant_id in part.carrier_ids:
                part.carrier_ids.discard(ant.ant_id)

"""
Layered steering for ant locomotion (M0.5).

heading_dir = normalize(
  w_persist * heading
  + w_meander * side
  + w_wall * parallel_to_wall
  + w_avoid * separation
  + ...
)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.sim.wall_sense import (
    WallHit,
    nearest_wall,
    nearest_wall_grid,
    wall_ahead,
    wall_ahead_grid,
)
from src.util.rng import Rng
from src.util.vec import Vec2

Rect = Tuple[float, float, float, float]


@dataclass
class LocoDebug:
    """Optional per-step debug vectors for rendering."""

    persist: Vec2
    meander: Vec2
    wall: Vec2
    avoid: Vec2
    combined: Vec2
    wall_hit: Optional[WallHit]
    inside_nest: bool
    weights: Dict[str, float]


def _angle_diff(a: float, b: float) -> float:
    """Smallest signed difference a - b in (-pi, pi]."""
    d = (a - b + math.pi) % (2.0 * math.pi) - math.pi
    return d


def _rotate90(v: Vec2, sign: float) -> Vec2:
    """Rotate v by +90° (sign>0) or -90° (sign<0)."""
    if sign >= 0:
        return Vec2(-v.y, v.x)
    return Vec2(v.y, -v.x)


def steering_weights(
    loco: Dict[str, Any], inside_nest: bool
) -> Dict[str, float]:
    """State-ish presets: nest corridors vs open arena with obstacle detour."""
    base = {
        "persist": float(loco.get("persistence_weight", 1.0)),
        "meander": float(loco.get("meander_amplitude", 0.35)),
        "wall": float(loco.get("wall_follow_weight", 0.9)),
        "avoid": float(loco.get("separation_weight", 0.7)),
        "turn_noise": float(loco.get("turn_noise_sigma", 0.12)),
    }
    if inside_nest:
        base["wall"] *= float(loco.get("nest_wall_boost", 1.6))
        base["meander"] *= float(loco.get("nest_meander_scale", 0.45))
        base["turn_noise"] *= float(loco.get("nest_noise_scale", 0.7))
    else:
        # Outside: sense walls/obstacles and detour toward goals (not pure thigmotaxis)
        base["meander"] *= float(loco.get("arena_meander_boost", 1.25))
        base["wall"] *= float(loco.get("arena_wall_scale", 1.0))
    return base


def wall_follow_vector(
    heading: float,
    hit: Optional[WallHit],
    wall_sense_range: float,
    preferred_side: float,
    front_block: float,
) -> Vec2:
    """
    Thigmotaxis: align parallel to nearest wall; keep preferred side.
    preferred_side: +1 = prefer wall on left, -1 = on right.
    """
    if hit is None or hit.distance > wall_sense_range:
        return Vec2(0.0, 0.0)

    # Strength falls off with distance (stronger near wall)
    proximity = 1.0 - (hit.distance / wall_sense_range)
    proximity = max(0.0, min(1.0, proximity)) ** 0.7

    n = hit.normal
    # Two tangents along the wall
    t_left = _rotate90(n, +1.0)   # wall normal rotated → left-ish along surface
    t_right = _rotate90(n, -1.0)

    h = Vec2.from_angle(heading)
    # Prefer tangent aligned with current heading
    if t_left.dot(h) >= t_right.dot(h):
        tangent = t_left
    else:
        tangent = t_right

    # Bias to keep wall on preferred side:
    # wall is on left of travel if cross(heading, -normal? ) ...
    # Normal points into free space (away from wall). Wall is "to the left"
    # if rotating heading toward -normal is a left turn... simpler:
    # desired: preferred_side * cross(heading, normal) ~ wall on that side
    # cross2d(h, n) > 0 means n is left of h.
    # We want wall (direction of -n, into wall) ... 
    # If wall should be on left: free-space normal should point roughly right of heading
    # i.e. cross(h, n) < 0 when wall is on left.
    cross = h.x * n.y - h.y * n.x  # >0 if n left of h
    # preferred_side +1 want wall left → want n on right → cross < 0
    side_error = preferred_side * cross  # positive if wrong side
    # Small correction rotate tangent toward preferred side
    correction = _rotate90(tangent, -preferred_side) * (0.35 * side_error)
    # Also gently push away if too close (avoid scraping into wall)
    push = n * max(0.0, 0.4 - hit.distance / max(wall_sense_range, 1e-6)) * 0.5

    # Front blocked: turn hard along wall instead of into it
    if front_block > 0.15:
        # Strongly prefer tangent; add normal component to peel off if nose-in
        tangent = tangent * (1.0 + 1.5 * front_block) + n * (0.3 * front_block)

    out = (tangent + correction + push).normalized() * proximity
    return out


def wall_avoid_toward_goal(
    heading: float,
    goal: Optional[Vec2],
    hit: Optional[WallHit],
    wall_sense_range: float,
    front_block: float,
    goal_block: float = 0.0,
    preferred_side: float = 1.0,
) -> Vec2:
    """
    Outdoor / goal-directed obstacle detour.

    When a wall is near or blocks the way toward ``goal``, steer along the
    wall tangent that best keeps progress toward the goal (not random side).
    Stronger when the nose or goal ray is blocked.
    """
    if hit is None or hit.distance > wall_sense_range:
        return Vec2(0.0, 0.0)

    proximity = 1.0 - (hit.distance / max(wall_sense_range, 1e-6))
    proximity = max(0.0, min(1.0, proximity)) ** 0.65

    n = hit.normal
    t_left = _rotate90(n, +1.0)
    t_right = _rotate90(n, -1.0)

    g: Optional[Vec2] = None
    if goal is not None and goal.length_sq() > 1e-8:
        g = goal.normalized()

    if g is not None:
        # Tangent more aligned with goal = preferred detour side
        if t_left.dot(g) >= t_right.dot(g):
            tangent = t_left
        else:
            tangent = t_right
        # If both tangents oppose goal, peel off with free-space normal
        if tangent.dot(g) < 0.05:
            tangent = (tangent * 0.35 + n * 0.65 + g * 0.4)
            if tangent.length_sq() > 1e-12:
                tangent = tangent.normalized()
    else:
        h = Vec2.from_angle(heading)
        if t_left.dot(h) >= t_right.dot(h):
            tangent = t_left
        else:
            tangent = t_right
        cross = h.x * n.y - h.y * n.x
        side_error = preferred_side * cross
        tangent = (
            tangent + _rotate90(tangent, -preferred_side) * (0.3 * side_error)
        ).normalized()

    # Blockage boost: blocked ahead or blocked toward goal → hard detour
    block = max(0.0, min(1.0, max(front_block, goal_block)))
    # Only mild wall influence when far and clear; strong when obstructed
    strength = proximity * (0.25 + 1.35 * block)
    if block < 0.08 and proximity < 0.45:
        strength *= 0.35

    push = n * (0.25 + 0.55 * block) * proximity
    # Blend a little goal so detours still advance when free along the wall
    goal_blend = g * (0.2 * (1.0 - block)) if g is not None else Vec2(0.0, 0.0)
    out = tangent * (1.0 + 1.8 * block) + push + goal_blend
    if out.length_sq() < 1e-12:
        return Vec2(0.0, 0.0)
    return out.normalized() * strength


def separation_vector(
    pos: Vec2,
    others: Sequence[Vec2],
    separation_radius: float,
    self_index: int = -1,
    wrap_delta_fn=None,
    spatial=None,
) -> Vec2:
    """
    Soft repulsion. wrap_delta_fn(from, to) -> shortest vector if toroidal.

    If ``spatial`` is a SpatialHash2D built from ``others``, only nearby
    cells are scanned (≈O(n) total per frame instead of O(n²)).
    """
    if separation_radius <= 0:
        return Vec2(0.0, 0.0)
    r2 = separation_radius * separation_radius
    count = 0
    ax = 0.0
    ay = 0.0
    if spatial is not None:
        indices = spatial.query_indices(pos, separation_radius)
        n_others = len(others)
        for i in indices:
            if i == self_index or i < 0 or i >= n_others:
                continue
            o = others[i]
            if wrap_delta_fn is not None:
                d = wrap_delta_fn(o, pos)
                dx, dy = d.x, d.y
            else:
                dx = pos.x - o.x
                dy = pos.y - o.y
            d2 = dx * dx + dy * dy
            if d2 < 1e-8 or d2 > r2:
                continue
            dist = math.sqrt(d2)
            inv = ((separation_radius - dist) / separation_radius) / dist
            ax += dx * inv
            ay += dy * inv
            count += 1
    else:
        for i, o in enumerate(others):
            if i == self_index:
                continue
            if wrap_delta_fn is not None:
                d = wrap_delta_fn(o, pos)
                dx, dy = d.x, d.y
            else:
                dx = pos.x - o.x
                dy = pos.y - o.y
            d2 = dx * dx + dy * dy
            if d2 < 1e-8 or d2 > r2:
                continue
            dist = math.sqrt(d2)
            inv = ((separation_radius - dist) / separation_radius) / dist
            ax += dx * inv
            ay += dy * inv
            count += 1

    if count == 0:
        return Vec2(0.0, 0.0)
    L2 = ax * ax + ay * ay
    if L2 < 1e-12:
        return Vec2(0.0, 0.0)
    invL = 1.0 / math.sqrt(L2)
    return Vec2(ax * invL, ay * invL)


def meander_vector(heading: float, phase: float, amplitude: float) -> Vec2:
    """Lateral bias oscillating with phase (Popp-style alternating turns)."""
    if amplitude <= 0:
        return Vec2(0.0, 0.0)
    side = math.sin(phase)  # -1..1
    lateral = Vec2.from_angle(heading + math.pi * 0.5)  # left of heading
    return lateral * (side * amplitude)


def compute_steering(
    pos: Vec2,
    heading: float,
    meander_phase: float,
    preferred_wall_side: float,
    walls: List[Rect],
    others: Sequence[Vec2],
    self_index: int,
    inside_nest: bool,
    loco: Dict[str, Any],
    rng: Rng,
    wrap_delta_fn=None,
    v_trail: Optional[Vec2] = None,
    w_trail: float = 0.0,
    v_home: Optional[Vec2] = None,
    w_home: float = 0.0,
    v_food: Optional[Vec2] = None,
    w_food: float = 0.0,
    meander_scale: float = 1.0,
    tile_grid=None,
    spatial=None,
) -> Tuple[float, float, LocoDebug]:
    """
    Returns (desired_heading, meander_length, debug).

    Optional chemotaxis / goal vectors (M1+):
      v_trail uphill food trail, v_home nest scent / entrance direction,
      v_food antenna-sensed prey direction.

    If tile_grid is provided, wall sensing uses local tile roles (fast).
    If spatial is a SpatialHash2D of ``others``, separation is O(neighbors).
    """
    w = steering_weights(loco, inside_nest)
    wall_range = float(loco.get("wall_sense_range", 22.0))
    if not inside_nest:
        wall_range = float(loco.get("arena_wall_sense_range", wall_range * 1.35))
    sep_r = float(loco.get("separation_radius", 12.0))
    meander_len = float(loco.get("meander_length", 14.0))  # ~3 body lengths

    # Sense walls both in nest and outside (nest shell / obstacles)
    need_wall = inside_nest or w["wall"] > 1e-6
    wall_samples = 3 if not inside_nest else 5
    if need_wall:
        if tile_grid is not None:
            hit = nearest_wall_grid(pos, tile_grid, max_range=wall_range)
            # Skip expensive ray march when no wall nearby
            if hit is not None and hit.distance <= wall_range:
                front = wall_ahead_grid(
                    pos, heading, tile_grid, wall_range, samples=wall_samples
                )
            elif inside_nest:
                front = wall_ahead_grid(
                    pos, heading, tile_grid, wall_range, samples=wall_samples
                )
            else:
                front = 0.0
        else:
            hit = nearest_wall(pos, walls)
            front = (
                wall_ahead(pos, heading, walls, wall_range)
                if hit is not None or inside_nest
                else 0.0
            )
    else:
        hit = None
        front = 0.0

    vt = v_trail if v_trail is not None else Vec2(0.0, 0.0)
    vh = v_home if v_home is not None else Vec2(0.0, 0.0)
    vf = v_food if v_food is not None else Vec2(0.0, 0.0)
    # Normalize goal vectors if strong so weights are comparable
    if vt.length_sq() > 1e-8:
        vt = vt.normalized()
    if vh.length_sq() > 1e-8:
        vh = vh.normalized()
    if vf.length_sq() > 1e-8:
        vf = vf.normalized()

    # Combined goal direction for outdoor detours (home / food / trail)
    goal = (
        vh * max(w_home, 0.0)
        + vf * max(w_food, 0.0)
        + vt * max(w_trail, 0.0)
    )
    if goal.length_sq() < 1e-10:
        goal = Vec2.from_angle(heading)
    else:
        goal = goal.normalized()

    # How blocked is the path toward the goal? (skip if wall is far)
    goal_block = 0.0
    if need_wall and hit is not None and hit.distance <= wall_range * 0.85:
        if tile_grid is not None:
            goal_block = wall_ahead_grid(
                pos, goal.angle(), tile_grid, wall_range, samples=wall_samples
            )
        else:
            goal_block = wall_ahead(pos, goal.angle(), walls, wall_range)

    v_persist = Vec2.from_angle(heading)
    v_meander = meander_vector(heading, meander_phase, 1.0)  # weight applied below
    if w["wall"] > 1e-6:
        if inside_nest:
            # Corridors: classic thigmotaxis with preferred wall side
            v_wall = wall_follow_vector(
                heading, hit, wall_range, preferred_wall_side, front
            )
        else:
            # Outside: detour along wall toward goal (plan around obstacles)
            v_wall = wall_avoid_toward_goal(
                heading,
                goal,
                hit,
                wall_range,
                front,
                goal_block=goal_block,
                preferred_side=preferred_wall_side,
            )
            # Extra weight when the goal ray is blocked
            w = dict(w)
            w["wall"] *= 1.0 + float(loco.get("obstacle_block_boost", 1.4)) * goal_block
    else:
        v_wall = Vec2(0.0, 0.0)
    v_avoid = separation_vector(
        pos,
        others,
        sep_r,
        self_index,
        wrap_delta_fn=wrap_delta_fn,
        spatial=spatial,
    )

    combined = (
        v_persist * w["persist"]
        + v_meander * (w["meander"] * meander_scale)
        + v_wall * w["wall"]
        + v_avoid * w["avoid"]
        + vt * w_trail
        + vh * w_home
        + vf * w_food
    )

    if combined.length_sq() < 1e-12:
        desired = heading
    else:
        desired = combined.normalized().angle()

    # Angular noise (small; scaled by weight preset)
    noise = rng.gauss(0.0, w["turn_noise"])
    desired = desired + noise * 0.05  # noise applied lightly to target; rate-limited later

    debug = LocoDebug(
        persist=v_persist,
        meander=v_meander * w["meander"],
        wall=v_wall * w["wall"],
        avoid=v_avoid * w["avoid"],
        combined=combined.normalized() if combined.length_sq() > 1e-12 else v_persist,
        wall_hit=hit if hit and hit.distance <= wall_range else None,
        inside_nest=inside_nest,
        weights=w,
    )

    # Advance meander phase by distance-scale (caller multiplies by speed*dt)
    # phase rate stored as 2π / meander_length * distance later
    return desired, meander_len, debug


def apply_turn(
    heading: float, desired: float, max_turn_rate: float, dt: float
) -> float:
    """Rate-limited turn toward desired heading."""
    err = _angle_diff(desired, heading)
    max_step = max_turn_rate * dt
    if err > max_step:
        err = max_step
    elif err < -max_step:
        err = -max_step
    return heading + err


def slide_move(
    pos: Vec2,
    heading: float,
    speed: float,
    radius: float,
    dt: float,
    walls: List[Rect],
    resolve_fn,
    hits_fn,
    tile_grid=None,
) -> Tuple[Vec2, float]:
    """
    Move forward; if blocked, try slide along wall tangent then align heading.
    Returns (new_pos, maybe_adjusted_heading).
    """
    step = speed * dt
    direction = Vec2.from_angle(heading)
    trial = pos + direction * step

    if not hits_fn(trial, radius):
        return resolve_fn(trial, radius), heading

    # Blocked: try slide along nearest wall tangent (prefer goal-aligned side)
    if tile_grid is not None:
        hit = nearest_wall_grid(pos, tile_grid, max_range=radius * 4.0 + 24.0)
    else:
        hit = nearest_wall(pos, walls)
    if hit is not None:
        n = hit.normal
        t1 = _rotate90(n, +1.0)
        t2 = _rotate90(n, -1.0)
        # Pick tangent more aligned with intended direction
        tang = t1 if t1.dot(direction) >= t2.dot(direction) else t2
        # If almost into the wall, also peel off slightly
        slide_dir = (tang * 0.85 + n * 0.15).normalized()
        trial2 = pos + slide_dir * step
        if not hits_fn(trial2, radius):
            new_heading = slide_dir.angle()
            # Blend heading toward slide so next frames stay aligned
            return resolve_fn(trial2, radius), new_heading

        # Shorter slide
        trial3 = pos + slide_dir * (step * 0.4)
        if not hits_fn(trial3, radius):
            return resolve_fn(trial3, radius), slide_dir.angle()

    # Last resort: resolve in place, nudge heading away from wall
    if hit is not None:
        away = hit.normal.angle()
        heading = heading + 0.5 * _angle_diff(away, heading)
    return resolve_fn(pos, radius), heading

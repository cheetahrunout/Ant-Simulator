"""
Live config sidebar — tune sim parameters without restart.

Mutates the shared cfg dict in-place. Ants / world hold references to
cfg sub-dicts, so most changes apply immediately.

Sections are collapsible (click the category header) to free vertical space.
Hover a slider for 1s to see a short explanation tooltip.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pygame

from src.util.config import save_yaml
from src.util.vec import clamp


@dataclass
class SliderDef:
    path: str
    label: str
    min_v: float
    max_v: float
    step: float
    is_int: bool = False
    section: str = ""
    help: str = ""


SLIDERS: List[SliderDef] = [
    # --- Pheromone ---
    SliderDef(
        "pheromone.deposit_amount",
        "Deposit amount",
        0.0,
        50.0,
        0.25,
        section="Pheromone",
        help=(
            "Chemical units dropped once per new tile while carrying food. "
            "Reinforcement = more ants walking the same path each drop this amount."
        ),
    ),
    SliderDef(
        "pheromone.trail_evaporation",
        "Trail fade (units/s)",
        0.0,
        20.0,
        0.1,
        section="Pheromone",
        help=(
            "Base wind: every trail tile loses this many units each second. "
            "Applies to all strengths (normal path fade)."
        ),
    ),
    SliderDef(
        "pheromone.trail_high_threshold",
        "High-trail threshold",
        0.0,
        200.0,
        1.0,
        section="Pheromone",
        help=(
            "Above this value, extra fade applies to the excess. Big peaks "
            "(after many deposits) crash faster once food is gone."
        ),
    ),
    SliderDef(
        "pheromone.trail_high_fade_rate",
        "High-trail extra fade",
        0.0,
        2.0,
        0.05,
        section="Pheromone",
        help=(
            "Fraction of (value − high threshold) removed per second. "
            "0 = only base wind; 0.5 = half the excess vanishes each second."
        ),
    ),
    SliderDef(
        "pheromone.diffusion",
        "Trail diffusion",
        0.0,
        0.5,
        0.01,
        section="Pheromone",
        help=(
            "Mild blur of trail into free neighbours each second (0 = off). "
            "Small values make paths slightly wider and easier to sense."
        ),
    ),
    SliderDef(
        "pheromone.floor",
        "Trail floor",
        0.0,
        10.0,
        0.05,
        section="Pheromone",
        help=(
            "Any trail/nest value below this becomes 0. Clears dust after fade."
        ),
    ),
    SliderDef(
        "pheromone.nest_emit_rate",
        "Nest emit rate",
        0.0,
        100.0,
        1.0,
        section="Pheromone",
        help=(
            "How strongly nest scent is re-emitted each second at the home tile "
            "(and weaker at the entrance). Helps foragers home."
        ),
    ),
    SliderDef(
        "pheromone.nest_evaporation",
        "Nest fade (units/s)",
        0.0,
        10.0,
        0.05,
        section="Pheromone",
        help="Wind for nest scent: units removed per second from nest-scent tiles.",
    ),
    # --- Forage ---
    SliderDef(
        "forage.leave_nest_rate",
        "Leave nest rate",
        0.0,
        2.0,
        0.01,
        section="Forage",
        help=(
            "Base leave rate. Each ant scales this by nest food they last saw "
            "inside (empty nest → leave more; full store → stay)."
        ),
    ),
    SliderDef(
        "forage.leave_nest_store_ref",
        "Leave store ref",
        50.0,
        2000.0,
        10.0,
        section="Forage",
        help=(
            "Remembered food-store level that mid-scales leave urge. "
            "Higher = need more stock before ants slow leaving."
        ),
    ),
    SliderDef(
        "forage.trail_follow_weight",
        "Trail follow weight",
        0.0,
        5.0,
        0.05,
        section="Forage",
        help=(
            "Strength of steering toward food trails when outbound. Higher = "
            "ants stick to trails more tightly."
        ),
    ),
    SliderDef(
        "forage.nest_follow_weight",
        "Nest follow weight",
        0.0,
        5.0,
        0.05,
        section="Forage",
        help=(
            "Strength of following nest scent when returning or lost. Higher = "
            "stronger pull toward home."
        ),
    ),
    SliderDef(
        "forage.trail_follow_min",
        "Trail follow min",
        0.0,
        2.0,
        0.01,
        section="Forage",
        help=(
            "Minimum sensed trail strength before ants use trail following. "
            "Below this they explore more randomly."
        ),
    ),
    SliderDef(
        "forage.trail_sense_distance",
        "Trail sense dist",
        5.0,
        80.0,
        1.0,
        section="Forage",
        help=(
            "How far ahead (world units) antenna samples look for trail. "
            "Larger = sense trails farther away."
        ),
    ),
    SliderDef(
        "forage.food_sense_distance",
        "Food sense dist",
        5.0,
        120.0,
        1.0,
        section="Forage",
        help=(
            "How far antennae can detect prey (from the food surface, world units). "
            "Larger = ants home in on food from farther away."
        ),
    ),
    SliderDef(
        "forage.food_seek_weight",
        "Food seek weight",
        0.0,
        6.0,
        0.05,
        section="Forage",
        help=(
            "How strongly ants steer toward food once antennae sense it. "
            "Higher = turn harder toward prey."
        ),
    ),
    SliderDef(
        "forage.pickup_amount",
        "Pickup amount",
        0.5,
        30.0,
        0.5,
        section="Forage",
        help="Food taken from a patch in one pickup. Higher = fewer trips needed.",
    ),
    SliderDef(
        "forage.unload_radius",
        "Home tile radius",
        4.0,
        40.0,
        0.5,
        section="Forage",
        help=(
            "How close an ant must be to the single home drop-off point to unload. "
            "Larger = easier delivery."
        ),
    ),
    SliderDef(
        "forage.min_search_range",
        "Min search range",
        40.0,
        600.0,
        5.0,
        section="Forage",
        help=(
            "Scout radius at the start of an outbound trip. Grows toward max "
            "while the ant finds no food."
        ),
    ),
    SliderDef(
        "forage.max_search_range",
        "Max search range",
        100.0,
        2000.0,
        10.0,
        section="Forage",
        help=(
            "Cap scout radius after a long fruitless search. Beyond this from "
            "the entrance the ant turns home."
        ),
    ),
    SliderDef(
        "forage.search_range_grow_time",
        "Search grow time",
        5.0,
        120.0,
        1.0,
        section="Forage",
        help=(
            "Seconds of outbound searching (no food) to grow range from min to max. "
            "Longer = expand the forage radius more slowly."
        ),
    ),
    SliderDef(
        "forage.carry_speed_scale",
        "Carry speed scale",
        0.3,
        1.0,
        0.01,
        section="Forage",
        help="Speed multiplier while carrying food (e.g. 0.82 = 18% slower).",
    ),
    # --- Haul (must stay one contiguous block — section name is unique) ---
    SliderDef(
        "forage.solo_haul_speed_percent",
        "Solo haul max %",
        1.0,
        100.0,
        1.0,
        section="Haul",
        help=(
            "Solo ant carrying a piece: never faster than this percent of base speed "
            "(1–100). Weight formula can only make it slower."
        ),
    ),
    SliderDef(
        "forage.multi_haul_speed_scale",
        "Multi haul cap",
        0.05,
        1.0,
        0.01,
        section="Haul",
        help=(
            "With 2+ ants on a piece: hard speed cap as a fraction of base speed "
            "(0.55 = 55% max even if mass allows faster)."
        ),
    ),
    SliderDef(
        "forage.food_mass_scale",
        "Food mass scale",
        0.2,
        4.0,
        0.05,
        section="Haul",
        help=(
            "Multiplies every part's haul weight. Raise to make all loads heavier / slower "
            "without editing per-part tables."
        ),
    ),
    SliderDef(
        "forage.ant_mass",
        "Ant haul mass",
        0.2,
        4.0,
        0.05,
        section="Haul",
        help="Mass unit per ant (× strength). Higher = ants pull heavy pieces faster.",
    ),
    SliderDef(
        "forage.haul_gain",
        "Haul gain",
        0.2,
        2.0,
        0.05,
        section="Haul",
        help="Overall speed multiplier after the mass formula. 1 = default.",
    ),
    SliderDef(
        "forage.cargo_path_min_weight",
        "Cargo path min weight",
        0.5,
        20.0,
        0.25,
        section="Haul",
        help=(
            "Parts at or above this weight approach via the wide cargo entrance. "
            "Lower = more pieces use cargo; higher = only the heaviest."
        ),
    ),
    SliderDef(
        "forage.haul_stuck_time",
        "Detour after stuck (s)",
        0.3,
        6.0,
        0.1,
        section="Haul",
        help=(
            "Seconds of failed personal pull before the ant tries a ±90° detour "
            "around the wall."
        ),
    ),
    SliderDef(
        "forage.haul_give_up_time",
        "Give up no progress (s)",
        1.0,
        30.0,
        0.5,
        section="Haul",
        help=(
            "If the load is not getting closer to the nest for this many seconds, "
            "the ant drops it and starts grip cooldown."
        ),
    ),
    SliderDef(
        "forage.haul_give_up_detours",
        "Give up after detours",
        1,
        10,
        1,
        is_int=True,
        section="Haul",
        help=(
            "Failed ±90° detours without homeward progress before releasing the piece."
        ),
    ),
    SliderDef(
        "forage.haul_grip_cooldown",
        "Re-grip cooldown (s)",
        0.0,
        30.0,
        0.5,
        section="Haul",
        help=(
            "After dropping a piece (give-up), this ant cannot grip loose food again "
            "for this many seconds. Others still can."
        ),
    ),
    SliderDef(
        "forage.haul_progress_eps",
        "Progress epsilon",
        1.0,
        20.0,
        0.5,
        section="Haul",
        help=(
            "World units closer to the nest goal that count as real progress "
            "(resets the give-up timer)."
        ),
    ),
    SliderDef(
        "forage.haul_group_jam_time",
        "Group jam time (s)",
        0.5,
        8.0,
        0.1,
        section="Haul",
        help=(
            "Seconds of almost no movement for a multi-haul before all carriers "
            "share one wall-follow unstick direction."
        ),
    ),
    SliderDef(
        "forage.haul_wall_crawl_frac",
        "Wall crawl floor",
        0.02,
        0.4,
        0.01,
        section="Haul",
        help=(
            "Minimum speed as a fraction of base when sliding along walls. "
            "Keeps heavy pieces creeping around corners."
        ),
    ),
    SliderDef(
        "forage.max_carriers_per_part",
        "Max carriers / part",
        1,
        8,
        1,
        is_int=True,
        section="Haul",
        help="Maximum ants that can lock onto one food piece at once.",
    ),
    # --- Behaviour (real L. niger rules) ---
    SliderDef(
        "forage.deposit_near_food",
        "Deposit near food",
        0.2,
        8.0,
        0.05,
        section="Behaviour",
        help=(
            "Trail-mark multiplier at the prey. L. niger lays far more pheromone "
            "near food than near the nest (Czaczkes 2024)."
        ),
    ),
    SliderDef(
        "forage.deposit_near_nest",
        "Deposit near nest",
        0.05,
        2.0,
        0.05,
        section="Behaviour",
        help="Trail-mark multiplier as a returning ant approaches the nest.",
    ),
    SliderDef(
        "forage.deposit_distance_scale",
        "Deposit × distance",
        0.0,
        0.006,
        0.0001,
        section="Behaviour",
        help=(
            "Extra deposit per world-unit of the outbound trip. Farther food "
            "gets a stronger trail (Devigne & Detrain / Czaczkes)."
        ),
    ),
    SliderDef(
        "forage.deposit_trail_suppress",
        "Trail suppress",
        0.0,
        0.12,
        0.002,
        section="Behaviour",
        help=(
            "How much an already-strong trail reduces further laying: "
            "1 / (1 + k × local). Conserves pheromone on busy paths."
        ),
    ),
    SliderDef(
        "forage.crowd_avoid_count",
        "Crowd avoid count",
        1,
        20,
        1,
        is_int=True,
        section="Behaviour",
        help=(
            "Outbound ants down-weight a feeder once this many nestmates "
            "are already on it (Wendt / Czaczkes crowding)."
        ),
    ),
    SliderDef(
        "forage.crowd_butcher_max",
        "Butcher crowd max",
        2,
        20,
        1,
        is_int=True,
        section="Behaviour",
        help="Extra ants start peeling off a carcass above this occupancy.",
    ),
    SliderDef(
        "forage.uturn_rate",
        "U-turn rate (/s)",
        0.0,
        2.0,
        0.05,
        section="Behaviour",
        help=(
            "Beckers U-turns: chance per second to reverse while the trail "
            "fades ahead. Helps colonies abandon weak / wrong branches."
        ),
    ),
    SliderDef(
        "forage.ars_duration",
        "Local search (s)",
        0.0,
        20.0,
        0.5,
        section="Behaviour",
        help=(
            "Seconds of looping search after losing a trail or dropping prey "
            "(area-restricted search)."
        ),
    ),
    SliderDef(
        "forage.energy_forage_drain",
        "Forage energy drain",
        0.0,
        0.05,
        0.001,
        section="Behaviour",
        help="Energy lost per second while exploring / outbound. 0 = ignore satiety.",
    ),
    SliderDef(
        "forage.nest_mill_speed",
        "Nest mill speed",
        0.0,
        0.8,
        0.02,
        section="Behaviour",
        help="Idle nest speed as a fraction of walk speed. 0 = freeze in nest.",
    ),
    SliderDef(
        "forage.antennation_radius",
        "Antennation radius",
        0.0,
        30.0,
        0.5,
        section="Behaviour",
        help=(
            "Contact range: meeting a loaded returning nestmate turns an "
            "explorer onto the outbound path."
        ),
    ),
    # --- Ants ---
    SliderDef(
        "ants.speed",
        "Ant speed",
        10.0,
        200.0,
        1.0,
        section="Ants",
        help="Base movement speed in world units per second (before carry slowdown).",
    ),
    SliderDef(
        "ants.radius",
        "Ant radius",
        1.0,
        12.0,
        0.25,
        section="Ants",
        help="Collision body radius. Larger ants bounce off walls sooner.",
    ),
    SliderDef(
        "ants.sprite_world_height",
        "Sprite body size",
        4.0,
        40.0,
        0.5,
        section="Ants",
        help="Drawn ant sprite height in world units. Visual only (not collision).",
    ),
    SliderDef(
        "ants.sprite_stride",
        "Walk cycle length",
        2.0,
        40.0,
        0.5,
        section="Ants",
        help=(
            "World distance walked per full sprite walk-cycle. Smaller = faster "
            "looking leg animation."
        ),
    ),
    SliderDef(
        "ants.use_sprites",
        "Use sprites (0/1)",
        0,
        1,
        1,
        is_int=True,
        section="Ants",
        help="1 = draw walking-ant sprites; 0 = simple coloured dots.",
    ),
    SliderDef(
        "ants.pheromone_ignore_below_fraction",
        "Ignore trail below (×base)",
        0.0,
        1.0,
        0.05,
        section="Ants",
        help=(
            "If trail strength ≤ this × deposit base, ants may ignore it. Chance = "
            "1 − strength/base (e.g. base 20, at 10 → 50% ignore)."
        ),
    ),
    SliderDef(
        "locomotion.turn_noise_sigma",
        "Turn noise",
        0.0,
        1.0,
        0.01,
        section="Ants",
        help="Random heading jitter. Higher = more wandering / less straight walks.",
    ),
    SliderDef(
        "locomotion.max_turn_rate",
        "Max turn rate",
        0.5,
        10.0,
        0.1,
        section="Ants",
        help="Maximum turn speed (rad/s). Lower = wider, slower curves.",
    ),
    SliderDef(
        "locomotion.meander_amplitude",
        "Meander amp",
        0.0,
        1.5,
        0.02,
        section="Ants",
        help="Side-to-side meander while walking. Higher = wobblier paths.",
    ),
    SliderDef(
        "locomotion.separation_weight",
        "Separation weight",
        0.0,
        3.0,
        0.05,
        section="Ants",
        help="How strongly ants steer away from nearby nestmates to avoid clumping.",
    ),
    # --- Camera ---
    SliderDef(
        "camera.pan_speed",
        "Pan speed",
        50.0,
        3000.0,
        10.0,
        section="Camera",
        help="WASD / arrow pan speed in world units per second.",
    ),
    SliderDef(
        "camera.zoom_step",
        "Zoom step",
        0.02,
        0.4,
        0.01,
        section="Camera",
        help="How much each mouse-wheel notch changes zoom.",
    ),
]


def _sections_in_order() -> List[str]:
    seen: List[str] = []
    for s in SLIDERS:
        if s.section and s.section not in seen:
            seen.append(s.section)
    return seen


def _get_path(cfg: Dict[str, Any], path: str) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        cur = cur[part]
    return cur


def _set_path(cfg: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Any = cfg
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


_SLIDER_FALLBACKS: Dict[str, float] = {
    "ants.sprite_world_height": 14.0,
    "ants.sprite_stride": 10.0,
    "ants.use_sprites": 1.0,
    "pheromone.deposit_amount": 12.0,
    "pheromone.trail_evaporation": 4.0,
    "pheromone.trail_high_threshold": 40.0,
    "pheromone.trail_high_fade_rate": 0.5,
    "pheromone.nest_evaporation": 0.6,
    "pheromone.diffusion": 0.06,
    "pheromone.floor": 0.5,
    "ants.pheromone_ignore_below_fraction": 0.5,
    "forage.food_sense_distance": 48.0,
    "forage.food_seek_weight": 2.6,
    "forage.leave_nest_store_ref": 400.0,
    "forage.min_search_range": 120.0,
    "forage.search_range_grow_time": 45.0,
    "forage.solo_haul_speed_percent": 40.0,
    "forage.multi_haul_speed_scale": 0.55,
    "forage.food_mass_scale": 1.0,
    "forage.ant_mass": 1.0,
    "forage.haul_gain": 1.0,
    "forage.cargo_path_min_weight": 3.5,
    "forage.haul_stuck_time": 1.4,
    "forage.haul_give_up_time": 6.0,
    "forage.haul_give_up_detours": 3.0,
    "forage.haul_grip_cooldown": 8.0,
    "forage.haul_progress_eps": 4.0,
    "forage.haul_group_jam_time": 1.5,
    "forage.haul_wall_crawl_frac": 0.10,
    "forage.max_carriers_per_part": 4.0,
    "forage.deposit_near_food": 2.6,
    "forage.deposit_near_nest": 0.40,
    "forage.deposit_distance_scale": 0.0012,
    "forage.deposit_trail_suppress": 0.028,
    "forage.crowd_avoid_count": 6.0,
    "forage.crowd_butcher_max": 8.0,
    "forage.uturn_rate": 0.50,
    "forage.ars_duration": 6.5,
    "forage.energy_forage_drain": 0.006,
    "forage.nest_mill_speed": 0.22,
    "forage.antennation_radius": 11.0,
}


def _ensure_slider_keys(cfg: Dict[str, Any]) -> None:
    for s in SLIDERS:
        try:
            _get_path(cfg, s.path)
        except (KeyError, TypeError):
            val = _SLIDER_FALLBACKS.get(s.path, s.min_v)
            _set_path(cfg, s.path, int(val) if s.is_int else float(val))


def _wrap_text(text: str, font: pygame.font.Font, max_width: int) -> List[str]:
    """Word-wrap help text to a pixel width."""
    words = text.split()
    if not words:
        return []
    lines: List[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = cur + " " + w
        if font.size(trial)[0] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


# Short labels and colours for the per-state histogram (B1)
_STATE_LABELS: Dict[str, str] = {
    "IDLE_IN_NEST": "idle",
    "FORAGE_OUTBOUND": "out",
    "FORAGE_RETURN": "ret",
    "EXPLORE": "expl",
    "ALARM": "ALRM",
    "ASSESS_NEST": "asst",
    "RECRUIT": "rcrt",
    "BROOD_CARE": "nurs",
    "EMIGRATE": "emig",
}
_STATE_COLORS: Dict[str, Tuple[int, int, int]] = {
    "IDLE_IN_NEST": (50, 110, 65),
    "FORAGE_OUTBOUND": (200, 130, 40),
    "FORAGE_RETURN": (60, 155, 165),
    "EXPLORE": (160, 190, 55),
    "ALARM": (210, 55, 55),
    "ASSESS_NEST": (145, 80, 185),
    "RECRUIT": (200, 200, 55),
    "BROOD_CARE": (205, 100, 145),
    "EMIGRATE": (65, 205, 205),
}


class Sidebar:
    WIDTH = 300
    PAD = 10
    ROW_H = 40
    SLIDER_H = 12
    BTN_W = 22
    HEADER_H = 26
    TITLE_H = 44
    STATS_H = 88  # compact histogram + sparkline (B1/B3)
    FOOTER_H = 110  # expanded for spawn buttons (B2)
    SCROLLBAR_W = 10
    TOOLTIP_DELAY_MS = 1000
    TOOLTIP_MAX_W = 260
    TOGGLE_W = 28
    TOGGLE_H = 56

    def __init__(
        self, cfg: Dict[str, Any], save_path: Optional[Path] = None
    ) -> None:
        self.cfg = cfg
        self.save_path = save_path
        self.visible = True
        self.scroll = 0
        self.drag_index: Optional[int] = None
        self.font = pygame.font.SysFont("consolas", 13)
        self.font_sm = pygame.font.SysFont("consolas", 11)
        self.font_title = pygame.font.SysFont("consolas", 15, bold=True)
        self._hover_index: Optional[int] = None
        self._hover_since_ms: int = 0
        self._mouse_pos: Tuple[int, int] = (0, 0)
        _ensure_slider_keys(cfg)
        self._defaults: Dict[str, float] = {
            s.path: float(_get_path(cfg, s.path)) for s in SLIDERS
        }
        # section -> collapsed (True = hide sliders)
        self._collapsed: Dict[str, bool] = {sec: False for sec in _sections_in_order()}
        # Collapse everything except Haul by default (new focus params)
        for sec in self._collapsed:
            if sec not in ("Haul", "Pheromone", "Behaviour"):
                self._collapsed[sec] = True
        # Expand Haul so give-up / cooldown are visible
        if "Haul" in self._collapsed:
            self._collapsed["Haul"] = False

        self._slider_rows: Dict[int, pygame.Rect] = {}
        self._minus_rects: Dict[int, pygame.Rect] = {}
        self._plus_rects: Dict[int, pygame.Rect] = {}
        self._track_rects: Dict[int, pygame.Rect] = {}
        self._header_rects: Dict[str, pygame.Rect] = {}
        self._reset_rect = pygame.Rect(0, 0, 0, 0)
        self._save_rect = pygame.Rect(0, 0, 0, 0)
        self._toggle_rect = pygame.Rect(0, 0, 0, 0)
        self._scrollbar_rect = pygame.Rect(0, 0, 0, 0)
        self._scroll_thumb_rect = pygame.Rect(0, 0, 0, 0)
        self._scroll_drag = False
        self._scroll_drag_y0 = 0
        self._scroll_drag_s0 = 0
        self._status = ""
        self._status_until = 0
        self._hold_index: Optional[int] = None
        self._hold_dir: int = 0
        self._hold_start_ms: int = 0
        self._hold_next_ms: int = 0
        self._on_change: Optional[Callable[[], None]] = None
        # B1/B3: live colony stats
        self._state_counts: Dict[str, int] = {}
        self._food_store: float = 0.0
        self._food_history: List[float] = []  # ring buffer, max 120 samples
        self._food_history_maxlen: int = 120
        # B2: spawn pending delta (positive = add, negative = remove)
        self._pending_spawn: int = 0
        self._spawn_p_rect = pygame.Rect(0, 0, 0, 0)
        self._spawn_m_rect = pygame.Rect(0, 0, 0, 0)

    # ------------------------------------------------------------------
    # B1/B2/B3 — live stats API called from main loop each frame
    # ------------------------------------------------------------------

    def update_stats(self, colony: object) -> None:
        """Snapshot colony state for histogram and sparkline (call before draw)."""
        if colony is None:
            return
        self._state_counts = colony.count_by_state()  # type: ignore[attr-defined]
        self._food_store = float(getattr(colony, "food_store", 0.0))
        self._food_history.append(self._food_store)
        if len(self._food_history) > self._food_history_maxlen:
            self._food_history = self._food_history[-self._food_history_maxlen:]

    def consume_spawn(self) -> int:
        """Return pending spawn delta (pos=add, neg=remove) and clear it."""
        n, self._pending_spawn = self._pending_spawn, 0
        return n

    def _draw_stats(self, screen: pygame.Surface, panel: pygame.Rect) -> None:
        """Histogram + sparkline drawn in the fixed stats strip (B1/B3)."""
        sx = panel.x + self.PAD
        sy = panel.y + self.PAD + self.TITLE_H + 2
        sw = panel.w - 2 * self.PAD
        label_w = 28
        num_w = 22
        bar_w = sw - label_w - num_w - 4
        bar_h = 11
        bar_gap = 2

        total = max(1, sum(self._state_counts.values()))
        y = sy
        # Show states with non-zero count, sorted by count descending (most first)
        for state, count in sorted(self._state_counts.items(), key=lambda x: -x[1]):
            if count == 0:
                continue
            if y + bar_h > panel.y + self.PAD + self.TITLE_H + self.STATS_H - 20:
                break  # leave room for sparkline
            col = _STATE_COLORS.get(state, (100, 100, 100))
            lab = self.font_sm.render(
                _STATE_LABELS.get(state, state[:4]), True, (165, 170, 158)
            )
            screen.blit(lab, (sx, y + 1))
            frac = count / total
            bg = pygame.Rect(sx + label_w, y, bar_w, bar_h)
            fill = pygame.Rect(sx + label_w, y, max(2, int(bar_w * frac)), bar_h)
            pygame.draw.rect(screen, (28, 33, 28), bg, border_radius=2)
            pygame.draw.rect(screen, col, fill, border_radius=2)
            num = self.font_sm.render(str(count), True, (185, 195, 175))
            screen.blit(num, (sx + label_w + bar_w + 3, y + 1))
            y += bar_h + bar_gap

        # Food store sparkline (B3)
        spark_y = panel.y + self.PAD + self.TITLE_H + self.STATS_H - 18
        store_s = f"food:{self._food_store:.0f}"
        store_surf = self.font_sm.render(store_s, True, (155, 185, 140))
        screen.blit(store_surf, (sx, spark_y + 2))
        spark_x = sx + 50
        spark_w = sw - 52
        spark_h = 14
        pygame.draw.rect(
            screen, (22, 28, 22), pygame.Rect(spark_x, spark_y, spark_w, spark_h)
        )
        hist = self._food_history
        if len(hist) >= 2:
            max_v = max(max(hist), 1.0)
            for i in range(1, len(hist)):
                x1 = spark_x + int((i - 1) * spark_w / max(len(hist) - 1, 1))
                x2 = spark_x + int(i * spark_w / max(len(hist) - 1, 1))
                y1p = spark_y + spark_h - 1 - int(hist[i - 1] / max_v * (spark_h - 2))
                y2p = spark_y + spark_h - 1 - int(hist[i] / max_v * (spark_h - 2))
                pygame.draw.line(screen, (75, 155, 75), (x1, y1p), (x2, y2p))

    def panel_rect(self, screen: pygame.Surface) -> pygame.Rect:
        sw, sh = screen.get_size()
        return pygame.Rect(sw - self.WIDTH, 0, self.WIDTH, sh)

    def toggle_rect(self, screen: pygame.Surface) -> pygame.Rect:
        """Always-visible strip to show/hide the panel."""
        sw, sh = screen.get_size()
        if self.visible:
            # On the left edge of the open panel
            return pygame.Rect(
                sw - self.WIDTH - self.TOGGLE_W,
                max(8, sh // 2 - self.TOGGLE_H // 2),
                self.TOGGLE_W,
                self.TOGGLE_H,
            )
        # Collapsed tab on the right edge
        return pygame.Rect(
            sw - self.TOGGLE_W,
            max(8, sh // 2 - self.TOGGLE_H // 2),
            self.TOGGLE_W,
            self.TOGGLE_H,
        )

    def contains_screen_pos(self, screen: pygame.Surface, pos: Tuple[int, int]) -> bool:
        if self.toggle_rect(screen).collidepoint(pos):
            return True
        if not self.visible:
            return False
        return self.panel_rect(screen).collidepoint(pos)

    def _section_expanded(self, section: str) -> bool:
        return not self._collapsed.get(section, False)

    def _scroll_content_height(self) -> int:
        """Height of scrollable slider/header block only (not title/footer)."""
        h = 0
        last_sec = None
        for s in SLIDERS:
            if s.section != last_sec:
                h += self.HEADER_H
                last_sec = s.section
            if self._section_expanded(s.section):
                h += self.ROW_H
        return h

    def _content_view_rect(self, panel: pygame.Rect) -> pygame.Rect:
        top = panel.y + self.PAD + self.TITLE_H + self.STATS_H
        bottom = panel.bottom - self.FOOTER_H
        return pygame.Rect(panel.x, top, panel.w, max(0, bottom - top))

    def _max_scroll(self, panel: pygame.Rect) -> int:
        view = self._content_view_rect(panel)
        return max(0, self._scroll_content_height() - view.height + 8)

    def _set_hover(self, idx: Optional[int]) -> None:
        if idx != self._hover_index:
            self._hover_index = idx
            self._hover_since_ms = pygame.time.get_ticks()

    def handle_event(
        self,
        event: pygame.event.Event,
        screen: pygame.Surface,
        on_change: Optional[Callable[[], None]] = None,
    ) -> bool:
        self._on_change = on_change
        mx, my = pygame.mouse.get_pos()
        self._mouse_pos = (mx, my)
        toggle = self.toggle_rect(screen)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
            self.visible = not self.visible
            if not self.visible:
                self.drag_index = None
                self._clear_hold()
                self._scroll_drag = False
            return True

        # Hide / show button (works even when panel is closed)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if toggle.collidepoint(mx, my):
                self.visible = not self.visible
                if not self.visible:
                    self.drag_index = None
                    self._clear_hold()
                    self._scroll_drag = False
                return True

        if not self.visible:
            return False

        panel = self.panel_rect(screen)
        over = panel.collidepoint(mx, my)
        view = self._content_view_rect(panel)
        max_sc = self._max_scroll(panel)
        self.scroll = int(clamp(self.scroll, 0, max_sc))

        if event.type == pygame.MOUSEWHEEL and over:
            # Wheel always scrolls the panel — values only change via −/+ or drag
            self.scroll = int(
                clamp(self.scroll - event.y * 36, 0, self._max_scroll(panel))
            )
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and over:
            # Scrollbar thumb drag
            if self._scroll_thumb_rect.width > 0 and self._scroll_thumb_rect.collidepoint(
                mx, my
            ):
                self._scroll_drag = True
                self._scroll_drag_y0 = my
                self._scroll_drag_s0 = self.scroll
                return True
            if self._scrollbar_rect.width > 0 and self._scrollbar_rect.collidepoint(
                mx, my
            ):
                # Jump scroll toward click
                view = self._content_view_rect(panel)
                if self._scrollbar_rect.h > 0:
                    t = clamp(
                        (my - self._scrollbar_rect.y) / self._scrollbar_rect.h, 0.0, 1.0
                    )
                    self.scroll = int(t * self._max_scroll(panel))
                return True

            for sec, hr in self._header_rects.items():
                if hr.collidepoint(mx, my) and view.collidepoint(mx, my):
                    self._collapsed[sec] = not self._collapsed.get(sec, False)
                    self.scroll = int(clamp(self.scroll, 0, self._max_scroll(panel)))
                    return True
            if self._save_rect.collidepoint(mx, my):
                self.save_params()
                return True
            if self._reset_rect.collidepoint(mx, my):
                self.reset_defaults()
                if on_change:
                    on_change()
                self._flash_status("Reset to run start")
                return True
            # B2: spawn +/- 5 ants buttons
            if self._spawn_p_rect.collidepoint(mx, my):
                self._pending_spawn += 5
                return True
            if self._spawn_m_rect.collidepoint(mx, my):
                self._pending_spawn -= 5
                return True
            for i, r in self._minus_rects.items():
                if r.collidepoint(mx, my) and view.collidepoint(mx, my):
                    self._nudge(i, -1, mult=1.0)
                    self._start_hold(i, -1)
                    if on_change:
                        on_change()
                    return True
            for i, r in self._plus_rects.items():
                if r.collidepoint(mx, my) and view.collidepoint(mx, my):
                    self._nudge(i, +1, mult=1.0)
                    self._start_hold(i, +1)
                    if on_change:
                        on_change()
                    return True
            for i, r in self._track_rects.items():
                if r.collidepoint(mx, my) and view.collidepoint(mx, my):
                    self.drag_index = i
                    self._set_from_mouse_x(i, mx)
                    if on_change:
                        on_change()
                    return True
            idx = self._hit_slider(mx, my)
            if idx is not None and view.collidepoint(mx, my):
                self._set_hover(idx)
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was = (
                self.drag_index is not None
                or self._hold_index is not None
                or self._scroll_drag
            )
            self.drag_index = None
            self._scroll_drag = False
            self._clear_hold()
            return was

        if event.type == pygame.MOUSEMOTION:
            self._mouse_pos = (mx, my)
            if self._scroll_drag and event.buttons[0]:
                max_sc = self._max_scroll(panel)
                track_h = max(1, self._scrollbar_rect.h - self._scroll_thumb_rect.h)
                dy = my - self._scroll_drag_y0
                if track_h > 0 and max_sc > 0:
                    self.scroll = int(
                        clamp(
                            self._scroll_drag_s0 + dy * (max_sc / track_h),
                            0,
                            max_sc,
                        )
                    )
                return True
            if over and view.collidepoint(mx, my):
                self._set_hover(self._hit_slider(mx, my))
            else:
                self._set_hover(None)
            if self.drag_index is not None and event.buttons[0]:
                self._set_from_mouse_x(self.drag_index, mx)
                if on_change:
                    on_change()
                return True
            if self._hold_index is not None and not event.buttons[0]:
                self._clear_hold()

        return False

    def update(self, on_change: Optional[Callable[[], None]] = None) -> None:
        # Keep hover index in sync even without motion events
        if self.visible:
            mx, my = pygame.mouse.get_pos()
            self._mouse_pos = (mx, my)
            panel_guess = None  # hit uses last drawn rects
            if self._slider_rows:
                self._set_hover(self._hit_slider(mx, my))

        if self._hold_index is None or self._hold_dir == 0:
            return
        if not pygame.mouse.get_pressed()[0]:
            self._clear_hold()
            return
        now = pygame.time.get_ticks()
        if now < self._hold_next_ms:
            return
        elapsed = (now - self._hold_start_ms) / 1000.0
        mult, interval_ms = self._hold_accel(elapsed)
        self._nudge(self._hold_index, self._hold_dir, mult=mult)
        self._hold_next_ms = now + interval_ms
        cb = on_change or self._on_change
        if cb:
            cb()

    def _start_hold(self, idx: int, direction: int) -> None:
        now = pygame.time.get_ticks()
        self._hold_index = idx
        self._hold_dir = direction
        self._hold_start_ms = now
        self._hold_next_ms = now + 350

    def _clear_hold(self) -> None:
        self._hold_index = None
        self._hold_dir = 0
        self._hold_next_ms = 0

    @staticmethod
    def _hold_accel(elapsed_s: float) -> Tuple[float, int]:
        if elapsed_s < 0.8:
            return 1.0, 120
        if elapsed_s < 1.6:
            return 1.0, 60
        if elapsed_s < 2.5:
            return 2.0, 40
        if elapsed_s < 4.0:
            return 5.0, 30
        return 10.0, 20

    def _nudge(self, idx: int, direction: int, mult: float = 1.0) -> None:
        s = SLIDERS[idx]
        cur = float(_get_path(self.cfg, s.path))
        delta = s.step * direction * mult
        cur = clamp(cur + delta, s.min_v, s.max_v)
        if s.is_int:
            cur = float(int(round(cur)))
        else:
            if s.step > 0:
                cur = round(cur / s.step) * s.step
                cur = clamp(cur, s.min_v, s.max_v)
        _set_path(self.cfg, s.path, int(cur) if s.is_int else float(cur))

    def reset_defaults(self) -> None:
        for s in SLIDERS:
            v = self._defaults[s.path]
            _set_path(self.cfg, s.path, int(round(v)) if s.is_int else v)

    def save_params(self) -> None:
        if self.save_path is None:
            self._flash_status("No save path")
            return
        data: Dict[str, Any] = {}
        for s in SLIDERS:
            val = _get_path(self.cfg, s.path)
            if s.is_int:
                val = int(round(float(val)))
            else:
                val = float(val)
            _set_path(data, s.path, val)
        try:
            save_yaml(self.save_path, data)
            self._flash_status(f"Saved → {self.save_path.name}")
        except Exception as exc:  # noqa: BLE001
            self._flash_status(f"Save failed: {exc}")

    def _flash_status(self, msg: str, ms: int = 2500) -> None:
        self._status = msg
        self._status_until = pygame.time.get_ticks() + ms

    def _set_from_mouse_x(self, idx: int, mx: int) -> None:
        s = SLIDERS[idx]
        track = self._track_rects.get(idx)
        if track is None:
            return
        t = 0.0 if track.w <= 0 else clamp((mx - track.x) / track.w, 0.0, 1.0)
        val = s.min_v + t * (s.max_v - s.min_v)
        if s.step > 0:
            val = round(val / s.step) * s.step
        val = clamp(val, s.min_v, s.max_v)
        _set_path(self.cfg, s.path, int(round(val)) if s.is_int else float(val))

    def _hit_slider(self, mx: int, my: int) -> Optional[int]:
        for i, r in self._slider_rows.items():
            if r.collidepoint(mx, my):
                return i
        return None

    def _draw_toggle(self, screen: pygame.Surface) -> None:
        r = self.toggle_rect(screen)
        self._toggle_rect = r
        bg = (45, 70, 50) if self.visible else (50, 55, 48)
        border = (120, 180, 120) if self.visible else (140, 150, 120)
        pygame.draw.rect(screen, bg, r, border_radius=4)
        pygame.draw.rect(screen, border, r, 2, border_radius=4)
        label = "«" if self.visible else "»"
        # Vertical hint
        t1 = self.font.render(label, True, (220, 240, 210))
        t2 = self.font_sm.render("cfg", True, (180, 200, 170))
        screen.blit(t1, (r.centerx - t1.get_width() // 2, r.y + 8))
        screen.blit(t2, (r.centerx - t2.get_width() // 2, r.centery - 2))
        tip = "Hide" if self.visible else "Show"
        t3 = self.font_sm.render(tip, True, (160, 180, 150))
        screen.blit(t3, (r.centerx - t3.get_width() // 2, r.bottom - 16))

    def draw(self, screen: pygame.Surface) -> None:
        self._draw_toggle(screen)

        if not self.visible:
            self._slider_rows.clear()
            self._minus_rects.clear()
            self._plus_rects.clear()
            self._track_rects.clear()
            self._header_rects.clear()
            self._scrollbar_rect = pygame.Rect(0, 0, 0, 0)
            self._scroll_thumb_rect = pygame.Rect(0, 0, 0, 0)
            return

        panel = self.panel_rect(screen)
        overlay = pygame.Surface((panel.w, panel.h), pygame.SRCALPHA)
        overlay.fill((18, 20, 22, 235))
        screen.blit(overlay, panel.topleft)
        pygame.draw.line(
            screen, (70, 90, 70), (panel.x, 0), (panel.x, panel.bottom), 2
        )

        # --- Fixed title ---
        y_title = panel.y + self.PAD
        title = self.font_title.render("Live config", True, (230, 230, 210))
        screen.blit(title, (panel.x + self.PAD, y_title + 2))
        hint = self.font_sm.render(
            "scroll · hover help · Tab", True, (130, 135, 120)
        )
        screen.blit(hint, (panel.x + self.PAD, y_title + 22))

        # --- Fixed stats strip (B1/B3) ---
        self._draw_stats(screen, panel)

        view = self._content_view_rect(panel)
        max_sc = self._max_scroll(panel)
        self.scroll = int(clamp(self.scroll, 0, max_sc))

        # --- Scrollable content (clipped) ---
        prev_clip = screen.get_clip()
        screen.set_clip(view)

        y = view.y - self.scroll
        self._slider_rows = {}
        self._minus_rects = {}
        self._plus_rects = {}
        self._track_rects = {}
        self._header_rects = {}
        last_sec = None
        content_right_pad = self.PAD + (
            self.SCROLLBAR_W + 4 if max_sc > 0 else 0
        )
        for i, s in enumerate(SLIDERS):
            if s.section != last_sec:
                collapsed = self._collapsed.get(s.section, False)
                marker = "▶" if collapsed else "▼"
                header = pygame.Rect(
                    panel.x + self.PAD,
                    y,
                    panel.w - self.PAD - content_right_pad,
                    self.HEADER_H,
                )
                self._header_rects[s.section] = header
                if header.bottom > view.y and header.top < view.bottom:
                    pygame.draw.rect(
                        screen, (32, 42, 34), header.inflate(0, -4), border_radius=3
                    )
                    sec = self.font.render(
                        f"{marker} {s.section}", True, (160, 190, 140)
                    )
                    screen.blit(sec, (header.x + 4, header.y + 4))
                y += self.HEADER_H
                last_sec = s.section

            if not self._section_expanded(s.section):
                continue

            row = pygame.Rect(
                panel.x + self.PAD,
                y,
                panel.w - self.PAD - content_right_pad,
                self.ROW_H,
            )
            self._slider_rows[i] = row
            if row.bottom > view.y and row.top < view.bottom:
                self._draw_slider(
                    screen,
                    row,
                    i,
                    i == self._hover_index
                    or i == self.drag_index
                    or i == self._hold_index,
                )
            y += self.ROW_H

        screen.set_clip(prev_clip)

        # --- Scrollbar ---
        self._scrollbar_rect = pygame.Rect(0, 0, 0, 0)
        self._scroll_thumb_rect = pygame.Rect(0, 0, 0, 0)
        if max_sc > 0 and view.h > 20:
            track = pygame.Rect(
                panel.right - self.PAD - self.SCROLLBAR_W,
                view.y + 2,
                self.SCROLLBAR_W,
                view.h - 4,
            )
            self._scrollbar_rect = track
            pygame.draw.rect(screen, (30, 35, 32), track, border_radius=3)
            content_h = max(1, self._scroll_content_height())
            thumb_h = max(24, int(track.h * (view.h / content_h)))
            thumb_h = min(thumb_h, track.h)
            travel = max(1, track.h - thumb_h)
            thumb_y = track.y + int((self.scroll / max_sc) * travel) if max_sc else track.y
            thumb = pygame.Rect(track.x, thumb_y, track.w, thumb_h)
            self._scroll_thumb_rect = thumb
            pygame.draw.rect(screen, (90, 120, 90), thumb, border_radius=3)
            pygame.draw.rect(screen, (130, 170, 120), thumb, 1, border_radius=3)

        # --- Fixed footer ---
        btn_w = (panel.w - 2 * self.PAD - 8) // 2
        by_spawn = panel.bottom - self.FOOTER_H + 8      # spawn buttons row (B2)
        by = panel.bottom - self.FOOTER_H + 46           # save/reset row
        # Spawn +5 / -5 ant buttons (B2)
        self._spawn_p_rect = pygame.Rect(panel.x + self.PAD, by_spawn, btn_w, 28)
        self._spawn_m_rect = pygame.Rect(
            panel.x + self.PAD + btn_w + 8, by_spawn, btn_w, 28
        )
        pygame.draw.rect(screen, (35, 62, 45), self._spawn_p_rect, border_radius=4)
        pygame.draw.rect(screen, (80, 155, 90), self._spawn_p_rect, 1, border_radius=4)
        lsp = self.font.render("+5 ants", True, (200, 240, 200))
        screen.blit(lsp, (self._spawn_p_rect.centerx - lsp.get_width() // 2,
                          self._spawn_p_rect.centery - lsp.get_height() // 2))
        pygame.draw.rect(screen, (55, 35, 35), self._spawn_m_rect, border_radius=4)
        pygame.draw.rect(screen, (140, 80, 70), self._spawn_m_rect, 1, border_radius=4)
        lsm = self.font.render("-5 ants", True, (240, 190, 180))
        screen.blit(lsm, (self._spawn_m_rect.centerx - lsm.get_width() // 2,
                          self._spawn_m_rect.centery - lsm.get_height() // 2))
        # Save / Reset buttons
        self._save_rect = pygame.Rect(panel.x + self.PAD, by, btn_w, 28)
        self._reset_rect = pygame.Rect(
            panel.x + self.PAD + btn_w + 8, by, btn_w, 28
        )
        pygame.draw.rect(screen, (40, 70, 50), self._save_rect, border_radius=4)
        pygame.draw.rect(
            screen, (100, 170, 110), self._save_rect, 1, border_radius=4
        )
        lab = self.font.render("Save", True, (200, 240, 200))
        screen.blit(
            lab,
            (
                self._save_rect.centerx - lab.get_width() // 2,
                self._save_rect.centery - lab.get_height() // 2,
            ),
        )
        pygame.draw.rect(screen, (45, 55, 45), self._reset_rect, border_radius=4)
        pygame.draw.rect(
            screen, (100, 120, 90), self._reset_rect, 1, border_radius=4
        )
        lab2 = self.font.render("Reset", True, (210, 220, 190))
        screen.blit(
            lab2,
            (
                self._reset_rect.centerx - lab2.get_width() // 2,
                self._reset_rect.centery - lab2.get_height() // 2,
            ),
        )

        if self._status and pygame.time.get_ticks() < self._status_until:
            st = self.font_sm.render(self._status, True, (160, 200, 150))
            screen.blit(st, (panel.x + self.PAD, by + 34))
        elif self.save_path is not None:
            tip = self.font_sm.render(
                f"Save → {self.save_path.name} · Tab hide",
                True,
                (100, 110, 100),
            )
            screen.blit(tip, (panel.x + self.PAD, by + 34))

        self._draw_tooltip(screen, panel)

    def _draw_tooltip(self, screen: pygame.Surface, panel: pygame.Rect) -> None:
        idx = self._hover_index
        if idx is None or idx < 0 or idx >= len(SLIDERS):
            return
        now = pygame.time.get_ticks()
        if now - self._hover_since_ms < self.TOOLTIP_DELAY_MS:
            return
        s = SLIDERS[idx]
        text = s.help.strip() if s.help else f"Config path: {s.path}"
        if not text:
            return

        pad = 8
        max_w = self.TOOLTIP_MAX_W
        lines = _wrap_text(text, self.font_sm, max_w - 2 * pad)
        # Title line with parameter name
        title = s.label
        line_h = self.font_sm.get_height() + 2
        title_h = self.font.get_height() + 4
        box_w = max_w
        box_h = pad * 2 + title_h + line_h * len(lines)

        mx, my = self._mouse_pos
        # Prefer left of cursor (into the game view); keep on screen
        tx = mx - box_w - 12
        ty = my - 8
        if tx < 4:
            tx = min(mx + 16, screen.get_width() - box_w - 4)
        if ty < 4:
            ty = 4
        if ty + box_h > screen.get_height() - 4:
            ty = screen.get_height() - box_h - 4

        box = pygame.Rect(tx, ty, box_w, box_h)
        surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        surf.fill((24, 28, 26, 240))
        screen.blit(surf, box.topleft)
        pygame.draw.rect(screen, (120, 160, 110), box, 1, border_radius=4)

        screen.blit(
            self.font.render(title, True, (200, 230, 180)),
            (box.x + pad, box.y + pad),
        )
        yy = box.y + pad + title_h
        for line in lines:
            screen.blit(
                self.font_sm.render(line, True, (210, 210, 200)),
                (box.x + pad, yy),
            )
            yy += line_h

    def _draw_slider(
        self, screen: pygame.Surface, row: pygame.Rect, idx: int, highlight: bool
    ) -> None:
        s = SLIDERS[idx]
        try:
            val = float(_get_path(self.cfg, s.path))
        except Exception:
            val = s.min_v

        if s.is_int:
            val_s = str(int(round(val)))
        elif abs(val) >= 100:
            val_s = f"{val:.1f}"
        elif abs(val) >= 10:
            val_s = f"{val:.2f}"
        else:
            val_s = f"{val:.3f}".rstrip("0").rstrip(".")

        label_col = (230, 230, 210) if highlight else (190, 190, 175)
        lab = self.font_sm.render(s.label, True, label_col)
        num = self.font_sm.render(val_s, True, (180, 210, 150))
        screen.blit(lab, (row.x, row.y + 1))
        screen.blit(num, (row.right - num.get_width(), row.y + 1))

        bw = self.BTN_W
        gap = 4
        by = row.y + 18
        bh = self.SLIDER_H + 6
        minus = pygame.Rect(row.x, by, bw, bh)
        plus = pygame.Rect(row.right - bw, by, bw, bh)
        track = pygame.Rect(
            minus.right + gap,
            by + 2,
            plus.left - gap - (minus.right + gap),
            self.SLIDER_H,
        )
        self._minus_rects[idx] = minus
        self._plus_rects[idx] = plus
        self._track_rects[idx] = track

        holding_m = self._hold_index == idx and self._hold_dir < 0
        holding_p = self._hold_index == idx and self._hold_dir > 0
        self._draw_step_btn(screen, minus, "−", holding_m)
        self._draw_step_btn(screen, plus, "+", holding_p)

        pygame.draw.rect(screen, (40, 45, 40), track, border_radius=3)
        t = 0.0 if s.max_v <= s.min_v else (val - s.min_v) / (s.max_v - s.min_v)
        t = clamp(t, 0.0, 1.0)
        fill_w = max(2, int(track.w * t))
        col = (90, 150, 80) if highlight else (70, 110, 65)
        pygame.draw.rect(
            screen, col, pygame.Rect(track.x, track.y, fill_w, track.h), border_radius=3
        )
        pygame.draw.circle(screen, (220, 230, 200), (track.x + fill_w, track.centery), 5)
        pygame.draw.circle(screen, (40, 50, 40), (track.x + fill_w, track.centery), 5, 1)

    def _draw_step_btn(
        self, screen: pygame.Surface, rect: pygame.Rect, label: str, held: bool
    ) -> None:
        bg = (70, 100, 60) if held else (45, 55, 45)
        border = (140, 190, 120) if held else (90, 110, 90)
        pygame.draw.rect(screen, bg, rect, border_radius=3)
        pygame.draw.rect(screen, border, rect, 1, border_radius=3)
        lab = self.font.render(label, True, (230, 240, 220))
        screen.blit(
            lab,
            (
                rect.centerx - lab.get_width() // 2,
                rect.centery - lab.get_height() // 2,
            ),
        )


def apply_camera_from_cfg(cfg: Dict[str, Any], camera: Any) -> None:
    ccfg = cfg.get("camera", {})
    if hasattr(camera, "pan_speed"):
        camera.pan_speed = float(ccfg.get("pan_speed", camera.pan_speed))
    if hasattr(camera, "zoom_step"):
        camera.zoom_step = float(ccfg.get("zoom_step", camera.zoom_step))

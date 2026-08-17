"""
Bottom toolbar: pick a prey type, then click the map to drop it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pygame

from src.sim.food import resolve_food_types


# (kind_id, short label for button)
_DEFAULT_ITEMS: List[Tuple[str, str]] = [
    ("fruit_fly", "Fruit fly"),
    ("dung_fly", "Fat fly"),
    ("cricket", "Cricket"),
]


class FoodBar:
    """Compact strip along the bottom of the screen."""

    HEIGHT = 52
    PAD = 8
    BTN_H = 36
    BTN_MIN_W = 88
    GAP = 6
    DEFAULT_ADD_ANTS = 5

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg
        self.visible = True
        self.selected: Optional[str] = None  # kind id, or None = pan only
        self._items: List[Tuple[str, str]] = list(_DEFAULT_ITEMS)
        self._sync_items_from_cfg()
        self._btn_rects: Dict[str, pygame.Rect] = {}
        self._cancel_rect = pygame.Rect(0, 0, 0, 0)
        self._add_ants_rect = pygame.Rect(0, 0, 0, 0)
        self._bar_rect = pygame.Rect(0, 0, 0, 0)
        self._fonts_ready = False
        self.font: Optional[pygame.font.Font] = None
        self.font_sm: Optional[pygame.font.Font] = None
        # Place-vs-pan: track press so a drag still pans
        self.press_pos: Optional[Tuple[int, int]] = None
        self.dragging = False
        self.drag_threshold = 7
        # Set by handle_event when user clicks +Ants (consumed by main)
        self.pending_add_ants: int = 0
        self.add_ants_batch = int(
            cfg.get("ants", {}).get("add_batch", self.DEFAULT_ADD_ANTS)
        )

    def _sync_items_from_cfg(self) -> None:
        types = resolve_food_types(self.cfg)
        items: List[Tuple[str, str]] = []
        for kind, label in _DEFAULT_ITEMS:
            if kind in types:
                items.append((kind, str(types[kind].get("label", label))))
        # Any extra configured kinds
        for kind, td in types.items():
            if kind not in {k for k, _ in items}:
                items.append((kind, str(td.get("label", kind))))
        if items:
            self._items = items

    def _ensure_fonts(self) -> None:
        if self._fonts_ready:
            return
        self.font = pygame.font.SysFont("consolas", 15)
        self.font_sm = pygame.font.SysFont("consolas", 12)
        self._fonts_ready = True

    def bar_rect(self, screen: pygame.Surface) -> pygame.Rect:
        sw, sh = screen.get_size()
        return pygame.Rect(0, sh - self.HEIGHT, sw, self.HEIGHT)

    def contains_screen_pos(
        self, screen: pygame.Surface, pos: Tuple[int, int]
    ) -> bool:
        if not self.visible:
            return False
        return self.bar_rect(screen).collidepoint(pos)

    def handle_event(
        self, event: pygame.event.Event, screen: pygame.Surface
    ) -> bool:
        """
        Returns True if the event was consumed by the bar.
        Does not place food — only selection / cancel / add-ants.
        """
        if not self.visible:
            return False
        self._layout(screen)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._add_ants_rect.collidepoint(event.pos):
                n = max(1, int(self.add_ants_batch))
                self.pending_add_ants += n
                self.press_pos = None
                self.dragging = False
                return True
            if self._cancel_rect.collidepoint(event.pos):
                self.selected = None
                self.press_pos = None
                self.dragging = False
                return True
            for kind, rect in self._btn_rects.items():
                if rect.collidepoint(event.pos):
                    # Toggle: click again to deselect
                    self.selected = None if self.selected == kind else kind
                    self.press_pos = None
                    self.dragging = False
                    return True
            if self._bar_rect.collidepoint(event.pos):
                return True  # empty bar chrome
        return False

    def consume_add_ants(self) -> int:
        """Return and clear pending ant spawns from button clicks."""
        n = self.pending_add_ants
        self.pending_add_ants = 0
        return n

    def begin_map_press(self, pos: Tuple[int, int]) -> None:
        """Call on left-down over the world when a kind is selected."""
        self.press_pos = pos
        self.dragging = False

    def update_map_drag(self, pos: Tuple[int, int]) -> bool:
        """
        Call on motion while left held. Returns True if this became a pan drag
        (caller should let the camera pan).
        """
        if self.press_pos is None:
            return False
        dx = pos[0] - self.press_pos[0]
        dy = pos[1] - self.press_pos[1]
        if dx * dx + dy * dy >= self.drag_threshold * self.drag_threshold:
            self.dragging = True
        return self.dragging

    def end_map_press(self) -> bool:
        """
        Call on left-up. Returns True if this was a clean click to place food
        (selected kind, no drag).
        """
        place = (
            self.selected is not None
            and self.press_pos is not None
            and not self.dragging
        )
        self.press_pos = None
        self.dragging = False
        return place

    def cancel_press(self) -> None:
        self.press_pos = None
        self.dragging = False

    def _layout(self, screen: pygame.Surface) -> None:
        self._bar_rect = self.bar_rect(screen)
        y = self._bar_rect.y + (self.HEIGHT - self.BTN_H) // 2
        x = self.PAD
        self._btn_rects = {}
        for kind, _label in self._items:
            r = pygame.Rect(x, y, self.BTN_MIN_W, self.BTN_H)
            self._btn_rects[kind] = r
            x += self.BTN_MIN_W + self.GAP
        self._cancel_rect = pygame.Rect(x, y, 72, self.BTN_H)
        x = self._cancel_rect.right + self.GAP + 8
        self._add_ants_rect = pygame.Rect(x, y, 100, self.BTN_H)

    def draw(self, screen: pygame.Surface, ant_count: int = 0) -> None:
        if not self.visible:
            return
        self._ensure_fonts()
        self._layout(screen)
        bar = self._bar_rect

        overlay = pygame.Surface((bar.w, bar.h), pygame.SRCALPHA)
        overlay.fill((18, 22, 18, 210))
        screen.blit(overlay, bar.topleft)
        pygame.draw.line(
            screen, (70, 100, 70), (bar.x, bar.y), (bar.right, bar.y), 2
        )

        assert self.font is not None and self.font_sm is not None
        batch = max(1, int(self.add_ants_batch))
        hint = "Drop food: select type, click map  ·  drag pans"
        if self.selected:
            hint = f"Click map to place {self.selected.replace('_', ' ')}  ·  Esc cancel"
        tip = self.font_sm.render(hint, True, (180, 200, 170))
        screen.blit(tip, (bar.right - tip.get_width() - self.PAD, bar.y + 6))
        if ant_count > 0:
            ac = self.font_sm.render(f"ants: {ant_count}", True, (160, 190, 160))
            screen.blit(ac, (bar.right - ac.get_width() - self.PAD, bar.bottom - 16))

        for kind, label in self._items:
            rect = self._btn_rects[kind]
            selected = self.selected == kind
            bg = (55, 95, 55) if selected else (40, 48, 40)
            border = (160, 220, 120) if selected else (90, 110, 90)
            pygame.draw.rect(screen, bg, rect, border_radius=6)
            pygame.draw.rect(screen, border, rect, 2, border_radius=6)
            # Color chip by kind
            chip = _kind_color(kind)
            pygame.draw.circle(
                screen, chip, (rect.x + 14, rect.centery), 7
            )
            text = self.font.render(label, True, (230, 240, 220))
            screen.blit(
                text, (rect.x + 28, rect.centery - text.get_height() // 2)
            )

        # Cancel / pan-only
        cr = self._cancel_rect
        off = self.selected is None
        pygame.draw.rect(
            screen, (50, 50, 55) if off else (45, 42, 42), cr, border_radius=6
        )
        pygame.draw.rect(
            screen,
            (140, 140, 150) if off else (100, 90, 90),
            cr,
            2,
            border_radius=6,
        )
        ct = self.font.render("Pan", True, (220, 220, 220))
        screen.blit(
            ct, (cr.centerx - ct.get_width() // 2, cr.centery - ct.get_height() // 2)
        )

        # Add ants at home nest
        ar = self._add_ants_rect
        pygame.draw.rect(screen, (50, 70, 90), ar, border_radius=6)
        pygame.draw.rect(screen, (120, 170, 220), ar, 2, border_radius=6)
        al = self.font.render(f"+{batch} ants", True, (220, 235, 255))
        screen.blit(
            al, (ar.centerx - al.get_width() // 2, ar.centery - al.get_height() // 2)
        )


def _kind_color(kind: str) -> Tuple[int, int, int]:
    if kind == "fruit_fly":
        return (210, 170, 60)
    if kind == "dung_fly":
        return (80, 100, 160)
    if kind == "cricket":
        return (150, 110, 55)
    return (160, 160, 120)

"""2D pan/zoom camera: world <-> screen."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import pygame

from src.util.vec import Vec2, clamp


class Camera:
    def __init__(self, cfg: Dict[str, Any], screen_size: Tuple[int, int], world_size: Tuple[float, float]) -> None:
        ccfg = cfg["camera"]
        self.zoom = float(ccfg["start_zoom"])
        self.min_zoom = float(ccfg["min_zoom"])
        self.max_zoom = float(ccfg["max_zoom"])
        self.pan_speed = float(ccfg["pan_speed"])
        self.zoom_step = float(ccfg["zoom_step"])

        self.screen_w, self.screen_h = screen_size
        self.world_w, self.world_h = world_size

        # Camera center in world coordinates
        self.center = Vec2(world_size[0] * 0.35, world_size[1] * 0.5)

        # Click-drag pan (left or middle mouse)
        self._drag_pan = False
        self._drag_last: Tuple[int, int] = (0, 0)

    def set_screen_size(self, size: Tuple[int, int]) -> None:
        self.screen_w, self.screen_h = size

    def world_to_screen(self, p: Vec2) -> Tuple[float, float]:
        sx = (p.x - self.center.x) * self.zoom + self.screen_w * 0.5
        sy = (p.y - self.center.y) * self.zoom + self.screen_h * 0.5
        return sx, sy

    def screen_to_world(self, sx: float, sy: float) -> Vec2:
        x = (sx - self.screen_w * 0.5) / self.zoom + self.center.x
        y = (sy - self.screen_h * 0.5) / self.zoom + self.center.y
        return Vec2(x, y)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEWHEEL:
            # Zoom toward mouse cursor
            mx, my = pygame.mouse.get_pos()
            before = self.screen_to_world(mx, my)
            factor = 1.0 + self.zoom_step * event.y
            self.zoom = clamp(self.zoom * factor, self.min_zoom, self.max_zoom)
            after = self.screen_to_world(mx, my)
            self.center.x += before.x - after.x
            self.center.y += before.y - after.y
            return

        # Grab-map pan: drag moves the world under the cursor
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 2):
            self._drag_pan = True
            self._drag_last = event.pos
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button in (1, 2):
            self._drag_pan = False
            return
        if event.type == pygame.MOUSEMOTION and self._drag_pan:
            # Only while left or middle still held (handles lost-focus edge cases)
            buttons = getattr(event, "buttons", (0, 0, 0))
            if not (buttons[0] or buttons[1]):
                self._drag_pan = False
                return
            mx, my = event.pos
            lx, ly = self._drag_last
            dx = mx - lx
            dy = my - ly
            self._drag_last = (mx, my)
            z = max(self.zoom, 0.05)
            self.center.x -= dx / z
            self.center.y -= dy / z

    def update_keyboard_pan(self, dt: float, keys: pygame.key.ScancodeWrapper) -> None:
        move = Vec2()
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            move.x -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            move.x += 1
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            move.y -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            move.y += 1
        if move.length_sq() > 0:
            # Pan speed in screen-ish units: faster when zoomed out
            step = move.normalized() * (self.pan_speed * dt / max(self.zoom, 0.1))
            self.center = self.center + step

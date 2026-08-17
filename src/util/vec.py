"""Lightweight 2D vector helpers (no external deps beyond math)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Tuple, Union

Number = Union[int, float]


@dataclass(slots=True)
class Vec2:
    x: float = 0.0
    y: float = 0.0

    def __add__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, s: Number) -> "Vec2":
        return Vec2(self.x * s, self.y * s)

    def __rmul__(self, s: Number) -> "Vec2":
        return self.__mul__(s)

    def __truediv__(self, s: Number) -> "Vec2":
        return Vec2(self.x / s, self.y / s)

    def __neg__(self) -> "Vec2":
        return Vec2(-self.x, -self.y)

    def copy(self) -> "Vec2":
        return Vec2(self.x, self.y)

    def as_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def length_sq(self) -> float:
        return self.x * self.x + self.y * self.y

    def normalized(self) -> "Vec2":
        L = self.length()
        if L < 1e-12:
            return Vec2(0.0, 0.0)
        return Vec2(self.x / L, self.y / L)

    def with_length(self, length: float) -> "Vec2":
        return self.normalized() * length

    def dot(self, other: "Vec2") -> float:
        return self.x * other.x + self.y * other.y

    def angle(self) -> float:
        return math.atan2(self.y, self.x)

    def rotated(self, radians: float) -> "Vec2":
        c, s = math.cos(radians), math.sin(radians)
        return Vec2(self.x * c - self.y * s, self.x * s + self.y * c)

    @staticmethod
    def from_angle(radians: float, length: float = 1.0) -> "Vec2":
        return Vec2(math.cos(radians) * length, math.sin(radians) * length)

    @staticmethod
    def from_iterable(xy: Iterable[Number]) -> "Vec2":
        it = list(xy)
        return Vec2(float(it[0]), float(it[1]))


def clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value

"""Seeded RNG wrapper for reproducible sims."""

from __future__ import annotations

import random
from typing import Optional, Sequence, TypeVar

T = TypeVar("T")


class Rng:
    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    def random(self) -> float:
        return self._rng.random()

    def uniform(self, a: float, b: float) -> float:
        return self._rng.uniform(a, b)

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        return self._rng.gauss(mu, sigma)

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)

    def choice(self, seq: Sequence[T]) -> T:
        return self._rng.choice(seq)

    def angle(self) -> float:
        """Uniform heading in radians [-pi, pi)."""
        return self.uniform(-3.141592653589793, 3.141592653589793)

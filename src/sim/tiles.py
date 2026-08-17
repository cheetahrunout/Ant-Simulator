"""
World tile roles — every cell has exactly one structural role.

  OPEN  (pheromone ground) — outdoor free floor; food trails live here
  WALL                     — solid; no walk, no pheromone
  NEST                     — nest floor / tunnel / door; nest scent lives here
  FOOD                     — outdoor food patch tile (also trail-capable)

Ants still move continuously; structure is fully grid-aligned.
"""

from __future__ import annotations

# Structural roles (uint8 on the map)
OPEN = 0  # outdoor free = pheromone ground
WALL = 1
NEST = 2
FOOD = 3

ROLE_NAMES = {
    OPEN: "open",
    WALL: "wall",
    NEST: "nest",
    FOOD: "food",
}

# Walkable / pheromone-capable
WALKABLE = frozenset({OPEN, NEST, FOOD})
PHEROMONE_OK = frozenset({OPEN, NEST, FOOD})  # walls never hold scent

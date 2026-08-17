# Ant Simulator — Current State Summary

## ★ Food damage graphics (landed)

Prey no longer uses yellow part blobs. Each kind has:

- `assets/food/{kind}/damage/{n}.png` — carcass after *n* parts detached  
- `assets/food/{kind}/{part_id}.png` — hauled / loose piece (wing, leg, head, body)

Draw path: `food_sprite.compose_carcass` + `get_part_sprite` (see `src/render/draw.py`).

## Haul rewrite (landed)

**Cooperative hauling** = passive load + per-ant forces (`src/sim/haul_physics.py`).  
Tune with `solo_haul_speed_percent`, mass, multi cap; test: `config/test_butcher.yaml`.

---

**Date:** 2026-07-29  
**Milestone:** M1 forage + trails + prey butcher/haul (WIP)  
**Stack:** Python + Pygame + NumPy + PyYAML  
**Run:** `python -m src.main` from project root  
**Small test map:** `python -m src.main config/test_small.yaml` (1/10 top-left)  
**Butcher test:** `python -m src.main config/test_butcher.yaml`  
**Auto trail test + shots:** `python -m tests.run_trail_test` → `debug screenshots/auto/`  
**Manual shot:** **F12**  

Full original design plan: `plan.md`

---

## What works today

### World
- Open **toroidal** outworld (20 000 × 12 000), **no border walls**
- **Single tile grid** (`tile_size: 10`, was 20 → each old cell is 2×2): roles `OPEN` | `WALL` | `NEST` | `FOOD`
- Three formicaria (home + empty good + empty poor), geometry in **tile units**
- Nest: chambers, door ≥ 1 tile, tunnel entrance ≥ 1 tile; walls = solid collision
- Continuous ant positions on top of the grid

### Foraging (M1)
- ~35 identical workers; shared behavior code
- States: idle in nest → outbound / explore → pickup → return → unload at **single home tile**
- Food: two start patches (amounts **240** / **180**, 5× smaller than earlier), square tile-aligned; respawn when empty
- Carry slows speed; quality affects recruitment strength
- Stuck ants teleport to home after ~10s

### Pheromones (simple deposit + wind)
- **Deposit** while carrying: fixed `deposit_amount` once per new tile  
  (reinforce = more ants drop the same amount; no max× / boost / mult)  
- **Wind**: `trail_evaporation` units/s on active cells  
- **Floor** + optional **diffusion**  
- Food gone → trail fades  
- Docs: `PHEROMONE_SIMPLE.md`  
- Backups: `../Ant-Simulator-backup-20260724-1531/`,  
  `../Ant-Simulator-backup-deposit-20260724-1608/`

### Rendering / UX
- CC0 walking-ant sprites (`assets/ant/`)
- Sandy nest floors for contrast with black ants
- Live config sidebar: **collapsible sections**, Save → `config/saved.yaml`
- **P** = trail heatmap **+** numbers (numbers only if **zoom > 1.5**)
- Walls keep wall color on heatmap; **numbers only** on walls (no heat tint)
- **V** = debug heading/steer vectors (all ants); not WASD **D**
- Food drawn as tile-aligned squares

### Performance notes
- Wall sensing uses **local tile grid** (fixed earlier lag from 100s of wall rects)
- **Sparse pheromone** (2026-07-18): active-cell sets for trail/nest — no full-grid
  `np.roll` / nonzero on 2.4M cells. Spread ~1 ms with hundreds of active tiles;
  full step ~2–3 ms sim-side (comfortably above 60 FPS). Multi-core not used
  (pool overhead would exceed savings at this scale).
- GPU not used; not recommended for current scale

---

## Key controls

| Key | Action |
|-----|--------|
| Click-drag / WASD / arrows | Pan |
| Bottom food bar / 1–3 | Select prey, click map to place |
| Wheel | Zoom |
| Space | Pause |
| R | Reset sim |
| P | Heatmap + values |
| V | Steer vectors |
| Tab | Config sidebar |
| H | Help |
| Esc | Quit |

---

## Layout snapshot (default)

- Home nest origin tile ≈ `[12, 38]` (tile_size 10)
- Food A: tile `[62, 48]` amount 240 Q1.0  
- Food B: tile `[38, 78]` amount 180 Q0.55  

---

## Main code map

| Area | Path |
|------|------|
| Entry | `src/main.py` |
| World / env step | `src/sim/world.py` |
| Grid / pheromone | `src/sim/grid.py`, `src/sim/tiles.py` |
| Nest build | `src/sim/nest.py` |
| Ants / forage | `src/agents/ant.py`, `locomotion.py` |
| Draw / sprites | `src/render/draw.py`, `ant_sprite.py` |
| Live config | `src/render/sidebar.py` |
| Defaults | `config/default.yaml` (+ optional `saved.yaml`) |

---

## Not done yet (from plan)

- Division of labour (response thresholds + age) beyond basic forage states  
- Brood / trophallaxis / queen module  
- Full house-hunting (assess empty nests, quorum, emigration)  
- Death / lifecycle  
- Sparse/active-region pheromone optimisations if FPS bites again  

---

## Recent design decisions (session)

1. Whole-map spread OK; locality from floor + delta (not bbox-only)  
2. No evaporation parameter — dilution + floor (+ wall delete-on-pass)  
3. Walls = silent pheromone sink when they “forward” mass  
4. Food smaller start supply; one patch moved +5 tiles right  
5. Sprite ants + light nest floors  

---

*Quick handoff note for next session — not a full design doc. See `plan.md` for the long-term roadmap.*

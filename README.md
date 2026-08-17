# Ant Simulator (*Lasius niger*–inspired)

2D agent-based formicarium simulator. Every worker runs the **same** behavior code; colony cooperation (trails, roles, nest choice) is meant to emerge from local rules.

## Stack

- Python 3.11+
- Pygame, NumPy, PyYAML

## Setup

```bash
cd Ant-Simulator
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python -m src.main
```

Optional config path:

```bash
python -m src.main config/default.yaml
```

### Controls

| Input | Action |
|-------|--------|
| Click-drag (or WASD / arrows) | Pan camera |
| Bottom food bar (or keys 1–3) | Choose prey, click map to drop |
| Mouse wheel | Zoom |
| Space | Pause / resume |
| R | Reset simulation |
| P | Toggle trail heatmap + per-tile numbers |
| V | Toggle heading / steering vectors (all ants) |
| H | Toggle help text |
| Tab | Config sidebar |
| Esc | Quit |

### Ant sprites

Workers use the CC0 [walking ant](https://opengameart.org/content/walking-ant-with-parts-and-rigged-spriter-file) pack (`assets/ant/walk_strip.png`). See `assets/ant/ATTRIBUTION.txt`. Toggle with `ants.use_sprites` in config.

## Current milestone: M1 — Foraging + trails

- Open outworld (20000×12000, toroidal wrap) + formicarium nests
- Food patches near home; workers pick up, return, unload to colony store
- **Trail pheromone** deposit on return (quality / distance / suppress / crowd rules)
- **Nest scent** for homing; trail following for recruitment
- Heatmap + values (**P**), steer vectors (**V**)

**Live config sidebar:** drag sliders to tune pheromone / forage / ants / camera while running. Hover a slider + mouse wheel to nudge.

| Button | Effect |
|--------|--------|
| **Save** | Writes current slider values to `config/saved.yaml` — loaded on **next** launch |
| **Reset** | Restores values from the **start of this run** (does not delete the save file) |

Tune `food`, `pheromone`, `forage` in `config/default.yaml`.

## Roadmap

| Milestone | Focus |
|-----------|--------|
| **M0** | Skeleton ✅ |
| **M0.5** | Locomotion ✅ |
| **M1** | Foraging + trails (current) |
| **M2** | Economy, brood stimuli, response-threshold DOL |
| **M3** | Memory, alarm, nestmate recognition |
| **M4** | Nest assessment, quorum, emigration |
| **M5** | Queen, polish, scenarios, scale |

## Project layout

```
config/default.yaml   # tunables
src/main.py           # entry + game loop
src/sim/              # world, nests, colony
src/agents/           # shared worker brain
src/render/           # camera + draw
src/util/             # vec, rng, config
```

# Plan: Lasius niger–inspired Ant Simulator (Single-Worker Code → Emergent Colony)

## Context

Build a **2D agent-based ant simulator** where **one worker behavior program** is shared by all ants. Cooperation (trails, recruitment, nest choice, division of labor) must emerge from local sensing and simple rules—not from a global “colony AI.”

**Design choices locked (from you):**
| Choice | Decision |
|--------|----------|
| Stack | **Python + Pygame** |
| Fidelity | **L. niger–inspired hybrid** (real foraging/pheromones + simplified house-hunting) |
| Nest selection | **Simplified house-hunting** (evaluate empty sites, recruit, quorum, emigrate) |
| Roles | **Response thresholds + age bias** (same code, emergent roles) |
| World | **Continuous 2D ants + discrete pheromone/environment grid** |
| First milestone | **Foraging + trail recruitment first** |

**Queen:** separate module later; for v1 use a static queen marker / brood source.

**Project state:** M0–M1 implemented under `Ant-Simulator/`; next polish is the pheromone-number sub-plan below.

---

## Research foundation (what real ants do)

### Species baseline: *Lasius niger* (black garden ant)

- Monogynous colonies; workers monomorphic (no major/minor castes).
- Colonies: hundreds → ~10k workers in the wild; **sim start with 10–50 workers**.
- Diet: insects (protein) + honeydew/sugar (carbs); liquid food often shared via **trophallaxis**.
- Foraging: bold open foragers; **mass recruitment** via trail pheromone when food is good or large.
- Nests: soil under stones / walls (digging). We **hybridize** with cavity house-hunting so empty prebuilt nests are interesting to evaluate.

### Behaviors to model (priority-ranked)

#### A. Core locomotion & sensing (all ants)
| Behavior | Real basis | Sim abstraction |
|----------|------------|-----------------|
| Correlated random walk | Stochastic exploration | Small random turn noise each step |
| Local antennae sense | Short-range chemoreception | Sample pheromone/food/nest in a small cone/radius ahead |
| Wall / obstacle collision | Physical body | Circle body vs solid cells / walls |
| Carry load | Food/brood/nestmate | Attach entity; reduce speed |
| Energy / satiety | Workers need food | Internal energy; low energy → food-seeking bias |

#### B. Navigation (L. niger strong suit)
| Mechanism | Notes | Phase |
|-----------|-------|-------|
| **Trail pheromone following** | Primary social cue; high fidelity in L. niger | **M1** |
| **Private route memory** | Repeated routes learned; pheromone helps learning | M2 |
| **Path integration (homing vector)** | Vector home after outbound trip | M2 (simplified) |
| Visual landmarks | Used with pheromones in L. niger | Optional later |

Key papers / findings to encode as **rules**, not full chemistry:
- Trail laying stronger near good food and modulated by trail already present (negative feedback / less deposit on heavy trails).
- Experienced foragers can rely more on memory; naïve ants rely more on pheromone.
- Beckers / Deneubourg-style recruitment: more deposit → more traffic → more deposit (positive feedback) until saturation.

#### C. Pheromones (start simple, expand)
| Layer | Function | Evaporation | Who lays | Phase |
|-------|----------|-------------|----------|-------|
| **Food trail** | Recruit to food; guide outbound | Medium | Returning successful foragers | **M1** |
| **Home / nest scent** | Diffuse nest marker for orientation | Slow | Nest area constant / workers near nest | **M1** |
| **Alarm** | Attract defenders / flee | Fast | Injured / fight | M3 |
| **Nest-site quality** | Mark candidate nest during house-hunting | Medium | Scouts assessing sites | M4 |
| Colony odor (CHC) | Nestmate recognition | Static per colony | — | M3 optional |

**M1 minimum:** food trail + nest scent on a grid with deposit, diffuse, evaporate.

#### D. Communication (beyond pheromone)
| Channel | Use | Phase |
|---------|-----|-------|
| Pheromone trails | Mass recruitment | M1 |
| Antennation / local contact | Food sharing trigger, task stimuli | M2 |
| Trophallaxis | Liquid food transfer | M2–M3 |
| Tandem / leading (simplified) | Guide to nest site | M4 |
| Alarm body shake / chemical | Defense | Later |

No global chat. All info is **local** or **environment-mediated**.

#### E. Division of labor (response threshold + age)
Classic model (Bonabeau / Beshers / Fewell style):

- Tasks: `brood_care`, `nest_maintenance`, `forage`, `scout`, `defend` (subset early).
- Each ant has **threshold θ_task** and senses **stimulus s_task** (local).
- Probability of performing task rises when `s > θ` (sigmoid).
- **Age bias:** young → lower brood thresholds, higher forage thresholds; age flips this.
- Colony need raises stimuli (hungry brood, empty food stores, damaged nest, “need scout” timer).
- **Same code for every worker** — specialization is emergent and reversible.

#### F. Nest site selection (simplified house-hunting)
Inspired by *Temnothorax* (user’s perimeter idea) adapted for formicarium sim:

1. **Scout** finds empty nest site.
2. **Assess quality** (local measurements, time spent scanning):
   - Darkness (prefer dark)
   - Entrance size (prefer narrow)
   - Interior area / usable capacity
   - **Perimeter walk** (proxy for size/shape exploration)
   - Distance from current nest / hazards
3. If quality high enough → **recruit** (trail or lead) others.
4. **Quorum:** if enough nestmates present at candidate → switch to **emigration** (carry brood / “queen token”).
5. Old nest abandoned when stimuli bad (light, dryness, overcrowding) *or* better site quorum reached.

#### G. Brood & queen (low priority stubs)
- Brood piles as entities with stages: egg → larva → pupa → callow.
- Nurses move brood toward preferred microclimate (dark/humid cells).
- Queen: static egg production rate for now.

---

## Environment design (captivity-style formicarium)

### Layout concept

```
┌─────────────────────────────────────────────────────────────┐
│                     OUTER WORLD (foraging arena)             │
│   food patches · obstacles · optional aphids later           │
│                                                              │
│   ┌──────── Nest A ────────┐     ┌──── Nest B (empty) ────┐ │
│   │  entrance tunnel       │     │  entrance              │ │
│   │  [chamber] [chamber]   │     │  [chamber] [chamber]   │ │
│   │  [brood]   [queen]     │     │  dark, good size       │ │
│   └────────────────────────┘     └────────────────────────┘ │
│   ┌──── Nest C (empty, poor) ──┐                            │
│   │  bright / too big entrance │                            │
│   └────────────────────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

### Specs (v1)
- **World size:** large enough that trails matter (e.g. 2000×1200 world units; camera zoom/pan).
- **Grid cell:** ~4–8 world units for pheromone/soil.
- **Nests:** 2–3 prebuilt multi-chamber sites + one occupied starter nest.
- **Outer world:** open arena with 2–4 food sources at different distances/qualities.
- **Chambers:** dark polygons with walls; tunnels as narrow walkable corridors.
- **Physics:** no full physics engine — kinematic agents, collision with walls, optional simple separation.

### What “plenty big” means in practice
- Travel time nest↔food should be many steps (dozens of seconds sim time) so trails form and ants don’t instantly telepathically find food.
- Start colony small so CPU is fine; design so **hundreds** of ants remain viable later.

---

## Architecture

```
Ant-Simulator/
  README.md
  requirements.txt          # pygame, numpy, (optional pyyaml)
  config/
    default.yaml            # world size, rates, thresholds, pheromone half-lives
  src/
    main.py                 # entry, game loop
    sim/
      world.py              # continuous space + grid layers
      grid.py               # pheromone deposit/diffuse/evaporate
      nest.py               # chambers, entrances, quality metrics
      food.py               # sources, amounts
      colony.py             # list of ants, queen stub, brood piles
    agents/
      ant.py                # shared worker brain (state + sensors + actuators)
      sensors.py            # local samples
      tasks.py              # task stimuli + threshold checks
      behaviors/            # pure functions / small modules
        explore.py
        forage.py
        trail.py
        brood.py
        nest_assess.py
        emigrate.py
    render/
      camera.py
      draw.py               # ants, pheromone heatmaps, nests, UI
    util/
      vec.py
      rng.py
  tests/
    test_pheromone.py
    test_thresholds.py
    test_nest_quality.py
```

### Core loop (fixed timestep)
1. Sense (local grid + nearby entities)
2. Update internal state (energy, age, memory, current task)
3. Decide action (threshold + FSM hybrid — see below)
4. Act (move, deposit, pick up, drop, recruit)
5. Environment step (pheromone diffuse/evaporate, food regen optional)
6. Render (decoupled; can run headless for tests)

### Worker control model (hybrid FSM + thresholds)

**Macro states** (finite, clear):
`idle_in_nest` → `explore` | `forage_outbound` | `forage_return` | `brood_care` | `assess_nest` | `recruit` | `emigrate` | `alarm`

**Task selection** when idle: response-threshold lottery over available stimuli.

**Within a task:** small behavior rules (follow trail gradient, deposit on return if food quality high, etc.).

This keeps debugability (you can print state) while allowing emergence (who forages vs nurses is not hardcoded).

### Critical shared worker API (conceptual)

```python
class WorkerAnt:
    # identity
    age, energy, colony_id
    thresholds: dict[Task, float]
    # memory
    home_vector, known_food_dir, last_nest_quality
    # load
    carrying: None | Food | Brood | Nestmate

    def step(self, world):
        stimuli = sense(self, world)
        maybe_switch_task(self, stimuli)  # thresholds + age
        act_current_task(self, world, stimuli)
        age_and_metabolism(self)
```

**Queen class** later implements different step; workers never call “colony.decide()”.

---

## Implementation phases

### Milestone 0 — Skeleton (½ day)
- Pygame window, camera pan/zoom, fixed-timestep loop.
- World + walls + one nest polygon + open arena.
- Dummy ants: random walk + wall bounce.
- Config file for sizes/speeds.

**Done when:** you see ants milling in a formicarium layout.

### Milestone 1 — Foraging + trails (primary goal) ✅ first playable

**Goal features**
- Food patches with quantity/quality.
- Ants leave nest, explore (correlated random walk).
- Find food → pick up / fill crop → **home via nest scent + reverse trail / home vector stub**.
- **Deposit food trail** on return (strength modulated by rules below).
- Other ants **follow trail gradient** outbound with noise.
- Drop food at nest; energy restore for colony food store.
- UI: toggle pheromone heatmap; stats (foragers active, food in nest).

#### Research findings → implementable rules (M1)

*L. niger* is one of the best-studied mass-recruiting ants (Beckers, Deneubourg, Goss; Czaczkes lab). Encode these as **local deposit/follow rules**, not chemistry.

| Finding | Source theme | Sim rule |
|---------|--------------|----------|
| Positive feedback builds trails | Beckers et al. mass recruitment | Returning ants deposit trail; outbound ants bias heading toward local trail gradient |
| Higher food quality → more deposit | Classic L. niger modulation | `deposit ∝ food_quality` (and optionally colony hunger later) |
| Heavy existing trail **suppresses** further deposit | Czaczkes 2013 negative feedback | If local trail intensity > `trail_cap`, reduce deposit (conserves pheromone, stabilizes path) |
| Deposit **much higher near food** than near nest | Czaczkes et al. 2024 (~22× within 10 cm of food vs near nest) | Scale deposit by distance-from-food or progress along return: high at start of return, low near nest |
| Deposit **higher for more distant** food sources | Czaczkes 2024 / Devigne & Detrain 2006 | Scale deposit by outbound trip length or effort (`1 + k * distance_travelled`) |
| Stereotypic “gaster touch” deposit | Observable discrete marks | Deposit in pulses every N steps (not continuous paint) — looks and acts more ant-like |
| Ants avoid crowded feeders + deposit less there | Wendt/Czaczkes negative social feedback | If many nestmates at food patch, prefer empty patch / deposit less on return |
| Trail helps navigation + **route learning** | Czaczkes JEB 2013 | M1: trail following only. M3: add private memory that pheromone helps form |
| Alternating routes harder than repeating | Czaczkes 2013 | Optional maze scenario later; pheromone reduces error rate |
| Starved colonies recruit more aggressively | Mailleux et al. | When colony food store low, multiply deposit or lower forage threshold (M2 hook) |
| Trail following fidelity is high and fairly state-independent | Poissonnier et al. | Outbound followers use same follow gain whether naïve or experienced (keep simple) |
| Randomness is adaptive | Trail models generally | Always keep turn noise; pure greedy gradient following fails exploration |

**M1 deposit formula (starting point):**

```text
base = deposit_amount * food_quality
base *= (1 + dist_scale * trip_distance)
base *= proximity_to_food_factor(progress_home)   # high near food, low near nest
base *= 1 / (1 + trail_suppress * local_trail)
if nestmates_at_food > crowd_threshold: base *= crowd_penalty
if random() < deposit_pulse_chance: grid.add_trail(pos, base)
```

**M1 follow formula:**

```text
heading = normalize(
  w_trail * gradient(trail) +
  w_nest  * gradient(nest_scent)   # mainly for return
  + noise
)
```

**Done when:** with ~20 identical ants, a stable trail forms to the better/closer food and traffic concentrates (classic emergent recruitment).

**Verification:**
- No trail → slow discovery, weak concentration.
- Trail enabled → positive feedback, majority on one source.
- Remove food mid-trail → trail evaporates, ants re-explore.
- Two foods, different quality → richer source gets more traffic.
- Crowding: optional second food preferred when first is crowded.

---

### Milestone 2 — Internal economy + simple DOL

**Goal features**
- Colony food store; brood hunger stimulus.
- Energy drain; ants feed from store or trophallaxis stub.
- Age variable + threshold bias.
- Tasks: `brood_care`, `nest_maintenance` (placeholder), `forage`, `scout`.
- Stimulus fields: brood need, low food store, unexplored/scout need.

#### Research findings → implementable rules (M2)

Division of labor in ants is **emergent**, not centrally assigned. Fixed response-threshold models (Bonabeau, Theraulaz, Deneubourg) plus age/polyethism capture most of what we need for monomorphic *L. niger* workers.

| Finding | Source theme | Sim rule |
|---------|--------------|----------|
| Fixed response thresholds create specialists | Bonabeau / Theraulaz FRT model | Each ant has `θ_task`; does task when local stimulus `s_task` exceeds θ (probabilistic sigmoid) |
| Performing a task can **reinforce** specialization | Threshold reinforcement models | Optional: after success, slightly lower θ for that task, raise others (slow learning) |
| Young inside, old outside (age polyethism) | Widespread in ants; early-stage DOL studies | Age shifts base thresholds: young low `θ_brood`, high `θ_forage`; reverse with age |
| Task switching has cost / inertia | Evolving DOL literature | Min dwell time on a task before re-lottery (prevents thrashing) |
| Specialists ≠ always more efficient | Dornhaus Temnothorax work | Don’t hardcode efficiency bonuses; let load-balancing emerge from stimuli |
| Foragers can **revert** to nursing if nurses removed | Classic flexibility experiments | Raising brood stimulus (no nurses) causes high-θ nurses (old foragers) to still respond |
| Scouts in small groups act more “solitary” | Collective exploration L. niger | Scout mode: higher random-walk variance, weaker trail-following weight |
| Food must reach in-nest workers | Trophallaxis / social stomach | Foragers unload to nest store or to encounter partners; nurses feed from store/brood |
| Colony hunger changes foraging effort | Mailleux critical volume / starvation | Global `colony_hunger` boosts forage stimulus and deposit scale (links to M1) |
| Idle ants still sample local cues | Real colonies | Even “idle_in_nest” ticks sense brood/food/alarm and may switch |

**Task stimuli (local or colony-visible, still no planner):**

| Task | Stimulus `s` sources |
|------|----------------------|
| `brood_care` | Nearby unattended brood, brood hunger, distance to queen/brood pile |
| `forage` | Low colony food store, personal energy, outbound trail strength at entrance |
| `scout` | Time since last new-area discovery, low trail coverage, nest stress (M4) |
| `nest_maintenance` | Debris, wall damage flags, overcrowding (stub) |

**Response probability:**

```text
P(do task) = 1 / (1 + exp( -gain * (s_task - θ_task) ))
θ_task = θ_base[task] + age_bias[task](age) + individual_noise
```

**Done when:** young ants cluster on brood more; older ants dominate outside; removing nurses causes some foragers to revert (threshold flexibility).

**Verification:**
- Age histogram per task shifts as colony ages.
- Starve nest store → forage stimulus rises → more outbound ants.
- Cull young nurses → older workers spend more time on brood.

---

### Milestone 3 — Richer communication, memory & combat stubs

**Goal features**
- Alarm pheromone on damage / threat.
- Nestmate recognition (`colony_id` / odor template).
- Route / private memory interacting with trails.
- Quality still encoded mainly via **deposit rate** (not a second food pheromone unless needed).
- Optional body-contact interactions (antennation, simple trophallaxis completion).

#### Research findings → implementable rules (M3)

| Finding | Source theme | Sim rule |
|---------|--------------|----------|
| Alarm is multi-gland (formicines): formic acid, undecane, mandibular volatiles | Lasius / Formicinae chemistry | Single **fast-evaporating alarm layer**; deposit on injury or non-nestmate fight |
| Alarm both **attracts** defenders and **excites** | Classic alarm-defense | Nearby ants: if `θ_defend` low or already outside → approach; fragile ants may flee |
| Nestmate recognition via CHC “colony odor” | Sturgis & Gordon review | Each ant has `odor_vector` (or scalar colony_id v1); mismatch > threshold → aggression |
| Recognition is **graded & context-dependent** | Adjustable threshold models | Aggression intensity scales with odor distance; near nest more aggressive than at food |
| Private info (memory) vs social info (pheromone) | Czaczkes decision papers | Experienced forager: blend `w_memory * remembered_dir + w_trail * gradient`; weights change with success/error |
| After a navigation **error**, deposit **more** on return | Czaczkes 2013 | If outbound path mismatched memory, boost return deposit (repair trail) |
| Pheromone aids **learning** of routes | Czaczkes 2013 | While following trail successfully, strengthen private route memory for that food |
| Trail following not strongly modulated by task state | Poissonnier et al. | Keep follow kernel simple; put complexity in deposit + memory weights |
| Undecane / hendecane alarm in Lasius group | Bergström & Löfqvist classic | Model as one alarm channel with short half-life (seconds of sim time) |
| L. niger body shakes in alarm contexts | Recent alarm-communication work | Optional visual/FX only; no need for separate mech channel in v1 |
| Do **not** require dual attractive food pheromones | L. niger single trail compound known | Prefer single trail intensity + deposit modulation over multi-pheromone food code |

**Memory model (lightweight):**

```text
on_successful_food_return:
  food_memory.position = food_pos
  food_memory.confidence = min(1, confidence + learn_rate)

outbound_heading = normalize(
  memory_weight(confidence) * dir_to(food_memory) +
  trail_weight * trail_gradient +
  explore_noise
)
```

**Nestmate stub (v1):**

```text
if other.colony_id != self.colony_id:
  if odor_distance > aggression_threshold(context):
    enter_alarm(); deposit_alarm(); maybe_attack()
```

**Done when:** ants repair trails after displacement, prefer remembered good food when trails weak, and cluster/excite on alarm without a global “defend now” flag.

**Verification:**
- Displace foragers / wipe part of trail → memory still finds food; re-deposit rebuilds trail.
- Spawn foreign ant → local alarm plume + attraction of nearby workers.
- Same colony contact → no fight; food transfer possible.

---

### Milestone 4 — Nest site selection & emigration

**Goal features**
- Multiple empty nests with different quality parameters.
- Scout assess: perimeter walk, area, darkness, entrance width.
- Quality score → recruitment probability / latency.
- Quorum at site → switch to rapid transport (brood / queen token).
- Old-nest stressor (light/heat/dry) like antkeeping “force move.”

#### Research findings → implementable rules (M4)

House-hunting is best formalized in **Temnothorax** (Pratt, Franks, Mallon, Sumpter). *L. niger* does not use the full cavity-dwelling playbook in nature, but the user’s formicarium + empty nests maps cleanly onto this model — which is why we chose the hybrid.

| Finding | Source theme | Sim rule |
|---------|--------------|----------|
| Scouts **independently assess** sites (no need to compare all options) | Pratt / parallel evaluation | Each scout stores quality of sites it visited; no global ranking board |
| Prefer **dark** interiors | Temnothorax light experiments | `quality += w_dark * (1 - light_level)` |
| Prefer **small / narrow entrances** (defense) | Pratt & Pierce; Franks et al. | `quality += w_entrance * preference(narrow)` |
| Interior size matters (too small bad; sometimes too large bad) | Cavity preference studies | Soft optimum on area vs colony size; perimeter walk estimates size |
| **Perimeter / exploration time** as size proxy | User request + assessment duration | Scout must walk interior boundary / spend `assess_time ∝ 1/quality` (better sites accepted faster) |
| Recruitment rate scales with quality | Pratt agent-based models | Higher quality → shorter latency to recruit; higher recruit probability |
| Phase 1: **tandem run** (slow) | Temnothorax emigration | Leader guides 1 follower to site (simplified: strong short-range “follow me” + trail) |
| Phase 2 after **quorum**: **transport** (fast carry) | Encounter-rate quorum sensing | If local nestmate count (or encounter rate) ≥ `Q`, switch to carry brood/queen/passive ants |
| Quorum sensed via **encounter rate**, not census | Pratt et al. | `encounters_per_time` at site ≥ threshold (robust, fully local) |
| Better sites reach quorum first → colony usually picks best | Positive feedback | Emergent choice; no voting |
| Can still choose farther better nest over closer worse | Empirical Temnothorax | Quality-weighted recruitment can beat pure distance if assess/recruit strong enough |
| Emigration can be triggered by home damage | Antkeeping + nest destruction assays | Raise `home_stress` stimulus → more scouts; lower quorum slightly under emergency |
| Dead ants / filth reduce site quality | Nest preference factors | Optional: corpse presence lowers quality |
| Active minority organizes move | Only some workers scout | Response thresholds: only low-θ scouts start assessment; others wait to be led/carried |

**Assessment algorithm (per scout):**

```text
on discovering empty nest:
  walk interior (wall-follow perimeter once or timed tour)
  measure: light, entrance_width, area_estimate, distance_from_home, hazards
  quality = weighted_sum(...)
  if quality > personal_accept_threshold:
    start_recruitment(site)
  assess_duration = assess_base / (eps + quality)   # good nests decided faster
```

**Quorum & phase switch:**

```text
at candidate site:
  encounter_rate = nestmates_met / time_window
  if encounter_rate >= quorum_Q:
    recruitment_mode = TRANSPORT  # carry brood, queen token, passive workers
  else:
    recruitment_mode = TANDEM_OR_TRAIL  # slow build-up
```

**Quality vector for empty nests (designer knobs):**

| Nest | Light | Entrance | Area | Expected rank |
|------|-------|----------|------|---------------|
| A (current) | dark | ok | medium | home until stressed |
| B (good empty) | very dark | narrow | good for colony size | should win |
| C (poor empty) | bright | wide | huge or tiny | should lose |

**Done when:** stressing old nest + offering good empty nest leads to scouts assessing, recruiting, and colony relocating brood **without a central planner**.

**Verification:**
- B vs C only → majority emigrates to B.
- Stress home + both empty → quorum at B first more often than C across seeds.
- Kill quorum (set Q huge) → stuck in slow recruitment, no full move.
- Perimeter/assess time visible in debug (scout paths hug chamber walls).

### Milestone 5 — Polish & scale
- Queen module (egg laying rate).
- Brood development lifecycle.
- Performance: spatial hash for neighbors; numpy grid ops.
- Scenario presets: “double bridge” (classic L. niger experiment), “two nest choice”, “food quality competition”.
- Headless batch runs for parameter sweeps.

---

## Behavior checklist (full ant “character sheet”)

Use this as the living feature list. **Bold = M1.**

**Physiology**
- [x] Position, heading, speed
- [ ] Age / lifespan
- [ ] Energy / crop fullness
- [ ] Carry capacity
- [ ] Health (alarm trigger)

**Sensing**
- [x] Walls / free space
- [ ] Local pheromone samples (multi-layer)
- [ ] Food in range
- [ ] Nestmates in range
- [ ] Brood / queen proximity
- [ ] Light level (nest quality)
- [ ] Entrance / chamber geometry

**Actuators**
- [x] Move / turn
- [ ] Deposit pheromone
- [ ] Pick up / drop (food, brood)
- [ ] Feed / trophallaxis
- [ ] Attack (later)

**Cognitive / internal**
- [ ] Current task + FSM state
- [ ] Response thresholds
- [ ] Home vector / nest direction
- [ ] Private food memory
- [ ] Nest quality memory

**Colony-level (emergent only)**
- [ ] Trail networks
- [ ] Division of labor
- [ ] Nest choice & emigration
- [ ] Defense clustering

---

## Key parameters (config-driven)

Tune without code changes:

**M1 trails**
- `pheromone.deposit_amount`, `evaporation_rate`, `diffusion_rate`
- `trail.follow_weight`, `random_turn_sigma`
- `trail.suppress_on_strong` (negative feedback when trail already heavy)
- `trail.near_food_boost`, `trail.distance_effort_scale` (Czaczkes 2024-style)
- `trail.deposit_pulse_interval`, `forage.crowd_deposit_penalty`
- `forage.food_quality_deposit_scale`

**M2 DOL / economy**
- `thresholds.base_*`, `age_shift_rate`, `task_min_dwell_ticks`
- `thresholds.reinforcement_rate` (optional specialization learning)
- `stimuli.colony_hunger_weight`, `stimuli.brood_need_weight`
- `energy.drain_rate`, `trophallaxis.transfer_amount`

**M3 memory / alarm / recognition**
- `memory.learn_rate`, `memory.trail_vs_private_blend`
- `alarm.evaporation_rate`, `alarm.attract_radius`
- `recognition.aggression_threshold`, `recognition.nest_context_boost`

**M4 house-hunting**
- `nest.quorum_encounter_rate`, `nest.assess_base_time`
- `nest.w_dark`, `nest.w_entrance`, `nest.w_area`, `nest.w_distance`
- `nest.tandem_speed_factor`, `nest.transport_speed_factor`
- `nest.home_stress_scout_boost`

**World**
- `world.cell_size`, `ant_radius`, `sense_radius`

---

## Existing code to reuse

None yet (empty repo). First implementation establishes the patterns above; all later behaviors plug into `WorkerAnt.step` and grid layers.

---

## Verification plan

| Check | How |
|-------|-----|
| Unit | Pheromone mass under diffusion/evaporation; nest quality ranks good > bad; threshold sigmoid edges |
| Integration (M1) | 20 ants form trail to food within N ticks with fixed seed |
| Deposit modulation (M1) | Heatmap brighter near food than near nest; distant food deposits more per return |
| Negative feedback (M1) | Saturated trail reduces new deposits; second equal path can still compete early |
| Crowding (M1) | Occupied feeder gets less recruitment than empty equal feeder |
| Emergence (M1) | Better food wins most traffic when two sources (quality or distance) |
| DOL (M2) | Age histogram per task shifts; nurse removal → forager reversion |
| Hunger (M2) | Empty store → more foragers / stronger deposit |
| Memory (M3) | Partial trail wipe → experienced ants still find food; re-mark trail |
| Alarm (M3) | Damage/foreign ant → local plume; nearby workers approach or excite |
| House-hunt (M4) | Stress home + good empty → encounter quorum → brood transport |
| Quorum necessity (M4) | Huge Q blocks full emigration (stays in slow recruit) |
| Performance | 200 ants @ 60 FPS target on mid PC (profile grid size) |
| Manual | Pheromone heatmap; click-spawn food; stress nest; spawn foreign ant |

**Classic experiment scenarios (stretch):**
1. **Binary bridge** — shorter path gets more pheromone (L. niger classic).
2. **Two food qualities** — richer source recruited harder.
3. **Crowded vs empty feeder** — negative social feedback.
4. **Nest choice** — small dark nest preferred over large bright one.
5. **Far better vs near worse nest** — quality-weighted recruitment can overcome distance.

---

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Ants get stuck on walls | Wall-following / bounce + small random jitter |
| Pheromone “washes out” or “floods” | Config half-lives; deposit only when returning with food |
| No trail forms | Boost deposit, slow evaporate, reduce random turn while following |
| All ants same task | Age bias + distinct stimuli; debug stimulus overlays |
| Scope creep (queen, digging, seasons) | Stick to M1 → M2 gates; queen stub only |
| Over-fidelity paralysis | Encode papers as 1–3 rules each, not full neuro models |

---

## Recommended immediate build order (when approved)

1. Project scaffold + config + pygame loop + camera  
2. Grid world + nest geometry + walls  
3. Worker random walk + collision  
4. Food + pick up + return-to-nest (nest scent gradient)  
5. Trail deposit + follow + heatmap  
6. Tune until recruitment emerges  
7. Only then: thresholds, age, brood, house-hunting  

---

## References (research anchors)

**M1 — Foraging / trails (*L. niger*)**
- Beckers, Deneubourg, Goss — trail laying, U-turns, collective path selection
- Czaczkes et al. 2013 (JEB) — route learning; pheromone aids memory; error → more deposit; strong trail suppresses deposit
- Czaczkes et al. 2024 — up to ~22× more deposit near food than near nest; more deposit for farther food sources
- Devigne & Detrain 2006 — distance-dependent deposit patterns
- Wendt / Czaczkes — avoid occupied feeders; deposit less when nestmates already feeding (negative social feedback)
- Mailleux et al. — crop fill / starvation modulates recruitment effort
- Trail chemistry: 3,4-dihydro-8-hydroxy-3,5,7-trimethylisocoumarin (model intensity only)

**M2 — Division of labor / economy**
- Bonabeau, Theraulaz, Deneubourg — fixed response-threshold (FRT) model
- Threshold reinforcement variants — specialization via experience
- Age polyethism literature — young in-nest → older outside; flexible reversion under need
- Dornhaus — specialists not always more efficient (don’t overfit bonuses)
- Trophallaxis / social stomach — liquid food distribution inside nest

**M3 — Communication / memory / alarm**
- Private vs social information trade-offs in *L. niger* foragers (Czaczkes decision papers)
- Nestmate recognition via cuticular hydrocarbons; graded, context-dependent aggression thresholds (Sturgis & Gordon review; Reeve-style models)
- Formicine alarm: formic acid + Dufour hydrocarbons (e.g. undecane) + mandibular volatiles — model as one fast layer
- Bergström & Löfqvist — Lasius gland chemistry / alarm compounds

**M4 — House-hunting (Temnothorax-inspired hybrid)**
- Pratt, Franks, Mallon, Sumpter — assess → quality-dependent recruit → quorum → transport
- Quorum via encounter rates (not global headcount)
- Preferences: dark interiors, narrow entrances, suitable cavity size (Pratt & Pierce; light-level choice assays)
- Agent-based nest choice models (Pratt & Sumpter 2005) as algorithmic template
- Antkeeping practice: stress old nest (light) to induce move into prebuilt nest

**Simulation pattern**
- Continuous (off-lattice) ants + on-lattice pheromone diffusion/evaporation — standard successful ABM approach

---

## Out of scope for early versions

- True 3D / side-view formicarium physics  
- Full soil digging cellular automata (optional post-M4)  
- Multiple competing colonies (easy later via `colony_id`)  
- Weather, seasons, alates, nuptial flights  
- Detailed queen physiology  
- Neural-network ant brains (rules first; ML optional research fork)

---

## Implementation status (as of 2026-07-18)

| Milestone | Status |
|-----------|--------|
| M0 skeleton | Done |
| M0.5 locomotion | Done |
| M1 forage + trails | Done (in progress polish) |
| Live config sidebar + Save | Done |
| Enter-once trail + stuck teleport | Done |
| Home tile unload only | Done |
| **Sub-plan: bound pheromone numbers** | Done |

Project path: Ant-Simulator/ (not empty). Queen still low priority.


---

# Sub-plan: Bound pheromone numbers (keep behaviour)

## Context

Trail values hit thousands (e.g. 11k on a stuck tile earlier; busy paths still climb fast) even after once-per-tile entry. Behaviour we want to **keep**:

- Only **food-carrying** ants lay trail  
- Lay **once when entering** a tile (not every frame)  
- Always add at least a **base** amount  
- **Existing trail** gets extra reinforce (used path stays strongest)  
- **Spread** to neighbours + **fade** when unused  
- Stronger tiles last longer than weak ones  
- Bilateral follow along high values  

We do **not** need huge absolute numbers for that — only **relative** contrast (busy path ≫ empty).

---

## Why numbers explode (code)

| Piece | Current | Effect |
|--------|---------|--------|
| Deposit | `add = base + mult * already` (`deposit_on_cells` in `grid.py`) | **Unbounded positive feedback**: each re-entry multiplies roughly by `(1+mult)` plus base. `mult=0.35` → ~1.35× growth per visit. |
| Evaporation | Absolute `v -= 4 * dt` (`trail_evaporation: 4`) | At `v=10000`, lifetime ~40 minutes — does not fight geometric growth. |
| Cap | None | No upper bound. |
| Scale | `base=48` | Even without mult, dozens of visits → thousands. |

So the model is behaviourally right (reinforce used paths) but **mathematically unbounded**.

---

## Recommended approach: soft capacity + saturating reinforce

Keep the same local rules; put pheromone on a **0 … trail_max** scale (default **100**).

### 1. Hard soft-cap (after every write)

```text
cell = min(cell, trail_max)
```

Applied after deposit and after spread receive. Values never leave `[0, trail_max]`.

### 2. Saturating deposit (same intent as base + mult × existing)

Replace pure linear mult with a form that still boosts used trails but **stops exploding**:

```text
fill = already / trail_max          # 0..1
add  = base * (1 + mult * (1 - fill))   # OR see alt below
# always clamp:
new  = min(already + add, trail_max)
```

**Preferred formula (matches your wording closest):**

```text
# Free capacity shrinks as tile fills → bonus fades near max
add = base + mult * already * (1 - already / trail_max)
new = min(already + add, trail_max)
```

| already | add (base=2, mult=0.5, max=100) | intuition |
|---------|----------------------------------|-----------|
| 0 | 2 | bare ground: base only |
| 20 | 2 + 8 = 10 | used path reinforced hard |
| 50 | 2 + 12.5 = 14.5 | still strong |
| 90 | 2 + 4.5 = 6.5 | approaching max |
| 100 | 2 → clamped to 0 net if at max | full; no further growth |

Bare ground still gets **full base**; busy tiles get **more until near max**.

**Alternative (if we want stricter “at least base” even at max):** allow tiny base until cap only:

```text
add = min(base + mult * already * (1 - fill), trail_max - already)
```

Always net ≥ 0 and never exceeds max.

### 3. Evaporation that scales with strength (keeps “strong lasts longer”)

Keep **absolute** loss so time-to-zero grows with value, but scale rate so max is usable:

```text
# Lifetime at full strength ≈ 1 / frac  (e.g. frac=0.15 → ~6–7 s at max if no reinforce)
trail_evap_units = trail_evap_frac * trail_max   # e.g. 0.12 * 100 = 12 units/s
cell = max(0, cell - trail_evap_units * dt)
```

- Weak tile (10): gone in ~0.8 s  
- Full tile (100): gone in ~8 s without reinforce  
- Busy path: re-entries keep it near max  

Optional small fractional term is **not** required if cap + absolute evap are tuned.

### 4. Rescale defaults (cleaner UI numbers)

| Param | Current | Proposed |
|-------|---------|----------|
| `trail_max` | — | **100** |
| `deposit_amount` (base per tile enter) | 48 | **2.0** |
| `deposit_existing_multiplier` | 0.35 | **0.5** (on saturating formula) |
| `trail_evaporation` | 4 abs units/s | replace with `trail_evap_frac: 0.12` of max, or keep abs `12` if max=100 |
| `floor` | 0.03 | **0.05** |
| `spread_rate` | 0.70 | keep ~0.5–0.7 |

Numbers on **N** overlay stay readable (0–100).

### 5. Spread stays as-is

Mass-conserving neighbour push is fine; **clamp after spread** so inflow cannot exceed `trail_max`.

### 6. Follow behaviour unchanged

`trail_follow_steering` already uses **relative** L/R samples. Working in 0–100 does not change follow logic; only retune `trail_follow_min` if needed (e.g. `0.5` on new scale).

### 7. Sidebar / config

- Add slider `pheromone.trail_max` (10–500)  
- Retarget deposit / evap slider ranges for 0–100 scale  
- Document formula in config comments  
- Save/reset continue to work as now  

---

## Files to change

| File | Change |
|------|--------|
| `src/sim/grid.py` | `deposit_on_cells` saturating formula + `clamp` helper; clamp after spread in `step` |
| `src/agents/ant.py` | Pass `trail_max` / use grid API only (no formula change if all in grid) |
| `src/sim/world.py` | Pass `trail_max` / `trail_evap_frac` into `pheromones.step` |
| `config/default.yaml` | New defaults + comments |
| `src/render/sidebar.py` | Sliders for `trail_max`, updated ranges |
| `src/render/draw.py` | Optional: absolute heat scale uses `trail_max` instead of hard-coded 40 |

**Reuse:** `last_trail_cell` enter-once logic; `cells_along_segment`; bilateral follow; stuck teleport — **no change**.

---

## Explicit non-goals

- No “food gone” special decay  
- No continuous per-frame deposit while standing  
- No ant “knows” about depletion  
- No change to home-tile unload  

---

## Verification

1. **Unit:** deposit on empty → `base`; re-enter same path many times → value **approaches but never exceeds** `trail_max`.  
2. **No stack volcano:** ant stuck 10s then teleport — tile value does not climb unboundedly (enter-once already; cap is belt-and-suspenders).  
3. **Behaviour:** 20+ ants still form a visible home↔food path; unused branch fades within a few seconds.  
4. **Numbers (N):** typical busy cell ~50–100; empty path ~0–5.  
5. **Sidebar:** change `trail_max` / deposit live; still sensible.  

---

## Summary

| Keep | Change |
|------|--------|
| Enter-once lay | Saturating `base + mult×existing×(1−fill)` |
| Base always applied | Hard cap `trail_max` (default 100) |
| Used path stronger | Absolute evap scaled to max (strong lasts longer, weak dies fast) |
| Spread + follow | Rescale defaults so HUD numbers stay small |

This preserves the ecology of recruitment trails without 4–5 digit tiles.

# Simple pheromone model

## Backup (before deposit simplify)

`../Ant-Simulator-backup-deposit-20260724-1608/`

Earlier full complex backup: `../Ant-Simulator-backup-20260724-1531/`

---

## Design (what we want)

1. Ant finds food, carries load home.  
2. On the way, drops a **fixed** chemical amount on each **new tile**.  
3. Other ants sense that chemical and tend to walk the same path.  
4. They reinforce by dropping the **same** amount again.  
5. **Wind** removes chemical every second.  
6. Food gone → nobody deposits → trail fades away.

No global colony brain.

---

## Deposit (current — deliberately minimal)

```
while carrying and enter new tile:
    trail[tile] += deposit_amount
```

| Removed | Why |
|---------|-----|
| `deposit_existing_multiplier` | Reinforce = more ants, not a formula |
| `deposit_max_factor` | Evaporation + floor already limit buildup |
| `deposit_boost_factor` / `deposit_boost_tiles` | Extra path-shaped complexity |

Still **enter-once** per tile (no volcano while standing still).

---

## Environment (current)

| Piece | Role |
|-------|------|
| `deposit_amount` | Drop size per tile |
| `trail_evaporation` | Base wind: units/s off every active trail tile |
| `trail_high_threshold` | Above this, extra fade on the excess |
| `trail_high_fade_rate` | Fraction of (value − threshold) removed per second |
| `diffusion` | Optional mild blur (0 = pure walked tiles) |
| `floor` | Values below this → 0 |
| Nest emit + nest fade | Homing only |

**High peaks:** when many ants stack trail (big numbers), excess above the
threshold crashes fast once deposits stop — faster than base wind alone.

---

## Knobs left (sidebar → Pheromone)

- Deposit amount  
- Trail fade (units/s)  
- Trail diffusion  
- Trail floor  
- Nest emit / nest fade  

---

## Tests

```bash
python -m tests.run_trail_test
```

Natural food empty → strong trail → fade. Screenshots in `debug screenshots/auto/`.

# Ant Simulator — project rules

This repo is on GitHub: `https://github.com/cheetahrunout/Ant-Simulator` (`origin` / `main`).

## Always use git

- After finishing a coherent piece of work, **commit** it. Do not leave finished features sitting only in the working tree.
- After a successful commit, **`git push origin main`** unless the user says to keep it local.
- Write short, complete-sentence commit messages that say what changed and why.
- Before committing, review `git status` and `git diff`. Do not stage junk: `__pycache__/`, `debug screenshots/`, `config/saved.yaml`, videos, or other `.gitignore`d files.
- Do not force-push, amend published commits, or rewrite history unless the user explicitly asks.
- Do not create extra branches unless the user asks. Default branch is `main`.
- If push fails on auth, say so and give the exact command — do not invent tokens.

## How to run

```bash
python -m src.main
```

Optional configs: `config/test_small.yaml`, `config/test_butcher.yaml`.

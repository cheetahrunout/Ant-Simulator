"""Load YAML config with a few safe coercions."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Mapping

import yaml


def _eval_numbers(obj: Any) -> Any:
    """Allow simple expressions like '1/60' in YAML strings."""
    if isinstance(obj, dict):
        return {k: _eval_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_eval_numbers(v) for v in obj]
    if isinstance(obj, str):
        s = obj.strip()
        if s and all(c in "0123456789.+-*/() eE" for c in s):
            try:
                return float(eval(s, {"__builtins__": {}}, {"math": math}))  # noqa: S307
            except Exception:
                return obj
    return obj


def load_config(path: Path | str) -> Dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _eval_numbers(data)


def deep_merge(base: Dict[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    """Recursively merge override into base (mutates base, returns it)."""
    for key, val in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(val, Mapping)
        ):
            deep_merge(base[key], val)  # type: ignore[arg-type]
        else:
            base[key] = val
    return base


def load_config_stack(
    default_path: Path | str,
    saved_path: Path | str | None = None,
    *overrides: Path | str,
) -> Dict[str, Any]:
    """
    Load default.yaml, then optional override YAMLs (left→right), then saved.

    Example::

        load_config_stack("config/default.yaml", None, "config/test_small.yaml")
    """
    cfg = load_config(default_path)
    for path in overrides:
        if path is None:
            continue
        p = Path(path)
        if p.is_file():
            deep_merge(cfg, load_config(p))
    if saved_path is not None:
        sp = Path(saved_path)
        if sp.is_file():
            deep_merge(cfg, load_config(sp))
    return cfg


def save_yaml(path: Path | str, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("# Auto-saved live config (sidebar Save). Merged on next launch.\n")
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

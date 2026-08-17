"""Screenshot helpers for manual F12 capture and automated tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import pygame

PathLike = Union[str, Path]


def default_shot_dir(project_root: Path) -> Path:
    d = project_root / "debug screenshots" / "auto"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_screenshot(
    surface: pygame.Surface,
    path: PathLike,
    *,
    make_parents: bool = True,
) -> Path:
    """Write ``surface`` to PNG (or whatever extension pygame supports)."""
    path = Path(path)
    if make_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, str(path))
    return path


def timestamped_path(
    directory: PathLike,
    prefix: str = "shot",
    ext: str = ".png",
) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return Path(directory) / f"{prefix}_{stamp}{ext}"


def capture(
    surface: pygame.Surface,
    directory: PathLike,
    prefix: str = "shot",
    path: Optional[PathLike] = None,
) -> Path:
    """Save to ``path`` or a timestamped file under ``directory``."""
    if path is None:
        path = timestamped_path(directory, prefix=prefix)
    return save_screenshot(surface, path)

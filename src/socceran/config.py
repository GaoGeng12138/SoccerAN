"""Load and resolve project configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config.yaml"


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    with cfg_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Resolve relative paths against repo root
    for key in ("raw_dir", "fixtures_dir"):
        if key in cfg.get("data", {}):
            p = Path(cfg["data"][key])
            if not p.is_absolute():
                cfg["data"][key] = str(ROOT / p)
    for key in ("elo_state", "poisson_state"):
        if key in cfg.get("paths", {}):
            p = Path(cfg["paths"][key])
            if not p.is_absolute():
                cfg["paths"][key] = str(ROOT / p)
    return cfg


def current_season_code(cfg: dict[str, Any] | None = None) -> str:
    """Return football-data.co.uk season folder, e.g. '2526' for 2025-26."""
    if cfg and cfg.get("seasons", {}).get("current"):
        return str(cfg["seasons"]["current"])
    # Heuristic: European season starts ~August. Use UTC+8 "today" via local date.
    from datetime import datetime, timezone, timedelta

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    year = now.year
    # Before August → still previous season (e.g. May 2026 → 2526)
    start = year if now.month >= 8 else year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def season_codes(cfg: dict[str, Any], n: int | None = None) -> list[str]:
    """List of recent season codes ending at current (oldest first)."""
    n = n if n is not None else int(cfg.get("seasons", {}).get("count", 3))
    cur = current_season_code(cfg)
    start_yy = int(cur[:2])
    codes = []
    for i in range(n - 1, -1, -1):
        a = (start_yy - i) % 100
        b = (a + 1) % 100
        codes.append(f"{a:02d}{b:02d}")
    return codes

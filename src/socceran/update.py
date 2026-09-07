"""Fetch (optional) + fit Elo + Poisson and persist state."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from socceran.config import load_config
from socceran.data import fetch_all, fetch_fixtures, load_matches
from socceran.elo import EloSystem
from socceran.poisson import PoissonModel

logger = logging.getLogger(__name__)


def update(
    cfg: dict[str, Any] | None = None,
    *,
    do_fetch: bool = True,
    force_fetch: bool = False,
) -> tuple[EloSystem, PoissonModel, int]:
    """Run pipeline update. Returns (elo, poisson, n_matches)."""
    cfg = cfg or load_config()
    if do_fetch:
        paths = fetch_all(cfg, force=force_fetch)
        logger.info("fetched/cached %d files", len(paths))
        fx = fetch_fixtures(cfg, force=force_fetch)
        logger.info("fixtures cached %d files", len(fx))

    matches = load_matches(cfg)
    n = len(matches)
    logger.info("loaded %d matches", n)

    elo = EloSystem.from_config(cfg)
    if n:
        elo.fit(matches)
    elo.save(cfg["paths"]["elo_state"])
    logger.info("wrote Elo state → %s (%d teams)", cfg["paths"]["elo_state"], len(elo.ratings))

    model = PoissonModel.from_config(cfg)
    if n:
        model.fit(matches)
    model.save(cfg["paths"]["poisson_state"])
    logger.info("wrote Poisson state → %s", cfg["paths"]["poisson_state"])
    return elo, model, n

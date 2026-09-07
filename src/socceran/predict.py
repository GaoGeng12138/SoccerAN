"""Generate match predictions from fitted Elo + Poisson models."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from socceran.config import load_config
from socceran.data import load_fixtures, load_matches
from socceran.elo import EloSystem
from socceran.names import enrich_zh_columns, to_zh, use_chinese_names
from socceran.poisson import PoissonModel

logger = logging.getLogger(__name__)


def _today_tag() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y%m%d")


def _pairs_from_recent(matches: pd.DataFrame, n_per_league: int = 10) -> pd.DataFrame:
    """Use most recent completed matches as prediction rows (backtest-style)."""
    rows = []
    for league, g in matches.groupby("league"):
        tail = g.sort_values("date").tail(n_per_league)
        rows.append(tail)
    if not rows:
        return matches.iloc[0:0].copy()
    return pd.concat(rows, ignore_index=True)


def _round_robin_next(matches: pd.DataFrame) -> pd.DataFrame:
    """Build hypothetical next-home fixtures when no real schedule exists."""
    out_rows = []
    for league, g in matches.groupby("league"):
        teams = sorted(set(g["home"]) | set(g["away"]))
        if len(teams) < 2:
            continue
        g2 = g.sort_values("date")
        for team in teams:
            last = g2[(g2["home"] == team) | (g2["away"] == team)].tail(1)
            if last.empty:
                continue
            row = last.iloc[0]
            opp = row["away"] if row["home"] == team else row["home"]
            if opp == team:
                opp = next(t for t in teams if t != team)
            out_rows.append(
                {
                    "date": pd.Timestamp(_today_tag()),
                    "league": league,
                    "home": team,
                    "away": opp,
                    "fthg": None,
                    "ftag": None,
                    "kind": "hypothetical_next",
                }
            )
    return pd.DataFrame(out_rows)


def _upcoming_fixtures(cfg: dict[str, Any], matches: pd.DataFrame) -> pd.DataFrame | None:
    """Load real upcoming fixtures if enabled and non-empty."""
    fx_cfg = cfg.get("fixtures") or {}
    if not fx_cfg.get("prefer_upcoming", True):
        return None
    fixtures = load_fixtures(cfg)
    if fixtures.empty:
        return None
    # Drop fixtures whose teams are totally unknown to the model history (optional soft filter)
    known = set(matches["home"]) | set(matches["away"])
    if known:
        mask = fixtures["home"].isin(known) | fixtures["away"].isin(known)
        # Keep all if filter would wipe everything (name mismatch across sources)
        if mask.any():
            fixtures = fixtures.loc[mask].copy()
    fixtures = fixtures.copy()
    fixtures["kind"] = "upcoming"
    return fixtures


def predict(
    cfg: dict[str, Any] | None = None,
    *,
    elo: EloSystem | None = None,
    model: PoissonModel | None = None,
    matches: pd.DataFrame | None = None,
    mode: str = "recent",  # recent | hypothetical | upcoming
) -> pd.DataFrame:
    cfg = cfg or load_config()
    if matches is None:
        matches = load_matches(cfg)
    if elo is None:
        elo_path = Path(cfg["paths"]["elo_state"])
        if not elo_path.exists():
            raise FileNotFoundError(f"Elo state missing: {elo_path}. Run `socceran update` first.")
        elo = EloSystem.load(elo_path)
    if model is None:
        po_path = Path(cfg["paths"]["poisson_state"])
        if not po_path.exists():
            raise FileNotFoundError(f"Poisson state missing: {po_path}. Run `socceran update` first.")
        model = PoissonModel.load(po_path)

    if matches.empty:
        return pd.DataFrame()

    fixtures: pd.DataFrame
    if mode == "upcoming":
        up = _upcoming_fixtures(cfg, matches)
        if up is None or up.empty:
            logger.warning(
                "predict --mode upcoming: no fixtures in data/fixtures/; "
                "falling back to recent completed"
            )
            fixtures = _pairs_from_recent(matches, n_per_league=8)
            fixtures = fixtures.copy()
            fixtures["kind"] = "recent_completed"
        else:
            fixtures = up
    elif mode == "hypothetical":
        # Still prefer real upcoming when available
        up = _upcoming_fixtures(cfg, matches)
        if up is not None and not up.empty:
            logger.info("using %d upcoming fixtures (prefer over hypothetical)", len(up))
            fixtures = up
        else:
            logger.info(
                "no upcoming fixtures cached; using hypothetical_next "
                "(run `socceran fixtures` to refresh)"
            )
            fixtures = _round_robin_next(matches)
    else:
        # default "recent": prefer real upcoming, else recent completed
        up = _upcoming_fixtures(cfg, matches)
        if up is not None and not up.empty:
            logger.info("using %d upcoming fixtures for predictions", len(up))
            fixtures = up
        else:
            logger.info(
                "no upcoming fixtures in data/fixtures/; "
                "predicting recent completed matches instead "
                "(run `python -m socceran fixtures`)"
            )
            fixtures = _pairs_from_recent(matches, n_per_league=8)
            fixtures = fixtures.copy()
            fixtures["kind"] = "recent_completed"

    rows = []
    add_zh = use_chinese_names(cfg)
    for r in fixtures.itertuples(index=False):
        pred = model.predict_match(r.home, r.away, r.league, elo=elo)
        rows.append(
            {
                "date": str(getattr(r, "date", "")),
                "league": r.league,
                "home": r.home,
                "away": r.away,
                **({"home_zh": to_zh(r.home), "away_zh": to_zh(r.away)} if add_zh else {}),
                "kind": getattr(r, "kind", "unknown"),
                "elo_home": elo.get(r.home, r.league),
                "elo_away": elo.get(r.away, r.league),
                "xg_home": pred["xg_home"],
                "xg_away": pred["xg_away"],
                "p_home": pred["p_home"],
                "p_draw": pred["p_draw"],
                "p_away": pred["p_away"],
                "fthg": getattr(r, "fthg", None),
                "ftag": getattr(r, "ftag", None),
            }
        )
    return pd.DataFrame(rows)


def write_predictions(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> tuple[Path, Path]:
    cfg = cfg or load_config()
    tag = _today_tag()
    csv_tmpl = cfg["paths"]["predictions_csv"]
    json_tmpl = cfg["paths"]["predictions_json"]
    csv_path = Path(str(csv_tmpl).replace("{date}", tag))
    json_path = Path(str(json_tmpl).replace("{date}", tag))
    if not csv_path.is_absolute():
        from socceran.config import ROOT

        csv_path = ROOT / csv_path
        json_path = ROOT / json_path
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df = enrich_zh_columns(df, cfg=cfg)
    df.to_csv(csv_path, index=False)
    payload = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "n": len(df),
        "predictions": df.to_dict(orient="records"),
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return csv_path, json_path

"""Generate match predictions from fitted Elo + Poisson models."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from socceran.config import load_config
from socceran.data import load_matches
from socceran.elo import EloSystem
from socceran.poisson import PoissonModel


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
    """Build hypothetical next-home fixtures: each team hosts median opponent by Elo gap.

    Fallback when no future fixtures exist in CSVs: emit one row per team as home
    vs the league median-Elo opponent (or last away opponent).
    """
    out_rows = []
    for league, g in matches.groupby("league"):
        teams = sorted(set(g["home"]) | set(g["away"]))
        if len(teams) < 2:
            continue
        # last known opponent for each team
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


def predict(
    cfg: dict[str, Any] | None = None,
    *,
    elo: EloSystem | None = None,
    model: PoissonModel | None = None,
    matches: pd.DataFrame | None = None,
    mode: str = "recent",  # recent | hypothetical
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

    if mode == "hypothetical":
        fixtures = _round_robin_next(matches)
    else:
        fixtures = _pairs_from_recent(matches, n_per_league=8)
        fixtures = fixtures.copy()
        fixtures["kind"] = "recent_completed"

    rows = []
    for r in fixtures.itertuples(index=False):
        pred = model.predict_match(r.home, r.away, r.league, elo=elo)
        rows.append(
            {
                "date": str(getattr(r, "date", "")),
                "league": r.league,
                "home": r.home,
                "away": r.away,
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
    # paths may be absolute after load_config; format date placeholder
    csv_path = Path(str(csv_tmpl).replace("{date}", tag))
    json_path = Path(str(json_tmpl).replace("{date}", tag))
    if not csv_path.is_absolute():
        from socceran.config import ROOT

        csv_path = ROOT / csv_path
        json_path = ROOT / json_path
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    payload = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "n": len(df),
        "predictions": df.to_dict(orient="records"),
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return csv_path, json_path

"""Chronological Elo ratings for football matches."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def expected_score(rating_a: float, rating_b: float) -> float:
    """P(A beats B) under Elo logistic."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def result_score(home_goals: int, away_goals: int) -> tuple[float, float]:
    """Return (home_score, away_score) in {0, 0.5, 1}."""
    if home_goals > away_goals:
        return 1.0, 0.0
    if home_goals < away_goals:
        return 0.0, 1.0
    return 0.5, 0.5


@dataclass
class EloSystem:
    initial: float = 1500.0
    k: float = 20.0
    home_advantage: float = 65.0
    scope: str = "per_league"  # or "global"
    ratings: dict[str, float] = field(default_factory=dict)
    history_rows: list[dict[str, Any]] = field(default_factory=list)

    def _key(self, team: str, league: str) -> str:
        if self.scope == "global":
            return team
        return f"{league}::{team}"

    def get(self, team: str, league: str = "") -> float:
        return self.ratings.get(self._key(team, league), self.initial)

    def update_match(
        self,
        home: str,
        away: str,
        fthg: int,
        ftag: int,
        league: str = "",
        date: Any = None,
    ) -> dict[str, Any]:
        """Update ratings after one match; return pre/post snapshot."""
        rh = self.get(home, league)
        ra = self.get(away, league)
        # Home advantage applied only to expectation
        eh = expected_score(rh + self.home_advantage, ra)
        ea = 1.0 - eh
        sh, sa = result_score(fthg, ftag)
        new_rh = rh + self.k * (sh - eh)
        new_ra = ra + self.k * (sa - ea)
        self.ratings[self._key(home, league)] = new_rh
        self.ratings[self._key(away, league)] = new_ra
        row = {
            "date": str(date) if date is not None else None,
            "league": league,
            "home": home,
            "away": away,
            "fthg": int(fthg),
            "ftag": int(ftag),
            "elo_home_pre": rh,
            "elo_away_pre": ra,
            "elo_home_post": new_rh,
            "elo_away_post": new_ra,
            "p_home_win_elo": eh,
        }
        self.history_rows.append(row)
        return row

    def fit(self, matches: pd.DataFrame) -> "EloSystem":
        """Process matches in chronological order."""
        df = matches.sort_values(["date", "league", "home"]).reset_index(drop=True)
        for row in df.itertuples(index=False):
            self.update_match(
                home=row.home,
                away=row.away,
                fthg=int(row.fthg),
                ftag=int(row.ftag),
                league=getattr(row, "league", ""),
                date=getattr(row, "date", None),
            )
        return self

    def table(self, league: str | None = None) -> pd.DataFrame:
        rows = []
        for key, rating in self.ratings.items():
            if self.scope == "per_league" and "::" in key:
                lg, team = key.split("::", 1)
            else:
                lg, team = "", key
            if league is not None and lg != league:
                continue
            rows.append({"league": lg, "team": team, "elo": rating})
        return pd.DataFrame(rows).sort_values(["league", "elo"], ascending=[True, False])

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial": self.initial,
            "k": self.k,
            "home_advantage": self.home_advantage,
            "scope": self.scope,
            "ratings": self.ratings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EloSystem":
        return cls(
            initial=float(data.get("initial", 1500)),
            k=float(data.get("k", 20)),
            home_advantage=float(data.get("home_advantage", 65)),
            scope=str(data.get("scope", "per_league")),
            ratings={k: float(v) for k, v in data.get("ratings", {}).items()},
        )

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "EloSystem":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "EloSystem":
        e = cfg.get("elo", {})
        return cls(
            initial=float(e.get("initial", 1500)),
            k=float(e.get("k", 20)),
            home_advantage=float(e.get("home_advantage", 65)),
            scope=str(e.get("scope", "per_league")),
        )


def elo_to_xg(
    elo_home: float,
    elo_away: float,
    home_advantage: float = 65.0,
    base_xg: float = 1.35,
    scale: float = 0.0035,
) -> tuple[float, float]:
    """Map Elo gap to rough expected goals (simple logistic-ish scale)."""
    gap = (elo_home + home_advantage) - elo_away
    # Symmetric around base_xg
    xg_h = max(0.2, base_xg + scale * gap)
    xg_a = max(0.2, base_xg - scale * gap)
    return xg_h, xg_a

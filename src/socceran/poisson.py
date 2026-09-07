"""Independent Poisson match model (attack/defense or Elo-derived xG)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import poisson

from socceran.elo import EloSystem, elo_to_xg


def poisson_1x2(xg_home: float, xg_away: float, max_goals: int = 10) -> dict[str, float]:
    """Independent Poisson P(H), P(D), P(A) truncated at max_goals."""
    ph = poisson.pmf(np.arange(0, max_goals + 1), mu=max(xg_home, 1e-9))
    pa = poisson.pmf(np.arange(0, max_goals + 1), mu=max(xg_away, 1e-9))
    # Outer product score matrix
    mat = np.outer(ph, pa)
    p_home = float(np.tril(mat, k=-1).sum())
    p_draw = float(np.trace(mat))
    p_away = float(np.triu(mat, k=1).sum())
    s = p_home + p_draw + p_away
    if s <= 0:
        return {"p_home": 1 / 3, "p_draw": 1 / 3, "p_away": 1 / 3, "xg_home": xg_home, "xg_away": xg_away}
    return {
        "p_home": p_home / s,
        "p_draw": p_draw / s,
        "p_away": p_away / s,
        "xg_home": float(xg_home),
        "xg_away": float(xg_away),
    }


@dataclass
class PoissonModel:
    """Team attack/defense strengths estimated from historical goals."""

    mode: str = "goals"  # goals | elo
    prior_strength: float = 8.0
    home_attack_boost: float = 1.15
    max_goals: int = 10
    league_avg_home: dict[str, float] = field(default_factory=dict)
    league_avg_away: dict[str, float] = field(default_factory=dict)
    attack: dict[str, float] = field(default_factory=dict)  # key: league::team
    defense: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def _key(league: str, team: str) -> str:
        return f"{league}::{team}"

    def fit(self, matches: pd.DataFrame) -> "PoissonModel":
        """Estimate attack/defense vs league averages with simple shrinkage."""
        if matches.empty:
            return self
        for league, g in matches.groupby("league"):
            avg_h = float(g["fthg"].mean())
            avg_a = float(g["ftag"].mean())
            self.league_avg_home[league] = avg_h if avg_h > 0 else 1.3
            self.league_avg_away[league] = avg_a if avg_a > 0 else 1.1

            teams = sorted(set(g["home"]) | set(g["away"]))
            for team in teams:
                home_games = g[g["home"] == team]
                away_games = g[g["away"] == team]
                n_h = len(home_games)
                n_a = len(away_games)
                # Goals scored / conceded
                gf_h = float(home_games["fthg"].sum()) if n_h else 0.0
                ga_h = float(home_games["ftag"].sum()) if n_h else 0.0
                gf_a = float(away_games["ftag"].sum()) if n_a else 0.0
                ga_a = float(away_games["fthg"].sum()) if n_a else 0.0
                n = n_h + n_a
                prior = self.prior_strength
                # Attack: goals scored relative to opp context averages
                scored = gf_h + gf_a
                expected_scored = n_h * avg_h + n_a * avg_a
                att = (scored + prior * 1.0) / (expected_scored + prior) if (expected_scored + prior) else 1.0
                conceded = ga_h + ga_a
                expected_conc = n_h * avg_a + n_a * avg_h
                deff = (conceded + prior * 1.0) / (expected_conc + prior) if (expected_conc + prior) else 1.0
                key = self._key(league, team)
                self.attack[key] = float(att)
                self.defense[key] = float(deff)
        return self

    def expected_goals(
        self,
        home: str,
        away: str,
        league: str,
        elo: EloSystem | None = None,
    ) -> tuple[float, float]:
        if self.mode == "elo" and elo is not None:
            return elo_to_xg(
                elo.get(home, league),
                elo.get(away, league),
                home_advantage=elo.home_advantage,
            )
        avg_h = self.league_avg_home.get(league, 1.35)
        avg_a = self.league_avg_away.get(league, 1.15)
        hk = self._key(league, home)
        ak = self._key(league, away)
        att_h = self.attack.get(hk, 1.0)
        def_h = self.defense.get(hk, 1.0)
        att_a = self.attack.get(ak, 1.0)
        def_a = self.defense.get(ak, 1.0)
        xg_h = avg_h * att_h * def_a * self.home_attack_boost / 1.0
        # Away uses away average; mild inverse of home boost
        xg_a = avg_a * att_a * def_h
        return max(0.15, float(xg_h)), max(0.15, float(xg_a))

    def predict_match(
        self,
        home: str,
        away: str,
        league: str,
        elo: EloSystem | None = None,
    ) -> dict[str, float]:
        xg_h, xg_a = self.expected_goals(home, away, league, elo=elo)
        return poisson_1x2(xg_h, xg_a, max_goals=self.max_goals)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "prior_strength": self.prior_strength,
            "home_attack_boost": self.home_attack_boost,
            "max_goals": self.max_goals,
            "league_avg_home": self.league_avg_home,
            "league_avg_away": self.league_avg_away,
            "attack": self.attack,
            "defense": self.defense,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PoissonModel":
        return cls(
            mode=str(data.get("mode", "goals")),
            prior_strength=float(data.get("prior_strength", 8.0)),
            home_attack_boost=float(data.get("home_attack_boost", 1.15)),
            max_goals=int(data.get("max_goals", 10)),
            league_avg_home={k: float(v) for k, v in data.get("league_avg_home", {}).items()},
            league_avg_away={k: float(v) for k, v in data.get("league_avg_away", {}).items()},
            attack={k: float(v) for k, v in data.get("attack", {}).items()},
            defense={k: float(v) for k, v in data.get("defense", {}).items()},
        )

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "PoissonModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "PoissonModel":
        p = cfg.get("poisson", {})
        return cls(
            mode=str(p.get("mode", "goals")),
            prior_strength=float(p.get("prior_strength", 8.0)),
            home_attack_boost=float(p.get("home_attack_boost", 1.15)),
            max_goals=int(p.get("max_goals", 10)),
        )

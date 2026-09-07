"""Fetch and load football-data.co.uk CSV season files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from socceran.config import load_config, season_codes

logger = logging.getLogger(__name__)

# football-data.co.uk date formats vary by season
DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y")


def _parse_dates(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, format=DATE_FORMATS[0], errors="coerce")
    if parsed.isna().any():
        alt = pd.to_datetime(series, format=DATE_FORMATS[1], errors="coerce")
        parsed = parsed.fillna(alt)
    # last resort: dayfirst
    if parsed.isna().any():
        alt = pd.to_datetime(series, dayfirst=True, errors="coerce")
        parsed = parsed.fillna(alt)
    return parsed


def csv_url(base_url: str, season: str, league_code: str) -> str:
    return f"{base_url.rstrip('/')}/{season}/{league_code}.csv"


def fetch_league_season(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any] | None = None,
    force: bool = False,
) -> Path | None:
    """Download one CSV into data/raw/{league}_{season}.csv. Returns path or None."""
    cfg = cfg or load_config()
    raw_dir = Path(cfg["data"]["raw_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{league_code}_{season}.csv"
    if dest.exists() and dest.stat().st_size > 0 and not force:
        logger.info("cached %s", dest.name)
        return dest

    url = csv_url(cfg["data"]["base_url"], season, league_code)
    logger.info("fetching %s → %s", url, dest.name)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; SoccerAN/0.1; +https://github.com/GaoGeng12138/SoccerAN)"
        ),
        "Accept": "text/csv,text/plain,*/*",
    }
    try:
        resp = None
        for attempt in range(3):
            resp = requests.get(url, timeout=60, headers=headers)
            if resp.status_code == 503:
                import time
                wait = int(resp.headers.get("Retry-After", 5))
                wait = min(max(wait, 2), 30)
                logger.warning("HTTP 503 for %s; retry in %ss (%d/3)", url, wait, attempt + 1)
                time.sleep(wait)
                continue
            break
        assert resp is not None
        body = resp.content
        if resp.status_code != 200 or not body or b"<html" in body[:200].lower():
            logger.warning("skip %s (HTTP %s or empty/HTML)", url, resp.status_code)
            return None
        # basic sanity: CSV should have commas / Date header
        if b"," not in body[:500]:
            logger.warning("skip %s (not CSV-like)", url)
            return None
        dest.write_bytes(body)
        return dest
    except requests.RequestException as exc:
        logger.warning("fetch failed %s: %s", url, exc)
        return None


def fetch_all(cfg: dict[str, Any] | None = None, force: bool = False) -> list[Path]:
    """Fetch last N seasons for all configured leagues."""
    cfg = cfg or load_config()
    seasons = season_codes(cfg)
    paths: list[Path] = []
    for code in cfg["leagues"]:
        for season in seasons:
            p = fetch_league_season(code, season, cfg=cfg, force=force)
            if p is not None:
                paths.append(p)
    return paths


def _normalize_frame(df: pd.DataFrame, league: str, season: str, cfg: dict[str, Any]) -> pd.DataFrame:
    cols = cfg["data"]
    required = [cols["date_col"], cols["home_col"], cols["away_col"], cols["fthg_col"], cols["ftag_col"]]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns {missing} in {league}/{season}")

    out = pd.DataFrame(
        {
            "date": _parse_dates(df[cols["date_col"]]),
            "home": df[cols["home_col"]].astype(str).str.strip(),
            "away": df[cols["away_col"]].astype(str).str.strip(),
            "fthg": pd.to_numeric(df[cols["fthg_col"]], errors="coerce"),
            "ftag": pd.to_numeric(df[cols["ftag_col"]], errors="coerce"),
        }
    )
    if cols["ftr_col"] in df.columns:
        out["ftr"] = df[cols["ftr_col"]].astype(str).str.strip()
    else:
        out["ftr"] = None
    out["league"] = league
    out["season"] = season
    out = out.dropna(subset=["date", "home", "away", "fthg", "ftag"])
    out["fthg"] = out["fthg"].astype(int)
    out["ftag"] = out["ftag"].astype(int)
    return out


def load_matches(
    cfg: dict[str, Any] | None = None,
    leagues: list[str] | None = None,
    paths: list[Path] | None = None,
) -> pd.DataFrame:
    """Load and concatenate cached CSVs into a normalized match table."""
    cfg = cfg or load_config()
    raw_dir = Path(cfg["data"]["raw_dir"])
    if paths is None:
        patterns = []
        league_list = leagues or list(cfg["leagues"].keys())
        for code in league_list:
            patterns.extend(sorted(raw_dir.glob(f"{code}_*.csv")))
        paths = patterns

    frames: list[pd.DataFrame] = []
    for path in paths:
        name = path.stem  # e.g. E0_2425
        parts = name.split("_", 1)
        if len(parts) != 2:
            continue
        league, season = parts
        try:
            df = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
        try:
            frames.append(_normalize_frame(df, league, season, cfg))
        except ValueError as exc:
            logger.warning("%s: %s", path.name, exc)

    if not frames:
        return pd.DataFrame(
            columns=["date", "home", "away", "fthg", "ftag", "ftr", "league", "season"]
        )

    all_m = pd.concat(frames, ignore_index=True)
    all_m = all_m.sort_values(["date", "league", "home"]).reset_index(drop=True)
    return all_m


def load_sample_fixture(path: Path | str) -> pd.DataFrame:
    """Load a tiny offline fixture CSV (tests)."""
    path = Path(path)
    raw = pd.read_csv(path)
    # Accept either football-data names or already-normalized names
    colmap = {
        "Date": "date",
        "HomeTeam": "home",
        "AwayTeam": "away",
        "FTHG": "fthg",
        "FTAG": "ftag",
        "FTR": "ftr",
    }
    df = raw.rename(columns={k: v for k, v in colmap.items() if k in raw.columns})
    date_src = df["date"] if "date" in df.columns else raw.iloc[:, 0]
    out = pd.DataFrame(
        {
            "date": _parse_dates(date_src),
            "home": df["home"].astype(str).str.strip(),
            "away": df["away"].astype(str).str.strip(),
            "fthg": pd.to_numeric(df["fthg"], errors="coerce").astype(int),
            "ftag": pd.to_numeric(df["ftag"], errors="coerce").astype(int),
            "ftr": df["ftr"].astype(str).str.strip() if "ftr" in df.columns else None,
            "league": df["league"] if "league" in df.columns else "E0",
            "season": df["season"] if "season" in df.columns else "0000",
        }
    )
    return out

"""Fetch and load match results with multi-source fallbacks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from socceran.config import load_config, season_codes
from socceran.sources import (
    MATCH_COLUMNS,
    empty_matches,
    fetch_england_mirror,
    fetch_football_datasets,
    fetch_jleague_finished,
    fetch_jleague_fixtures,
    fetch_kleague_finished,
    fetch_kleague_fixtures,
    fetch_openfootball_finished,
    fetch_openfootball_fixtures,
    fetch_openligadb_finished,
    fetch_openligadb_fixtures,
)

logger = logging.getLogger(__name__)

# football-data.co.uk date formats vary by season
DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y")

USER_AGENT = (
    "Mozilla/5.0 (compatible; SoccerAN/0.1; +https://github.com/GaoGeng12138/SoccerAN)"
)


def _parse_dates(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, format=DATE_FORMATS[0], errors="coerce")
    if parsed.isna().any():
        alt = pd.to_datetime(series, format=DATE_FORMATS[1], errors="coerce")
        parsed = parsed.fillna(alt)
    # ISO / OpenLigaDB-style timestamps
    if parsed.isna().any():
        alt = pd.to_datetime(series, format="%Y-%m-%d %H:%M:%S", errors="coerce")
        parsed = parsed.fillna(alt)
    if parsed.isna().any():
        alt = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")
        parsed = parsed.fillna(alt)
    if parsed.isna().any():
        alt = pd.to_datetime(series, dayfirst=True, errors="coerce")
        parsed = parsed.fillna(alt)
    if parsed.isna().any():
        alt = pd.to_datetime(series, errors="coerce")
        parsed = parsed.fillna(alt)
    return parsed


def csv_url(base_url: str, season: str, league_code: str) -> str:
    return f"{base_url.rstrip('/')}/{season}/{league_code}.csv"


def _sources_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg.get("sources") or {}


def _source_enabled(cfg: dict[str, Any], name: str) -> bool:
    block = _sources_cfg(cfg).get(name) or {}
    return bool(block.get("enabled", True))


def _source_order(cfg: dict[str, Any]) -> list[str]:
    order = _sources_cfg(cfg).get("order")
    if order:
        return list(order)
    return ["football_data", "jleague", "kleague", "openfootball", "football_datasets", "openligadb", "england_mirror"]


def _raw_dir(cfg: dict[str, Any]) -> Path:
    return Path(cfg["data"]["raw_dir"])


def _fixtures_dir(cfg: dict[str, Any]) -> Path:
    d = cfg.get("data", {}).get("fixtures_dir") or "data/fixtures"
    return Path(d)


def _cache_path(cfg: dict[str, Any], league_code: str, season: str) -> Path:
    return _raw_dir(cfg) / f"{league_code}_{season}.csv"


def _fixtures_path(cfg: dict[str, Any], league_code: str, season: str) -> Path:
    return _fixtures_dir(cfg) / f"{league_code}_{season}.csv"


def write_matches_csv(df: pd.DataFrame, path: Path) -> Path:
    """Persist normalized matches (internal schema) to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for col in MATCH_COLUMNS:
        if col not in out.columns:
            out[col] = None
    out = out[MATCH_COLUMNS]
    out.to_csv(path, index=False)
    return path


def _fetch_football_data_frame(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Download one football-data.co.uk CSV and normalize; empty on failure."""
    if not _source_enabled(cfg, "football_data"):
        return empty_matches()
    fd = (_sources_cfg(cfg).get("football_data") or {})
    base = fd.get("base_url") or cfg["data"]["base_url"]
    url = csv_url(base, season, league_code)
    logger.info("football-data GET %s", url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,*/*"}
    try:
        resp = None
        for attempt in range(2):
            resp = requests.get(url, timeout=60, headers=headers)
            if resp.status_code == 503:
                import time

                wait = int(resp.headers.get("Retry-After", 3))
                wait = min(max(wait, 2), 8)
                logger.warning(
                    "HTTP 503 for %s; retry in %ss (%d/3)", url, wait, attempt + 1
                )
                time.sleep(wait)
                continue
            break
        assert resp is not None
        body = resp.content
        if resp.status_code != 200 or not body or b"<html" in body[:200].lower():
            logger.warning("skip %s (HTTP %s or empty/HTML)", url, resp.status_code)
            return empty_matches()
        if b"," not in body[:500]:
            logger.warning("skip %s (not CSV-like)", url)
            return empty_matches()
        from io import BytesIO

        try:
            raw = pd.read_csv(BytesIO(body), encoding="utf-8", on_bad_lines="skip")
        except UnicodeDecodeError:
            raw = pd.read_csv(BytesIO(body), encoding="latin-1", on_bad_lines="skip")
        return _normalize_football_data(raw, league_code, season, cfg)
    except requests.RequestException as exc:
        logger.warning("fetch failed %s: %s", url, exc)
        return empty_matches()


def _normalize_football_data(
    df: pd.DataFrame, league: str, season: str, cfg: dict[str, Any]
) -> pd.DataFrame:
    cols = cfg["data"]
    required = [
        cols["date_col"],
        cols["home_col"],
        cols["away_col"],
        cols["fthg_col"],
        cols["ftag_col"],
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        # already-normalized cache?
        if {"date", "home", "away", "fthg", "ftag"}.issubset(df.columns):
            return _normalize_internal(df, league, season, default_source="football_data")
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
    out["source"] = "football_data"
    out = out.dropna(subset=["date", "home", "away", "fthg", "ftag"])
    out["fthg"] = out["fthg"].astype(int)
    out["ftag"] = out["ftag"].astype(int)
    return out[MATCH_COLUMNS]


def _normalize_internal(
    df: pd.DataFrame,
    league: str,
    season: str,
    *,
    default_source: str = "cache",
) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "date": _parse_dates(df["date"]) if "date" in df.columns else pd.NaT,
            "home": df["home"].astype(str).str.strip(),
            "away": df["away"].astype(str).str.strip(),
            "fthg": pd.to_numeric(df["fthg"], errors="coerce"),
            "ftag": pd.to_numeric(df["ftag"], errors="coerce"),
            "ftr": df["ftr"].astype(str).str.strip() if "ftr" in df.columns else None,
            "league": df["league"] if "league" in df.columns else league,
            "season": df["season"] if "season" in df.columns else season,
            "source": df["source"] if "source" in df.columns else default_source,
        }
    )
    out = out.dropna(subset=["date", "home", "away", "fthg", "ftag"])
    out["fthg"] = out["fthg"].astype(int)
    out["ftag"] = out["ftag"].astype(int)
    return out[MATCH_COLUMNS]


def _normalize_frame(df: pd.DataFrame, league: str, season: str, cfg: dict[str, Any]) -> pd.DataFrame:
    """Accept football-data columns or already-normalized schema."""
    if {"date", "home", "away", "fthg", "ftag"}.issubset(df.columns):
        return _normalize_internal(df, league, season)
    return _normalize_football_data(df, league, season, cfg)


def fetch_league_season(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any] | None = None,
    force: bool = False,
) -> Path | None:
    """Fetch one league/season via ordered sources; cache under data/raw/.

    Returns cache path or None if all sources fail.
    """
    cfg = cfg or load_config()
    dest = _cache_path(cfg, league_code, season)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        logger.info("cached %s", dest.name)
        return dest

    frame = empty_matches()
    used = None
    for name in _source_order(cfg):
        if name == "football_data":
            frame = _fetch_football_data_frame(league_code, season, cfg=cfg)
        elif name == "openfootball":
            if not _source_enabled(cfg, "openfootball"):
                continue
            frame = fetch_openfootball_finished(league_code, season, cfg=cfg)
        elif name == "football_datasets":
            if not _source_enabled(cfg, "football_datasets"):
                continue
            frame = fetch_football_datasets(league_code, season, cfg=cfg)
        elif name == "jleague":
            if not _source_enabled(cfg, "jleague"):
                continue
            frame = fetch_jleague_finished(league_code, season, cfg=cfg)
        elif name == "kleague":
            if not _source_enabled(cfg, "kleague"):
                continue
            frame = fetch_kleague_finished(league_code, season, cfg=cfg)
        elif name == "openligadb":
            if not _source_enabled(cfg, "openligadb"):
                continue
            frame = fetch_openligadb_finished(league_code, season, cfg=cfg)
        elif name == "england_mirror":
            if not _source_enabled(cfg, "england_mirror"):
                continue
            frame = fetch_england_mirror(season, cfg=cfg, league_code=league_code)
        else:
            logger.warning("unknown source %s", name)
            continue
        if frame is not None and not frame.empty:
            used = name
            break
        logger.info("source %s returned no rows for %s/%s", name, league_code, season)

    if frame is None or frame.empty:
        logger.warning("all sources failed for %s/%s", league_code, season)
        return None

    write_matches_csv(frame, dest)
    logger.info("wrote %s (%d rows, source=%s)", dest.name, len(frame), used)
    return dest


def fetch_all(cfg: dict[str, Any] | None = None, force: bool = False) -> list[Path]:
    """Fetch last N seasons for all configured leagues (primary then fallbacks)."""
    cfg = cfg or load_config()
    seasons = season_codes(cfg)
    paths: list[Path] = []
    for code in cfg["leagues"]:
        for season in seasons:
            p = fetch_league_season(code, season, cfg=cfg, force=force)
            if p is not None:
                paths.append(p)
    return paths


def _filter_future_fixtures(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop unscored rows whose kickoff is already in the past (UTC+8 day)."""
    if frame is None or frame.empty or "date" not in frame.columns:
        return empty_matches() if frame is None else frame
    from datetime import datetime, timezone, timedelta

    today = datetime.now(timezone(timedelta(hours=8))).date()
    out = frame.copy()
    dts = pd.to_datetime(out["date"], errors="coerce")
    mask = dts.dt.date >= today
    return out.loc[mask].reset_index(drop=True)


def _fetch_fixtures_frame(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Try fixture providers: OpenLigaDB, openfootball, jleague, kleague."""
    providers = []
    if _source_enabled(cfg, "openligadb"):
        providers.append(("openligadb", fetch_openligadb_fixtures))
    if _source_enabled(cfg, "jleague"):
        providers.append(("jleague", fetch_jleague_fixtures))
    if _source_enabled(cfg, "kleague"):
        providers.append(("kleague", fetch_kleague_fixtures))
    if _source_enabled(cfg, "openfootball"):
        providers.append(("openfootball", fetch_openfootball_fixtures))
    for name, fn in providers:
        frame = fn(league_code, season, cfg=cfg)
        frame = _filter_future_fixtures(frame)
        if frame is not None and not frame.empty:
            logger.info("fixtures via %s for %s/%s (%d)", name, league_code, season, len(frame))
            return frame
    return empty_matches()


def fetch_fixtures(
    cfg: dict[str, Any] | None = None,
    *,
    force: bool = False,
    leagues: list[str] | None = None,
) -> list[Path]:
    """Refresh upcoming fixtures into data/fixtures/ (OpenLigaDB + openfootball)."""
    cfg = cfg or load_config()
    fx_cfg = cfg.get("fixtures") or {}
    if not fx_cfg.get("enabled", True):
        logger.info("fixtures disabled in config")
        return []

    seasons = season_codes(cfg)
    # Prefer current season for schedule
    current = seasons[-1] if seasons else None
    if current is None:
        return []
    league_list = leagues or list(cfg["leagues"].keys())
    paths: list[Path] = []
    for code in league_list:
        dest = _fixtures_path(cfg, code, current)
        if dest.exists() and dest.stat().st_size > 0 and not force:
            logger.info("fixtures cached %s", dest.name)
            paths.append(dest)
            continue
        frame = _fetch_fixtures_frame(code, current, cfg=cfg)
        if frame.empty:
            logger.info("no upcoming fixtures for %s/%s", code, current)
            continue
        write_matches_csv(frame, dest)
        logger.info("wrote fixtures %s (%d rows)", dest.name, len(frame))
        paths.append(dest)
    return paths


def load_matches(
    cfg: dict[str, Any] | None = None,
    leagues: list[str] | None = None,
    paths: list[Path] | None = None,
) -> pd.DataFrame:
    """Load and concatenate cached CSVs into a normalized match table."""
    cfg = cfg or load_config()
    raw_dir = _raw_dir(cfg)
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
        return empty_matches()

    all_m = pd.concat(frames, ignore_index=True)
    all_m = all_m.sort_values(["date", "league", "home"]).reset_index(drop=True)
    return all_m


def load_fixtures(
    cfg: dict[str, Any] | None = None,
    leagues: list[str] | None = None,
) -> pd.DataFrame:
    """Load cached upcoming fixtures (unfinished matches)."""
    cfg = cfg or load_config()
    fx_dir = _fixtures_dir(cfg)
    if not fx_dir.exists():
        return empty_matches()
    league_list = leagues or list(cfg["leagues"].keys())
    frames: list[pd.DataFrame] = []
    for code in league_list:
        for path in sorted(fx_dir.glob(f"{code}_*.csv")):
            try:
                df = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
            season = path.stem.split("_", 1)[-1]
            if {"date", "home", "away"}.issubset(df.columns):
                out = pd.DataFrame(
                    {
                        "date": _parse_dates(df["date"]),
                        "home": df["home"].astype(str).str.strip(),
                        "away": df["away"].astype(str).str.strip(),
                        "fthg": None,
                        "ftag": None,
                        "ftr": None,
                        "league": df["league"] if "league" in df.columns else code,
                        "season": df["season"] if "season" in df.columns else season,
                        "source": df["source"] if "source" in df.columns else "fixture",
                    }
                )
                out = out.dropna(subset=["date", "home", "away"])
                frames.append(out)
    if not frames:
        return empty_matches()
    return pd.concat(frames, ignore_index=True).sort_values(["date", "league"]).reset_index(
        drop=True
    )


def load_sample_fixture(path: Path | str) -> pd.DataFrame:
    """Load a tiny offline fixture CSV (tests)."""
    path = Path(path)
    raw = pd.read_csv(path)
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
            "source": df["source"] if "source" in df.columns else "fixture",
        }
    )
    return out

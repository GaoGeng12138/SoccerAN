"""Alternate finished-result / fixture sources (OpenLigaDB, England mirror, openfootball, football-datasets)."""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; SoccerAN/0.1; +https://github.com/GaoGeng12138/SoccerAN)"
)

MATCH_COLUMNS = [
    "date",
    "league",
    "season",
    "home",
    "away",
    "fthg",
    "ftag",
    "ftr",
    "source",
]


def empty_matches() -> pd.DataFrame:
    return pd.DataFrame(columns=MATCH_COLUMNS)


def season_to_openliga_year(season: str) -> int:
    """football-data season '2526' → OpenLigaDB year 2025 (season start)."""
    return 2000 + int(str(season)[:2])


def season_to_slash(season: str) -> str:
    """'2526' → '2025/2026'."""
    y = season_to_openliga_year(season)
    return f"{y}/{y + 1}"


def _result_1x2(fthg: int, ftag: int) -> str:
    if fthg > ftag:
        return "H"
    if fthg < ftag:
        return "A"
    return "D"


def _http_get_json(url: str, *, timeout: int = 60) -> Any | None:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        resp = requests.get(url, timeout=timeout, headers=headers)
        if resp.status_code != 200:
            logger.warning("HTTP %s for %s", resp.status_code, url)
            return None
        return resp.json()
    except requests.RequestException as exc:
        logger.warning("request failed %s: %s", url, exc)
        return None
    except ValueError as exc:
        logger.warning("invalid JSON from %s: %s", url, exc)
        return None


def _oldb_ft_score(match: dict[str, Any]) -> tuple[int, int] | None:
    """Extract full-time score from OpenLigaDB matchResults."""
    results = match.get("matchResults") or []
    for r in results:
        if r.get("resultTypeKind") == "After90Minutes" or r.get("resultTypeID") == 2:
            return int(r["pointsTeam1"]), int(r["pointsTeam2"])
    if results:
        r = max(results, key=lambda x: int(x.get("resultOrderID") or 0))
        try:
            return int(r["pointsTeam1"]), int(r["pointsTeam2"])
        except (KeyError, TypeError, ValueError):
            return None
    return None


_LEADING_FC = re.compile(r"^FC\s+", re.IGNORECASE)
_TRAILING_FC = re.compile(r"\s+F\.?C\.?$", re.IGNORECASE)


def soft_strip_fc(name: str) -> str:
    """Align OpenLigaDB club strings with football-data / England-mirror style.

    Examples: 'FC Arsenal'→'Arsenal', 'Chelsea FC'→'Chelsea'; keep 'AFC Bournemouth'.
    """
    s = (name or "").strip()
    if not s:
        return s
    if s.casefold().startswith("afc "):
        return _TRAILING_FC.sub("", s).strip() or s
    s2 = _LEADING_FC.sub("", s)
    s2 = _TRAILING_FC.sub("", s2).strip()
    return s2 or s


def _team_name(team: dict[str, Any] | None) -> str:
    if not team:
        return ""
    name = (team.get("teamName") or team.get("shortName") or "").strip()
    return soft_strip_fc(name)


def resolve_openliga_shortcut(
    league_code: str, season: str, cfg: dict[str, Any]
) -> str | None:
    """Return OpenLigaDB shortcut for league/season, or None if unsupported."""
    oldb = (cfg.get("sources") or {}).get("openligadb") or {}
    if not oldb.get("enabled", True):
        return None
    overrides = (oldb.get("shortcut_overrides") or {}).get(league_code) or {}
    if season in overrides and overrides[season]:
        return str(overrides[season])
    shortcuts = oldb.get("shortcuts") or {}
    sc = shortcuts.get(league_code)
    if sc is None or sc == "" or sc is False:
        return None
    return str(sc)


def fetch_openligadb_raw(
    shortcut: str,
    year: int,
    *,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """GET OpenLigaDB match list; return [] on failure/empty."""
    cfg = cfg or {}
    oldb = (cfg.get("sources") or {}).get("openligadb") or {}
    base = oldb.get("base_url") or "https://www.openligadb.de/api/getmatchdata"
    url = f"{base.rstrip('/')}/{shortcut}/{year}"
    logger.info("OpenLigaDB GET %s", url)
    data = _http_get_json(url)
    if not isinstance(data, list):
        return []
    return data


def openligadb_matches_to_frame(
    matches: list[dict[str, Any]],
    *,
    league_code: str,
    season: str,
    finished_only: bool = True,
    source: str = "openligadb",
) -> pd.DataFrame:
    """Normalize OpenLigaDB JSON matches into internal schema."""
    rows: list[dict[str, Any]] = []
    for m in matches:
        is_fin = bool(m.get("matchIsFinished"))
        if finished_only and not is_fin:
            continue
        if not finished_only and is_fin:
            continue
        home = _team_name(m.get("team1"))
        away = _team_name(m.get("team2"))
        if not home or not away:
            continue
        dt = m.get("matchDateTimeUTC") or m.get("matchDateTime")
        date = pd.to_datetime(dt, errors="coerce", utc=True)
        if pd.isna(date):
            continue
        # naive UTC for consistency with football-data date columns
        date = date.tz_localize(None)
        fthg = ftag = None
        ftr = None
        if is_fin:
            score = _oldb_ft_score(m)
            if score is None:
                continue
            fthg, ftag = score
            ftr = _result_1x2(fthg, ftag)
        rows.append(
            {
                "date": date,
                "league": league_code,
                "season": season,
                "home": home,
                "away": away,
                "fthg": fthg,
                "ftag": ftag,
                "ftr": ftr,
                "source": source,
            }
        )
    if not rows:
        return empty_matches()
    out = pd.DataFrame(rows)
    if finished_only:
        out = out.dropna(subset=["fthg", "ftag"])
        out["fthg"] = out["fthg"].astype(int)
        out["ftag"] = out["ftag"].astype(int)
    return out.sort_values(["date", "home"]).reset_index(drop=True)


def fetch_openligadb_finished(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Finished matches for one league/season via OpenLigaDB."""
    shortcut = resolve_openliga_shortcut(league_code, season, cfg)
    if not shortcut:
        logger.info("OpenLigaDB: no shortcut for %s/%s", league_code, season)
        return empty_matches()
    year = season_to_openliga_year(season)
    raw = fetch_openligadb_raw(shortcut, year, cfg=cfg)
    if not raw:
        return empty_matches()
    return openligadb_matches_to_frame(
        raw, league_code=league_code, season=season, finished_only=True
    )


def fetch_openligadb_fixtures(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Upcoming (unfinished) matches for one league/season via OpenLigaDB."""
    shortcut = resolve_openliga_shortcut(league_code, season, cfg)
    if not shortcut:
        return empty_matches()
    year = season_to_openliga_year(season)
    raw = fetch_openligadb_raw(shortcut, year, cfg=cfg)
    if not raw:
        return empty_matches()
    return openligadb_matches_to_frame(
        raw,
        league_code=league_code,
        season=season,
        finished_only=False,
        source="openligadb",
    )


def fetch_england_mirror(
    season: str,
    *,
    cfg: dict[str, Any],
    league_code: str = "E0",
) -> pd.DataFrame:
    """Premier League (Tier==1) finished results from GitHub CSV mirror."""
    em = (cfg.get("sources") or {}).get("england_mirror") or {}
    if not em.get("enabled", True):
        return empty_matches()
    allowed = set(em.get("leagues") or ["E0"])
    if league_code not in allowed:
        return empty_matches()
    url = em.get("url") or (
        "https://raw.githubusercontent.com/seanelvidge/England-football-results/"
        "main/EnglandLeagueResults.csv"
    )
    logger.info("England mirror GET %s (season %s)", url, season)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,*/*"}
    try:
        resp = requests.get(url, timeout=120, headers=headers)
        if resp.status_code != 200 or not resp.content:
            logger.warning("England mirror HTTP %s", resp.status_code)
            return empty_matches()
        from io import StringIO

        df = pd.read_csv(StringIO(resp.text))
    except requests.RequestException as exc:
        logger.warning("England mirror failed: %s", exc)
        return empty_matches()
    except Exception as exc:  # noqa: BLE001 — parse errors
        logger.warning("England mirror parse failed: %s", exc)
        return empty_matches()

    # Normalize column names
    cols = {c.lower(): c for c in df.columns}
    def col(*names: str) -> str | None:
        for n in names:
            if n.lower() in cols:
                return cols[n.lower()]
            if n in df.columns:
                return n
        return None

    tier_c = col("Tier")
    season_c = col("Season", "season")
    date_c = col("Date", "date")
    home_c = col("HomeTeam", "home")
    away_c = col("AwayTeam", "away")
    hg_c = col("hGoal", "FTHG", "fthg")
    ag_c = col("aGoal", "FTAG", "ftag")
    res_c = col("Result", "FTR", "ftr")
    if not all([tier_c, season_c, date_c, home_c, away_c, hg_c, ag_c]):
        logger.warning("England mirror missing columns: %s", list(df.columns))
        return empty_matches()

    target = season_to_slash(season)
    sub = df[df[tier_c].astype(str).str.strip() == "1"].copy()
    sub = sub[sub[season_c].astype(str).str.strip() == target]
    if sub.empty:
        logger.info("England mirror: no Tier=1 rows for %s", target)
        return empty_matches()

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(sub[date_c], errors="coerce"),
            "league": league_code,
            "season": season,
            "home": sub[home_c].astype(str).str.strip(),
            "away": sub[away_c].astype(str).str.strip(),
            "fthg": pd.to_numeric(sub[hg_c], errors="coerce"),
            "ftag": pd.to_numeric(sub[ag_c], errors="coerce"),
        }
    )
    if res_c:
        out["ftr"] = sub[res_c].astype(str).str.strip()
    else:
        out["ftr"] = [
            _result_1x2(int(h), int(a)) if pd.notna(h) and pd.notna(a) else None
            for h, a in zip(out["fthg"], out["ftag"])
        ]
    out["source"] = "england_mirror"
    out = out.dropna(subset=["date", "home", "away", "fthg", "ftag"])
    out["fthg"] = out["fthg"].astype(int)
    out["ftag"] = out["ftag"].astype(int)
    # Fill missing FTR
    miss = out["ftr"].isna() | (out["ftr"] == "") | (out["ftr"] == "nan")
    out.loc[miss, "ftr"] = [
        _result_1x2(h, a) for h, a in zip(out.loc[miss, "fthg"], out.loc[miss, "ftag"])
    ]
    return out.sort_values(["date", "home"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# openfootball / football.json (Serie A + Ligue 1 results & fixtures)
# ---------------------------------------------------------------------------


def season_to_openfootball_path(season: str) -> str:
    """'2627' → '2026-27'."""
    y = season_to_openliga_year(season)
    return f"{y}-{str(y + 1)[-2:]}"


def _of_ft_score(score: Any) -> tuple[int, int] | None:
    """Parse openfootball score: [hg, ag] or {'ft': [hg, ag], ...}."""
    if score is None:
        return None
    if isinstance(score, list) and len(score) >= 2:
        if score[0] is None or score[1] is None:
            return None
        try:
            return int(score[0]), int(score[1])
        except (TypeError, ValueError):
            return None
    if isinstance(score, dict):
        ft = score.get("ft")
        if isinstance(ft, (list, tuple)) and len(ft) >= 2:
            if ft[0] is None or ft[1] is None:
                return None
            try:
                return int(ft[0]), int(ft[1])
            except (TypeError, ValueError):
                return None
    return None


def resolve_openfootball_file(
    league_code: str, season: str, cfg: dict[str, Any]
) -> str | None:
    """Return relative JSON path under base_url, or None if league unsupported.

    European leagues use ``2025-26/it.1.json``; calendar-year leagues (e.g. JP1)
    use ``2025/jp.1.json`` (configured via ``calendar_year_leagues``).
    """
    of = (cfg.get("sources") or {}).get("openfootball") or {}
    if not of.get("enabled", True):
        return None
    files = of.get("files") or {}
    fname = files.get(league_code)
    if not fname:
        return None
    cal = set(of.get("calendar_year_leagues") or [])
    if league_code in cal:
        return f"{season_to_openliga_year(season)}/{fname}"
    return f"{season_to_openfootball_path(season)}/{fname}"


def fetch_openfootball_raw(
    rel_path: str,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """GET openfootball football.json payload; None on failure."""
    cfg = cfg or {}
    of = (cfg.get("sources") or {}).get("openfootball") or {}
    base = of.get("base_url") or (
        "https://raw.githubusercontent.com/openfootball/football.json/master"
    )
    url = f"{base.rstrip('/')}/{rel_path.lstrip('/')}"
    logger.info("openfootball GET %s", url)
    data = _http_get_json(url)
    if not isinstance(data, dict):
        return None
    return data


def openfootball_matches_to_frame(
    payload: dict[str, Any],
    *,
    league_code: str,
    season: str,
    finished_only: bool = True,
    source: str = "openfootball",
) -> pd.DataFrame:
    """Normalize openfootball JSON matches into internal schema."""
    matches = payload.get("matches") or []
    if not isinstance(matches, list):
        return empty_matches()
    rows: list[dict[str, Any]] = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        # Skip explicitly canceled fixtures for both modes
        status = str(m.get("status") or "").lower()
        if status in {"canceled", "cancelled", "postponed", "awarded"}:
            # Still allow finished awarded? Prefer skip unstable rows.
            if status in {"canceled", "cancelled"}:
                continue
        home = (m.get("team1") or m.get("home") or "").strip()
        away = (m.get("team2") or m.get("away") or "").strip()
        if not home or not away:
            continue
        date = pd.to_datetime(m.get("date"), errors="coerce")
        if pd.isna(date):
            continue
        # Attach kickoff time when present (naive local / as published)
        t = m.get("time")
        if t and isinstance(t, str) and re.match(r"^\d{1,2}:\d{2}", t):
            try:
                hh, mm = t.split(":")[:2]
                date = date + pd.Timedelta(hours=int(hh), minutes=int(mm))
            except (ValueError, TypeError):
                pass
        score = m.get("score")
        ft = _of_ft_score(score)
        is_fin = ft is not None
        if finished_only and not is_fin:
            continue
        if not finished_only and is_fin:
            continue
        fthg = ftag = ftr = None
        if is_fin:
            fthg, ftag = ft
            ftr = _result_1x2(fthg, ftag)
        rows.append(
            {
                "date": date,
                "league": league_code,
                "season": season,
                "home": home,
                "away": away,
                "fthg": fthg,
                "ftag": ftag,
                "ftr": ftr,
                "source": source,
            }
        )
    if not rows:
        return empty_matches()
    out = pd.DataFrame(rows)
    if finished_only:
        out = out.dropna(subset=["fthg", "ftag"])
        out["fthg"] = out["fthg"].astype(int)
        out["ftag"] = out["ftag"].astype(int)
    return out.sort_values(["date", "home"]).reset_index(drop=True)


def fetch_openfootball_finished(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Finished matches via openfootball football.json (I1/F1)."""
    rel = resolve_openfootball_file(league_code, season, cfg)
    if not rel:
        logger.info("openfootball: no file for %s/%s", league_code, season)
        return empty_matches()
    raw = fetch_openfootball_raw(rel, cfg=cfg)
    if not raw:
        return empty_matches()
    return openfootball_matches_to_frame(
        raw, league_code=league_code, season=season, finished_only=True
    )


def fetch_openfootball_fixtures(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Upcoming (unscored) matches via openfootball football.json."""
    rel = resolve_openfootball_file(league_code, season, cfg)
    if not rel:
        return empty_matches()
    raw = fetch_openfootball_raw(rel, cfg=cfg)
    if not raw:
        return empty_matches()
    return openfootball_matches_to_frame(
        raw,
        league_code=league_code,
        season=season,
        finished_only=False,
        source="openfootball",
    )


# ---------------------------------------------------------------------------
# datasets/football-datasets GitHub CSV mirror (football-data schema)
# ---------------------------------------------------------------------------


def fetch_football_datasets(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Finished results from datasets/football-datasets (Serie A / Ligue 1 CSVs).

    Coverage typically lags current season (no 2627 as of Sep 2026); useful
    historical fallback when football-data.co.uk is down. Short club names.
    """
    fdg = (cfg.get("sources") or {}).get("football_datasets") or {}
    if not fdg.get("enabled", True):
        return empty_matches()
    league_dirs = fdg.get("leagues") or {}
    folder = league_dirs.get(league_code)
    if not folder:
        return empty_matches()
    base = fdg.get("base_url") or (
        "https://raw.githubusercontent.com/datasets/football-datasets/master/datasets"
    )
    url = f"{base.rstrip('/')}/{folder}/season-{season}.csv"
    logger.info("football_datasets GET %s", url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,*/*"}
    try:
        resp = requests.get(url, timeout=60, headers=headers)
        if resp.status_code != 200 or not resp.content:
            logger.warning("football_datasets HTTP %s for %s", resp.status_code, url)
            return empty_matches()
        from io import StringIO

        df = pd.read_csv(StringIO(resp.text))
    except requests.RequestException as exc:
        logger.warning("football_datasets failed: %s", exc)
        return empty_matches()
    except Exception as exc:  # noqa: BLE001
        logger.warning("football_datasets parse failed: %s", exc)
        return empty_matches()

    cols = {c.lower(): c for c in df.columns}

    def col(*names: str) -> str | None:
        for n in names:
            if n.lower() in cols:
                return cols[n.lower()]
            if n in df.columns:
                return n
        return None

    date_c = col("Date", "date")
    home_c = col("HomeTeam", "home")
    away_c = col("AwayTeam", "away")
    hg_c = col("FTHG", "fthg")
    ag_c = col("FTAG", "ftag")
    res_c = col("FTR", "ftr")
    if not all([date_c, home_c, away_c, hg_c, ag_c]):
        logger.warning("football_datasets missing columns: %s", list(df.columns))
        return empty_matches()

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_c], errors="coerce"),
            "league": league_code,
            "season": season,
            "home": df[home_c].astype(str).str.strip(),
            "away": df[away_c].astype(str).str.strip(),
            "fthg": pd.to_numeric(df[hg_c], errors="coerce"),
            "ftag": pd.to_numeric(df[ag_c], errors="coerce"),
        }
    )
    if res_c:
        out["ftr"] = df[res_c].astype(str).str.strip()
    else:
        out["ftr"] = None
    out["source"] = "football_datasets"
    out = out.dropna(subset=["date", "home", "away", "fthg", "ftag"])
    out["fthg"] = out["fthg"].astype(int)
    out["ftag"] = out["ftag"].astype(int)
    miss = out["ftr"].isna() | (out["ftr"] == "") | (out["ftr"] == "nan")
    out.loc[miss, "ftr"] = [
        _result_1x2(h, a) for h, a in zip(out.loc[miss, "fthg"], out.loc[miss, "ftag"])
    ]
    return out.sort_values(["date", "home"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# J.League official HTML (JP1) — data.j-league.or.jp schedule/results table
# ---------------------------------------------------------------------------

_JL_SCORE_RE = re.compile(r"^(\d+)\s*[-－–]\s*(\d+)$")
_JL_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{2})")


def _parse_jleague_date(cell: str) -> pd.Timestamp | None:
    """Parse ``26/08/07(金)`` / ``24/02/23(金・祝)`` → Timestamp."""
    m = _JL_DATE_RE.search(cell or "")
    if not m:
        return None
    yy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year = 2000 + yy
    try:
        return pd.Timestamp(year=year, month=mm, day=dd)
    except ValueError:
        return None


def jleague_html_to_frame(
    html: str,
    *,
    league_code: str,
    season: str,
    finished_only: bool = True,
    source: str = "jleague",
) -> pd.DataFrame:
    """Parse J.League SFMS01 HTML table into internal schema."""
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        logger.warning("beautifulsoup4 required for jleague source: %s", exc)
        return empty_matches()

    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return empty_matches()
    best = max(tables, key=lambda t: len(t.find_all("tr")))
    rows_out: list[dict[str, Any]] = []
    for tr in best.find_all("tr")[1:]:
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 8:
            continue
        # シーズン,大会,節,試合日,K/O時刻,ホーム,スコア,アウェイ,...
        date = _parse_jleague_date(cells[3])
        if date is None:
            continue
        ko = cells[4] if len(cells) > 4 else ""
        if ko and re.match(r"^\d{1,2}:\d{2}", ko):
            try:
                hh, mm = ko.split(":")[:2]
                date = date + pd.Timedelta(hours=int(hh), minutes=int(mm))
            except (ValueError, TypeError):
                pass
        home = (cells[5] or "").strip()
        away = (cells[7] or "").strip()
        if not home or not away:
            continue
        score = (cells[6] or "").strip()
        m = _JL_SCORE_RE.match(score)
        is_fin = m is not None
        if finished_only and not is_fin:
            continue
        if not finished_only and is_fin:
            continue
        fthg = ftag = ftr = None
        if is_fin:
            fthg, ftag = int(m.group(1)), int(m.group(2))
            ftr = _result_1x2(fthg, ftag)
        rows_out.append(
            {
                "date": date,
                "league": league_code,
                "season": season,
                "home": home,
                "away": away,
                "fthg": fthg,
                "ftag": ftag,
                "ftr": ftr,
                "source": source,
            }
        )
    if not rows_out:
        return empty_matches()
    out = pd.DataFrame(rows_out)
    if finished_only:
        out = out.dropna(subset=["fthg", "ftag"])
        out["fthg"] = out["fthg"].astype(int)
        out["ftag"] = out["ftag"].astype(int)
    return out.sort_values(["date", "home"]).reset_index(drop=True)


def fetch_jleague_finished(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Finished J1 matches from data.j-league.or.jp (Japanese club abbreviations)."""
    jl = (cfg.get("sources") or {}).get("jleague") or {}
    if not jl.get("enabled", True):
        return empty_matches()
    allowed = set(jl.get("leagues") or ["JP1"])
    if league_code not in allowed:
        return empty_matches()
    year = season_to_openliga_year(season)
    base = jl.get("base_url") or "https://data.j-league.or.jp/SFMS01/search"
    frame_ids = jl.get("competition_frame_ids") or "1"
    url = f"{base}?competition_years={year}&competition_frame_ids={frame_ids}"
    logger.info("jleague GET %s", url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
    try:
        resp = requests.get(url, timeout=90, headers=headers)
        if resp.status_code != 200 or not resp.text:
            logger.warning("jleague HTTP %s", resp.status_code)
            return empty_matches()
        # Force UTF-8 (site sometimes mislabels encoding)
        resp.encoding = resp.apparent_encoding or "utf-8"
        return jleague_html_to_frame(
            resp.text, league_code=league_code, season=season, finished_only=True
        )
    except requests.RequestException as exc:
        logger.warning("jleague failed: %s", exc)
        return empty_matches()


def fetch_jleague_fixtures(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Upcoming J1 fixtures (score == vs) from data.j-league.or.jp."""
    jl = (cfg.get("sources") or {}).get("jleague") or {}
    if not jl.get("enabled", True):
        return empty_matches()
    allowed = set(jl.get("leagues") or ["JP1"])
    if league_code not in allowed:
        return empty_matches()
    year = season_to_openliga_year(season)
    base = jl.get("base_url") or "https://data.j-league.or.jp/SFMS01/search"
    frame_ids = jl.get("competition_frame_ids") or "1"
    url = f"{base}?competition_years={year}&competition_frame_ids={frame_ids}"
    logger.info("jleague fixtures GET %s", url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
    try:
        resp = requests.get(url, timeout=90, headers=headers)
        if resp.status_code != 200 or not resp.text:
            return empty_matches()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return jleague_html_to_frame(
            resp.text,
            league_code=league_code,
            season=season,
            finished_only=False,
            source="jleague",
        )
    except requests.RequestException as exc:
        logger.warning("jleague fixtures failed: %s", exc)
        return empty_matches()


# ---------------------------------------------------------------------------
# K League official JSON API (KR1) — www.kleague.com/getScheduleList.do
# ---------------------------------------------------------------------------


def kleague_schedule_to_frame(
    matches: list[dict[str, Any]],
    *,
    league_code: str,
    season: str,
    finished_only: bool = True,
    source: str = "kleague",
) -> pd.DataFrame:
    """Normalize K League scheduleList JSON rows into internal schema."""
    rows: list[dict[str, Any]] = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        home = (m.get("homeTeamName") or "").strip()
        away = (m.get("awayTeamName") or "").strip()
        if not home or not away:
            continue
        gd = str(m.get("gameDate") or "").replace(".", "-")
        date = pd.to_datetime(gd, errors="coerce")
        if pd.isna(date):
            continue
        gt = m.get("gameTime")
        if gt and isinstance(gt, str) and re.match(r"^\d{1,2}:\d{2}", gt):
            try:
                hh, mm = gt.split(":")[:2]
                date = date + pd.Timedelta(hours=int(hh), minutes=int(mm))
            except (ValueError, TypeError):
                pass
        end_yn = str(m.get("endYn") or "").upper()
        status = str(m.get("gameStatus") or "").upper()
        hg, ag = m.get("homeGoal"), m.get("awayGoal")
        # Unplayed rows often carry homeGoal=0,awayGoal=0 placeholders — trust endYn/FE.
        if end_yn == "N":
            is_fin = False
        elif end_yn == "Y" or status == "FE":
            is_fin = True
        else:
            is_fin = False
        if finished_only and not is_fin:
            continue
        if not finished_only and is_fin:
            continue
        fthg = ftag = ftr = None
        if is_fin:
            try:
                fthg, ftag = int(hg), int(ag)
            except (TypeError, ValueError):
                continue
            ftr = _result_1x2(fthg, ftag)
        rows.append(
            {
                "date": date,
                "league": league_code,
                "season": season,
                "home": home,
                "away": away,
                "fthg": fthg,
                "ftag": ftag,
                "ftr": ftr,
                "source": source,
            }
        )
    if not rows:
        return empty_matches()
    out = pd.DataFrame(rows)
    if finished_only:
        out = out.dropna(subset=["fthg", "ftag"])
        out["fthg"] = out["fthg"].astype(int)
        out["ftag"] = out["ftag"].astype(int)
    return out.sort_values(["date", "home"]).reset_index(drop=True)


def fetch_kleague_month(
    year: int,
    month: int,
    *,
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """POST one month of K League 1 schedule JSON."""
    kl = (cfg.get("sources") or {}).get("kleague") or {}
    url = kl.get("url") or "https://www.kleague.com/getScheduleList.do"
    league_id = str(kl.get("league_id") or "1")
    body = {"leagueId": league_id, "year": str(year), "month": f"{month:02d}"}
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.kleague.com/schedule.do?leagueId=1",
        "Origin": "https://www.kleague.com",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        resp = requests.post(url, json=body, timeout=60, headers=headers)
        if resp.status_code != 200:
            logger.warning("kleague HTTP %s for %s-%02d", resp.status_code, year, month)
            return []
        data = resp.json()
        return list((data.get("data") or {}).get("scheduleList") or [])
    except (requests.RequestException, ValueError) as exc:
        logger.warning("kleague month failed %s-%02d: %s", year, month, exc)
        return []


def fetch_kleague_year(
    year: int,
    *,
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Aggregate Jan–Dec schedule rows for one K League season year."""
    out: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for month in range(1, 13):
        for m in fetch_kleague_month(year, month, cfg=cfg):
            key = m.get("gameId") or (
                m.get("gameDate"),
                m.get("homeTeam"),
                m.get("awayTeam"),
                m.get("gameTime"),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(m)
    return out


def fetch_kleague_finished(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Finished K League 1 results via official JSON API."""
    kl = (cfg.get("sources") or {}).get("kleague") or {}
    if not kl.get("enabled", True):
        return empty_matches()
    allowed = set(kl.get("leagues") or ["KR1"])
    if league_code not in allowed:
        return empty_matches()
    year = season_to_openliga_year(season)
    logger.info("kleague fetch year %s for %s/%s", year, league_code, season)
    raw = fetch_kleague_year(year, cfg=cfg)
    if not raw:
        return empty_matches()
    return kleague_schedule_to_frame(
        raw, league_code=league_code, season=season, finished_only=True
    )


def fetch_kleague_fixtures(
    league_code: str,
    season: str,
    *,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Upcoming K League 1 fixtures via official JSON API."""
    kl = (cfg.get("sources") or {}).get("kleague") or {}
    if not kl.get("enabled", True):
        return empty_matches()
    allowed = set(kl.get("leagues") or ["KR1"])
    if league_code not in allowed:
        return empty_matches()
    year = season_to_openliga_year(season)
    raw = fetch_kleague_year(year, cfg=cfg)
    if not raw:
        return empty_matches()
    return kleague_schedule_to_frame(
        raw,
        league_code=league_code,
        season=season,
        finished_only=False,
        source="kleague",
    )

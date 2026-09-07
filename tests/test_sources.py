"""Unit tests for alternate sources (OpenLigaDB, England, openfootball, CSV)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from socceran.sources import (
    MATCH_COLUMNS,
    fetch_england_mirror,
    fetch_football_datasets,
    fetch_openfootball_finished,
    jleague_html_to_frame,
    kleague_schedule_to_frame,
    openfootball_matches_to_frame,
    openligadb_matches_to_frame,
    resolve_openliga_shortcut,
    season_to_openfootball_path,
    season_to_openliga_year,
    season_to_slash,
    soft_strip_fc,
)

SAMPLE = Path(__file__).parent / "fixtures" / "openligadb_sample.json"
OF_SAMPLE = Path(__file__).parent / "fixtures" / "openfootball_sample.json"


def test_season_helpers():
    assert season_to_openliga_year("2526") == 2025
    assert season_to_openliga_year("2627") == 2026
    assert season_to_slash("2425") == "2024/2025"


def test_openligadb_json_to_finished_schema():
    raw = json.loads(SAMPLE.read_text(encoding="utf-8"))
    df = openligadb_matches_to_frame(raw, league_code="D1", season="2627", finished_only=True)
    assert list(df.columns) == MATCH_COLUMNS
    assert len(df) == 2
    assert set(df["source"]) == {"openligadb"}
    assert set(df["league"]) == {"D1"}
    bayern = df[df["home"] == "Bayern München"].iloc[0]
    assert bayern["fthg"] == 3
    assert bayern["ftag"] == 1
    assert bayern["ftr"] == "H"
    draw = df[df["ftr"] == "D"].iloc[0]
    assert draw["fthg"] == 0 and draw["ftag"] == 0


def test_openligadb_json_to_fixtures():
    raw = json.loads(SAMPLE.read_text(encoding="utf-8"))
    df = openligadb_matches_to_frame(raw, league_code="D1", season="2627", finished_only=False)
    assert len(df) == 1
    assert df.iloc[0]["home"] == "Borussia Dortmund"
    assert df.iloc[0]["away"] == "1. FC Union Berlin"
    assert pd.isna(df.iloc[0]["fthg"]) or df.iloc[0]["fthg"] is None


def test_resolve_shortcut_and_override():
    cfg = {
        "sources": {
            "openligadb": {
                "enabled": True,
                "shortcuts": {"E0": "PL", "D1": "bl1", "SP1": "la1"},
                "shortcut_overrides": {"E0": {"2324": "pl1"}},
            }
        }
    }
    assert resolve_openliga_shortcut("D1", "2627", cfg) == "bl1"
    assert resolve_openliga_shortcut("E0", "2627", cfg) == "PL"
    assert resolve_openliga_shortcut("E0", "2324", cfg) == "pl1"
    assert resolve_openliga_shortcut("I1", "2627", cfg) is None


def test_england_mirror_filters_tier1(monkeypatch):
    csv_text = (
        "Date,Season,HomeTeam,AwayTeam,Score,hGoal,aGoal,Division,Tier,Result\n"
        "2025-08-15,2025/2026,Liverpool,Arsenal,2-1,2,1,Premier League,1,H\n"
        "2025-08-16,2025/2026,Leeds,Derby,1-0,1,0,Championship,2,H\n"
        "2024-08-15,2024/2025,Chelsea,Everton,0-0,0,0,Premier League,1,D\n"
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = csv_text.encode()
    mock_resp.text = csv_text

    cfg = {
        "sources": {
            "england_mirror": {
                "enabled": True,
                "url": "https://example.invalid/EnglandLeagueResults.csv",
                "leagues": ["E0"],
            }
        }
    }
    with patch("socceran.sources.requests.get", return_value=mock_resp):
        df = fetch_england_mirror("2526", cfg=cfg, league_code="E0")
    assert len(df) == 1
    assert df.iloc[0]["home"] == "Liverpool"
    assert df.iloc[0]["away"] == "Arsenal"
    assert df.iloc[0]["fthg"] == 2
    assert df.iloc[0]["source"] == "england_mirror"


def test_soft_strip_fc():
    assert soft_strip_fc("FC Arsenal") == "Arsenal"
    assert soft_strip_fc("Chelsea FC") == "Chelsea"
    assert soft_strip_fc("Brentford F.C.") == "Brentford"
    assert soft_strip_fc("AFC Bournemouth") == "AFC Bournemouth"
    assert soft_strip_fc("Manchester United FC") == "Manchester United"


def test_season_to_openfootball_path():
    assert season_to_openfootball_path("2627") == "2026-27"
    assert season_to_openfootball_path("2425") == "2024-25"


def test_openfootball_json_to_finished_and_fixtures():
    raw = json.loads(OF_SAMPLE.read_text(encoding="utf-8"))
    fin = openfootball_matches_to_frame(
        raw, league_code="I1", season="2627", finished_only=True
    )
    assert list(fin.columns) == MATCH_COLUMNS
    assert len(fin) == 2
    assert set(fin["source"]) == {"openfootball"}
    draw = fin[fin["home"] == "Udinese Calcio"].iloc[0]
    assert draw["fthg"] == 1 and draw["ftag"] == 1 and draw["ftr"] == "D"
    home_win = fin[fin["home"] == "AC Milan"].iloc[0]
    assert home_win["fthg"] == 2 and home_win["ftag"] == 0 and home_win["ftr"] == "H"

    fx = openfootball_matches_to_frame(
        raw, league_code="I1", season="2627", finished_only=False
    )
    # canceled row skipped; one upcoming Juventus–Roma
    assert len(fx) == 1
    assert fx.iloc[0]["home"] == "Juventus FC"
    assert fx.iloc[0]["away"] == "AS Roma"
    assert pd.isna(fx.iloc[0]["fthg"]) or fx.iloc[0]["fthg"] is None


def test_fetch_openfootball_finished_mocked():
    payload = json.loads(OF_SAMPLE.read_text(encoding="utf-8"))
    cfg = {
        "sources": {
            "openfootball": {
                "enabled": True,
                "base_url": "https://example.invalid/football.json",
                "files": {"I1": "it.1.json"},
            }
        }
    }
    with patch("socceran.sources._http_get_json", return_value=payload):
        df = fetch_openfootball_finished("I1", "2627", cfg=cfg)
    assert len(df) == 2
    assert df.iloc[0]["league"] == "I1"


def test_football_datasets_csv_mocked():
    csv_text = (
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "2025-08-23,Genoa,Lecce,0,0,D\n"
        "2025-08-24,Inter,Torino,2,1,H\n"
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = csv_text.encode()
    mock_resp.text = csv_text
    cfg = {
        "sources": {
            "football_datasets": {
                "enabled": True,
                "base_url": "https://example.invalid/datasets",
                "leagues": {"I1": "serie-a"},
            }
        }
    }
    with patch("socceran.sources.requests.get", return_value=mock_resp):
        df = fetch_football_datasets("I1", "2526", cfg=cfg)
    assert len(df) == 2
    assert df.iloc[1]["home"] == "Inter"
    assert df.iloc[1]["fthg"] == 2
    assert df.iloc[0]["source"] == "football_datasets"


def test_jleague_html_finished_and_fixtures():
    html = """
    <table>
      <tr><th>シーズン</th><th>大会</th><th>節</th><th>試合日</th><th>K/O時刻</th><th>ホーム</th><th>スコア</th><th>アウェイ</th></tr>
      <tr><td>2026/27</td><td>Ｊ１</td><td>1</td><td>26/08/07(金)</td><td>19:00</td><td>横浜FM</td><td>3-4</td><td>鹿島</td></tr>
      <tr><td>2026/27</td><td>Ｊ１</td><td>6</td><td>26/09/12(土)</td><td>19:00</td><td>浦和</td><td>vs</td><td>神戸</td></tr>
    </table>
    """
    fin = jleague_html_to_frame(html, league_code="JP1", season="2627", finished_only=True)
    assert len(fin) == 1
    assert fin.iloc[0]["home"] == "横浜FM"
    assert fin.iloc[0]["away"] == "鹿島"
    assert fin.iloc[0]["fthg"] == 3 and fin.iloc[0]["ftag"] == 4
    assert fin.iloc[0]["ftr"] == "A"
    assert fin.iloc[0]["source"] == "jleague"
    fx = jleague_html_to_frame(html, league_code="JP1", season="2627", finished_only=False)
    assert len(fx) == 1
    assert fx.iloc[0]["home"] == "浦和"
    assert fx.iloc[0]["away"] == "神戸"


def test_kleague_schedule_finished_and_fixtures():
    rows = [
        {
            "gameId": 1,
            "gameDate": "2026.03.01",
            "gameTime": "14:00",
            "homeTeamName": "전북",
            "awayTeamName": "부천",
            "homeGoal": 2,
            "awayGoal": 3,
            "endYn": "Y",
            "gameStatus": "FE",
        },
        {
            "gameId": 2,
            "gameDate": "2026.09.20",
            "gameTime": "19:00",
            "homeTeamName": "서울",
            "awayTeamName": "울산",
            "homeGoal": 0,
            "awayGoal": 0,
            "endYn": "N",
            "gameStatus": "",
        },
    ]
    fin = kleague_schedule_to_frame(rows, league_code="KR1", season="2627", finished_only=True)
    assert len(fin) == 1
    assert fin.iloc[0]["home"] == "전북"
    assert fin.iloc[0]["fthg"] == 2 and fin.iloc[0]["ftag"] == 3
    assert fin.iloc[0]["ftr"] == "A"
    fx = kleague_schedule_to_frame(rows, league_code="KR1", season="2627", finished_only=False)
    assert len(fx) == 1
    assert fx.iloc[0]["home"] == "서울"
    assert fx.iloc[0]["away"] == "울산"


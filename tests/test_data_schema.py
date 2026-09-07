"""Schema / cache round-trip for normalized matches."""

from pathlib import Path

import pandas as pd

from socceran.data import load_matches, write_matches_csv
from socceran.sources import MATCH_COLUMNS, openligadb_matches_to_frame
import json


def test_write_load_normalized_cache(tmp_path, monkeypatch):
    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "openligadb_sample.json").read_text()
    )
    df = openligadb_matches_to_frame(raw, league_code="D1", season="2627", finished_only=True)
    path = tmp_path / "D1_2627.csv"
    write_matches_csv(df, path)
    assert path.exists()

    # Minimal config pointing raw_dir at tmp
    cfg = {
        "data": {
            "raw_dir": str(tmp_path),
            "date_col": "Date",
            "home_col": "HomeTeam",
            "away_col": "AwayTeam",
            "fthg_col": "FTHG",
            "ftag_col": "FTAG",
            "ftr_col": "FTR",
        },
        "leagues": {"D1": {"code": "D1"}},
    }
    loaded = load_matches(cfg, leagues=["D1"])
    assert len(loaded) == 2
    assert set(MATCH_COLUMNS).issubset(loaded.columns)
    assert loaded.iloc[0]["league"] == "D1"

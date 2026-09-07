"""Unit tests for Elo math."""

from pathlib import Path

import pytest

from socceran.data import load_sample_fixture
from socceran.elo import EloSystem, expected_score, result_score

FIXTURE = Path(__file__).parent / "fixtures" / "sample_matches.csv"


def test_expected_score_symmetric():
    assert expected_score(1500, 1500) == pytest.approx(0.5)
    e = expected_score(1600, 1400)
    assert e > 0.5
    assert expected_score(1400, 1600) == pytest.approx(1 - e)


def test_result_score():
    assert result_score(2, 1) == (1.0, 0.0)
    assert result_score(0, 3) == (0.0, 1.0)
    assert result_score(1, 1) == (0.5, 0.5)


def test_elo_update_home_win_raises_home():
    elo = EloSystem(initial=1500, k=20, home_advantage=65, scope="per_league")
    pre_h = elo.get("Alpha", "E0")
    pre_a = elo.get("Beta", "E0")
    elo.update_match("Alpha", "Beta", 2, 0, league="E0")
    assert elo.get("Alpha", "E0") > pre_h
    assert elo.get("Beta", "E0") < pre_a


def test_elo_fit_fixture_offline():
    matches = load_sample_fixture(FIXTURE)
    elo = EloSystem(initial=1500, k=20, home_advantage=65)
    elo.fit(matches)
    assert len(elo.ratings) == 4
    # Alpha won more → should be among the highest
    table = elo.table("E0")
    assert table.iloc[0]["team"] in {"Alpha", "Gamma"}
    assert table["elo"].mean() == pytest.approx(1500, abs=1.0)


def test_home_advantage_affects_expectation():
    elo = EloSystem(initial=1500, k=20, home_advantage=65)
    # Equal ratings: home expected > 0.5 due to HA
    row = elo.update_match("A", "B", 1, 1, league="E0")
    assert row["p_home_win_elo"] > 0.5

"""Unit tests for Poisson probabilities and attack/defense fit."""

from pathlib import Path

import pytest

from socceran.data import load_sample_fixture
from socceran.poisson import PoissonModel, poisson_1x2

FIXTURE = Path(__file__).parent / "fixtures" / "sample_matches.csv"


def test_poisson_1x2_sums_to_one():
    out = poisson_1x2(1.4, 1.1, max_goals=10)
    s = out["p_home"] + out["p_draw"] + out["p_away"]
    assert s == pytest.approx(1.0, abs=1e-9)
    assert out["xg_home"] == 1.4
    assert out["xg_away"] == 1.1


def test_poisson_strong_home_favoured():
    out = poisson_1x2(2.5, 0.6, max_goals=12)
    assert out["p_home"] > out["p_draw"] > out["p_away"] * 0.5
    assert out["p_home"] > 0.6


def test_poisson_equal_xg_drawish():
    out = poisson_1x2(1.2, 1.2, max_goals=10)
    assert out["p_home"] == pytest.approx(out["p_away"], abs=1e-9)
    assert out["p_draw"] > 0.2


def test_fit_and_predict_offline():
    matches = load_sample_fixture(FIXTURE)
    model = PoissonModel(mode="goals", prior_strength=4.0, home_attack_boost=1.15)
    model.fit(matches)
    assert "E0::Alpha" in model.attack
    pred = model.predict_match("Alpha", "Beta", "E0")
    s = pred["p_home"] + pred["p_draw"] + pred["p_away"]
    assert s == pytest.approx(1.0, abs=1e-9)
    assert pred["xg_home"] > 0
    assert pred["xg_away"] > 0

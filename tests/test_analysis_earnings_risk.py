from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.analysis import earnings_risk
from src.models import trading, trial_log
from tests.test_models_trading import SMALL, _synthetic


def test_flag_counts_overdue_as_inside_and_nan_as_unknown():
    got = earnings_risk.flag(pd.Series([0.0, 21.0, 22.0, np.nan]), 21)
    assert got.tolist() == ["inside", "inside", "outside", "unknown"]


def test_realized_inside_is_the_next_reaction_within_the_holding_window():
    cal = pd.bdate_range("2020-01-01", periods=30)
    rows = pd.DataFrame({"ticker": ["A", "A", "A", "B", "C"],
                         "date": [cal[0], cal[5], cal[10], cal[0], cal[0]]}, index=[10, 11, 12, 13, 14])
    react = earnings_risk.reactions(
        pd.DataFrame({"ticker": ["A", "A", "B"], "reaction_date": [cal[5], cal[20], cal[3]]}))
    got = earnings_risk.realized_inside(rows, react, window=5)
    # A on day 0: reaction 5 business days out, inside 1..5; on day 5 the same-day
    # reaction is t's own (not after t), the next is 15 out; on day 10, 10 out
    assert got.to_dict() == {10: True, 11: False, 12: False, 13: True, 14: False}
    assert earnings_risk.realized_inside(rows, react, window=10).loc[12]
    # business days, as the flag counts them: Thanksgiving 2020 (Thu) still counts
    thu = pd.DataFrame({"ticker": ["A"], "date": [pd.Timestamp("2020-11-23")]})
    held = earnings_risk.reactions(pd.DataFrame({"ticker": ["A"], "reaction_date": [pd.Timestamp("2020-11-30")]}))
    assert earnings_risk.realized_inside(thu, held, window=5).iloc[0]
    assert not earnings_risk.realized_inside(thu, held, window=4).iloc[0]


@pytest.fixture
def logged(tmp_path, monkeypatch):
    features, labels = _synthetic(shuffled=False)
    monkeypatch.setattr(trading.dataset, "read_labels", lambda d, h, cell: labels)
    sc = replace(SMALL, experiment_id="F2", track="B", band=0.001, verdict_k=5, ci=0.95)
    trials, art = tmp_path / "TRIALS.csv", tmp_path / "art"
    trading.run_horizon(sc, 21, features, tmp_path, trials_path=trials, artifacts_root=art)
    return sc, features, labels, trial_log.read_trials(trials), art


def _run(logged, d2e, tmp_path):
    sc, features, labels, trials, art = logged
    features = features.assign(days_to_earnings_expected=d2e)
    earnings = pd.DataFrame({"ticker": features["ticker"].iloc[:1], "reaction_date": features["date"].iloc[:1]})
    return earnings_risk.run(features, earnings, tmp_path, trials, sc, artifacts_root=art, require_clean=False)


def test_no_flag_leaves_the_basket_unchanged_and_is_dead(logged, tmp_path):
    out = _run(logged, np.nan, tmp_path)[21]
    for side in ("reference", "model"):
        for w, v in out[side]["windows"].items():
            assert v["point_estimate"] == 0 and v["verdict"] == trading.DEAD
        assert out[side]["flag_share"]["unknown"] == 1


def test_excluding_the_planted_winners_hurts(logged, tmp_path):
    sc, features, labels, *_ = logged
    # flag inside exactly the rows that go on to rise (a plant, not a feature)
    up = features[["ticker", "date"]].merge(labels[["ticker", "date", "ret"]], how="left")["ret"].gt(0)
    out = _run(logged, np.where(up, 5.0, 40.0), tmp_path)[21]
    v = out["model"]["windows"][21]
    assert v["verdict"] == trading.NEGATIVE and v["ci_high"] < 0
    split = out["model"]["by_flag"]
    assert split["inside"]["expectancy"] > split["outside"]["expectancy"]
    # one cell's daily top-K is one strategy: K a day, whatever the number of cells
    assert sum(s["trades_per_year"] for s in split.values()) == pytest.approx(earnings_risk.K * 252, rel=0.05)
    assert set(out["model"]["by_cell"]) == {"2/1.5"}
    assert set(out["model"]["windows"]) == set(earnings_risk.WINDOWS)
    assert earnings_risk.report_lines({21: out}, sc.band)[0].startswith("F3:")

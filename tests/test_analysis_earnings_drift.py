import numpy as np
import pandas as pd
import pytest

from src.analysis import earnings_drift as drift
from src.models import trading


def test_trailing_cuts_use_only_earlier_events():
    days = pd.bdate_range("2015-01-01", periods=300)
    events = pd.DataFrame({"ticker": "A", "date": days, "sue": np.arange(300.0)})
    cuts = drift.trailing_cuts(events, 0.9).set_index("date")
    # fewer than MIN_TRAILING_EVENTS before: no cut
    assert cuts["hi"].iloc[: drift.MIN_TRAILING_EVENTS].isna().all()
    # on day i the window is days [i - 365 calendar days, i): values strictly below i
    i = 250
    assert cuts["hi"].iloc[i] < i and cuts["n_trailing"].iloc[i] == i
    assert cuts["hi"].iloc[i] == pytest.approx(np.quantile(np.arange(i), 0.9))


def test_forward_returns_keep_a_delisted_tickers_terminal_return():
    days = pd.bdate_range("2020-01-01", periods=10)
    live = pd.DataFrame({"ticker": "L", "date": days, "open": 100.0, "close": np.linspace(100, 109, 10)})
    gone = pd.DataFrame({"ticker": "D", "date": days[:5], "open": 50.0, "close": [50, 50, 50, 50, 25.0]})
    fwd = drift.forward_returns(pd.concat([live, gone]), 3).set_index(["ticker", "date"])["fwd"]
    assert fwd[("L", days[0])] == pytest.approx(np.log(103 / 100))
    assert np.isnan(fwd[("L", days[8])])  # a live window past the data's end is dropped
    assert fwd[("D", days[3])] == pytest.approx(np.log(25 / 50))  # terminal: last close


def test_buckets_are_nan_when_a_rank_is():
    f = pd.DataFrame({"mom_12_1_rank": [0.1, 0.95, np.nan], "mom_1_0_rank": [0.5, 1.0, 0.2]})
    got = drift._buckets(f, ("mom_12_1_rank", "mom_1_0_rank"))
    assert got.tolist()[:2] == ["1_2", "5_3"] and pd.isna(got.iloc[2])


def _panel(planted: float, seed: int = 0):
    """300 names x 600 days (~20 per momentum bucket); each name reports every
    60 sessions (5 a day),
    its SUE uniform; its forward return is momentum-driven noise plus
    `planted` x sign(SUE)."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2014-01-01", periods=600)
    names = [f"T{i:03d}" for i in range(300)]
    rows = pd.DataFrame({"ticker": np.tile(names, len(days)), "date": np.repeat(days, len(names))})
    rows["mom_12_1_rank"] = rng.uniform(0.01, 1, len(rows))
    rows["mom_1_0_rank"] = rng.uniform(0.01, 1, len(rows))
    rows["fwd"] = rng.normal(0, 0.05, len(rows)) + 0.02 * rows["mom_12_1_rank"]
    rows["sue"] = 0.0
    day_i = np.repeat(np.arange(len(days)), len(names))
    is_event = pd.Series((day_i + np.tile(np.arange(len(names)), len(days))) % 60 == 0, index=rows.index)
    rows.loc[is_event, "sue"] = rng.uniform(-1, 1, is_event.sum())
    events = rows.loc[is_event, ["ticker", "date", "sue"]].reset_index(drop=True)
    rows.loc[is_event, "fwd"] += planted * np.sign(rows.loc[is_event, "sue"])
    return rows, events


def test_a_planted_drift_is_recovered_beyond_momentum():
    rows, events = _panel(planted=0.03)
    cuts = drift.trailing_cuts(events, 0.8)
    d = drift.deltas(rows, events, cuts, ("mom_12_1_rank", "mom_1_0_rank"))
    assert len(d) > 50 and set(d["side"]) == {-1, 1}
    s = drift.summarize(d, "signed", 21)
    assert s["point"] == pytest.approx(0.03, abs=0.01) and s["verdict"] == trading.POSITIVE


def test_no_drift_is_not_an_effect():
    rows, events = _panel(planted=0.0, seed=1)
    d = drift.deltas(rows, events, drift.trailing_cuts(events, 0.8), ("mom_12_1_rank", "mom_1_0_rank"))
    s = drift.summarize(d, "signed", 21)
    assert s["ci_low"] < 0 < s["ci_high"]

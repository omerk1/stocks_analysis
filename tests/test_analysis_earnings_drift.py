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
    days = pd.bdate_range("2020-01-01", periods=20)
    live = pd.DataFrame({"ticker": "L", "date": days, "open": 100.0, "close": np.linspace(100, 119, 20)})
    gone = pd.DataFrame({"ticker": "D", "date": days[:5], "open": 50.0, "close": [50, 50, 50, 50, 25.0]})
    # bars that stop just short of the end (a vendor gap, not a delisting)
    short = pd.DataFrame({"ticker": "S", "date": days[:17], "open": 10.0, "close": 10.0})
    fwd = drift.forward_returns(pd.concat([live, gone, short]), 3).set_index(["ticker", "date"])["fwd"]
    assert fwd[("L", days[0])] == pytest.approx(np.log(103 / 100))
    assert np.isnan(fwd[("L", days[18])])  # a live window past the data's end is dropped
    assert fwd[("D", days[3])] == pytest.approx(np.log(25 / 50))  # terminal: last close
    assert np.isnan(fwd[("S", days[15])])  # not truncated into a fake terminal return


def test_an_event_is_the_quarters_own_session_not_a_late_first_row(monkeypatch):
    days = pd.bdate_range("2015-01-01", periods=40)
    known = pd.DataFrame({"ticker": ["A", "B", "C", "C"],
                          "known_at": [days[5], days[2], days[10], days[10]], "value": [1.0, 2.0, 3.0, 4.0]})
    monkeypatch.setattr(drift.fundamentals, "quarter_features", lambda fund: {"sue_net_income": known})
    features = pd.concat([
        pd.DataFrame({"ticker": "A", "date": days, "sue_net_income": np.where(days >= days[5], 1.0, np.nan)}),
        # B joins the cache 20 sessions after its quarter became known: no event
        pd.DataFrame({"ticker": "B", "date": days[20:], "sue_net_income": 2.0}),
        # C: two quarters known the same day; the row carries the later one, one event
        pd.DataFrame({"ticker": "C", "date": days, "sue_net_income": np.where(days >= days[10], 4.0, np.nan)}),
    ])
    got = drift.sue_events(features, None)
    assert got[["ticker", "date", "sue"]].values.tolist() == [["A", days[5], 1.0], ["C", days[10], 4.0]]


def test_controls_near_an_event_are_counted_in_business_days():
    days = pd.bdate_range("2015-01-01", periods=30)
    rows = pd.DataFrame({"ticker": ["A"] * 30 + ["B"] * 30, "date": list(days) * 2})
    rows = rows[~((rows["ticker"] == "A") & rows["date"].isin(days[11:15]))]  # A ineligible for a while
    near = drift.near_events(rows, pd.DataFrame({"ticker": ["A"], "date": [days[10]]}), sessions=5)
    a = rows.assign(near=near)[lambda r: r["ticker"] == "A"].set_index("date")["near"]
    assert a[days[5]] and a[days[15]] and not a[days[16]] and not a[days[4]]
    assert not near[rows["ticker"] == "B"].any()


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
    rows["near"] = drift.near_events(rows, events)
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

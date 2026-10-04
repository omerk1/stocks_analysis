import numpy as np
import pandas as pd
import pytest

from src.models import metrics
from src.models.labels.barriers import BarrierCell

CELL = BarrierCell(horizon=5, upper=2.0, lower=1.0)  # computable from 3 x 10 = 30 dates


def _frame(n_dates=40, names=25, seed=0, informative=False):
    """Synthetic predictions: a uniform model, or one whose P(+1) is the true
    probability of +1 (then outcomes are drawn from it)."""
    rng = np.random.default_rng(seed)
    dates = np.repeat(pd.bdate_range("2015-01-01", periods=n_dates), names)
    n = len(dates)
    if informative:
        p_up = rng.uniform(0.1, 0.7, n)
        p_down = (1 - p_up) * 0.6
    else:
        p_up = np.full(n, 1 / 3)
        p_down = np.full(n, 1 / 3)
    p_neither = 1 - p_up - p_down
    u = rng.uniform(size=n)
    hit = np.where(u < p_up, 1, np.where(u < p_up + p_down, -1, 0)).astype(float)
    return pd.DataFrame({
        "date": dates, "ticker": [f"T{i % names:03d}" for i in range(n)],
        "p_up": p_up, "p_down": p_down, "p_neither": p_neither, "hit": hit,
        "ret": np.where(hit == 1, 0.04, np.where(hit == -1, -0.02, 0.001)),
        "atr": 2.0, "close_t": 100.0, "tie": False,
    })


def test_brier_and_log_loss_by_hand():
    f = pd.DataFrame({"date": pd.Timestamp("2020-01-02"), "p_up": [1.0, 1 / 3], "p_down": [0.0, 1 / 3],
                      "p_neither": [0.0, 1 / 3], "hit": [1.0, -1.0]})
    np.testing.assert_allclose(metrics.brier_rows(f), [0.0, 2 / 3])
    np.testing.assert_allclose(metrics.log_loss_rows(f), [0.0, np.log(3)], atol=1e-12)


def test_log_loss_is_finite_at_a_confident_miss():
    f = pd.DataFrame({"p_up": [1.0], "p_down": [0.0], "p_neither": [0.0], "hit": [-1.0]})
    assert np.isfinite(metrics.log_loss_rows(f).iloc[0])


def test_reliability_bins():
    f = pd.DataFrame({"date": pd.to_datetime(["2020-01-02"] * 3 + ["2020-01-03"]),
                      "p_up": [0.05, 0.05, 0.95, 1.0], "p_down": 0.0, "p_neither": 0.0,
                      "hit": [1.0, 0.0, 1.0, 1.0]})
    r = metrics.reliability(f, cls=1)
    assert len(r) == 10 and r["n_rows"].sum() == 4
    assert r.loc[0, "n_rows"] == 2 and r.loc[0, "observed"] == 0.5 and r.loc[0, "mean_pred"] == pytest.approx(0.05)
    assert r.loc[9, "n_rows"] == 2 and r.loc[9, "n_dates"] == 2 and r.loc[9, "observed"] == 1.0
    assert r.loc[5, "n_rows"] == 0 and np.isnan(r.loc[5, "mean_pred"])


def test_daily_ic_sign_and_minimum_names():
    f = _frame(n_dates=3, names=25)
    f["p_up"] = f["hit"] + np.random.default_rng(1).uniform(0, 0.1, len(f))  # same ordering as hit
    assert metrics.daily_ic(f).gt(0.9).all()
    f["p_up"] = -f["p_up"]
    assert metrics.daily_ic(f).lt(-0.9).all()
    assert metrics.daily_ic(f, min_names=26).isna().all()


def test_ev_uses_decision_time_prices_not_the_entry():
    f = _frame(n_dates=1, names=3)
    f[["p_up", "p_down", "p_neither"]] = [[0.5, 0.25, 0.25]] * 3
    ev = metrics.expected_value(f, CELL, neither_ret=0.01)
    # 0.5 * 2 * 2/100 - 0.25 * 1 * 2/100 + 0.25 * 0.01
    np.testing.assert_allclose(ev, 0.0175)
    with_entry = f.assign(entry_price=[50.0, 100.0, 200.0])
    np.testing.assert_allclose(metrics.expected_value(with_entry, CELL, 0.01), ev)


def test_top_k_picks_costs_and_ties():
    f = _frame(n_dates=2, names=4)
    f["p_up"] = [0.6, 0.6, 0.2, 0.1] * 2   # T000/T001 tie on EV; ticker breaks it
    f["p_down"] = 0.2
    f["p_neither"] = 1 - f["p_up"] - f["p_down"]
    f["hit"] = [1.0, -1.0, 1.0, 0.0] * 2
    f["ret"] = [0.05, -0.02, 0.04, 0.0] * 2
    daily = metrics.top_k_daily(f, CELL, neither_ret=0.0, k=1)
    assert (daily["hit_rate"] == 1.0).all() and np.allclose(daily["ret"], 0.05)
    np.testing.assert_allclose(daily["ret_net_10bps"], 0.049)
    np.testing.assert_allclose(daily["ret_net_25bps"], 0.0475)
    big = metrics.top_k_daily(f, CELL, neither_ret=0.0, k=20)
    assert (big["n_picked"] == 4).all()


def test_cell_metrics_not_computable_below_the_block_minimum():
    few = metrics.cell_metrics(_frame(n_dates=29), CELL, neither_ret=0.0, by=None)
    assert few.loc[0, "status"] == metrics.NOT_COMPUTABLE
    assert few.loc[0, "n_dates"] == 29 and few.loc[0, "n_rows"] == 29 * 25
    assert "brier" not in few or np.isnan(few.loc[0, "brier"])
    ok = metrics.cell_metrics(_frame(n_dates=30), CELL, neither_ret=0.0, by=None)
    assert ok.loc[0, "status"] == metrics.OK and np.isfinite(ok.loc[0, "brier"])


def test_cell_metrics_per_group_and_counts():
    f = pd.concat([_frame(n_dates=40, seed=1).assign(fold="a"),
                   _frame(n_dates=10, seed=2).assign(fold="b", date=lambda d: d["date"] + pd.Timedelta(days=400))])
    f["capped"] = f["ticker"].isin(["T000", "T001"])
    f.loc[f.index[:5], "hit"] = np.nan  # unresolved windows are dropped
    out = metrics.cell_metrics(f, CELL, neither_ret=0.0, by="fold").set_index("fold")
    assert out.loc["a", "status"] == metrics.OK and out.loc["b", "status"] == metrics.NOT_COMPUTABLE
    assert out.loc["a", "n_rows"] == 40 * 25 - 5
    assert out.loc["a", "capped_share"] == pytest.approx(2 / 25, abs=0.01)
    assert out.loc["a", "brier"] == pytest.approx(2 / 3)  # the uniform model's Brier, whatever happens


def test_informative_model_beats_uniform_on_every_metric():
    good = metrics.cell_metrics(_frame(n_dates=60, informative=True, seed=3), CELL, 0.0, by=None).iloc[0]
    flat = metrics.cell_metrics(_frame(n_dates=60, seed=3), CELL, 0.0, by=None).iloc[0]
    assert good["brier"] < flat["brier"] and good["log_loss"] < flat["log_loss"]
    assert good["ic_mean"] > 0.1
    assert good["top5_hit_rate"] > good["base_rate_up"]


def test_reliability_drops_unresolved_rows_and_missing_probabilities():
    f = pd.DataFrame({"date": pd.to_datetime(["2020-01-02"] * 4),
                      "p_up": [0.95, 0.95, np.nan, 0.95], "p_down": 0.0, "p_neither": 0.0,
                      "hit": [1.0, 1.0, 1.0, np.nan]})
    r = metrics.reliability(f, cls=1)
    assert r["n_rows"].sum() == 2 and r.loc[9, "observed"] == 1.0


def test_top_k_excess_removes_the_days_own_move():
    f = _frame(n_dates=2, names=4)
    f["p_up"] = [0.6, 0.3, 0.2, 0.1] * 2
    f["p_down"] = 0.2
    f["p_neither"] = 1 - f["p_up"] - f["p_down"]
    f["ret"] = [0.05, 0.03, 0.02, 0.0] + [0.15, 0.13, 0.12, 0.10]  # day 2: everything +10%
    daily = metrics.top_k_daily(f, CELL, neither_ret=0.0, k=1)
    np.testing.assert_allclose(daily["ret"], [0.05, 0.15])
    np.testing.assert_allclose(daily["excess"], [0.025, 0.025])  # same pick quality both days

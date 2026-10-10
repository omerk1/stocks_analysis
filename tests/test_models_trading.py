import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.models import trading, trial_log
from src.models.ablation import B4_COLUMNS, LABEL_COLS, dataset
from src.models.labels.barriers import BarrierCell
from src.models.learners import BoostingConfig
from src.models.synthetic import PlantedSpec, planted_panel, shuffle_within_date

FAST = BoostingConfig(max_iter=50, min_samples_leaf=50)


def test_the_model_is_every_registered_column_and_the_reference_is_b4():
    from src.models.features.registry import model_input, model_specs
    assert set(trading.FULL_COLUMNS) == {model_input(s) for s in model_specs()}
    assert trading.Scorecard().reference_columns == B4_COLUMNS
    assert len(trading.Scorecard().cells(63)) == 9
    assert [(c.upper, c.lower) for c in trading.Scorecard(grid=((2.0, 1.5),)).cells(21)] == [(2.0, 1.5)]


def test_trade_stats_reads_wins_losses_and_costs():
    trades = pd.DataFrame({"date": pd.to_datetime(["2020-01-02"] * 2 + ["2020-01-03"] * 2),
                           "ticker": list("ABCD"), "hit": [1, -1, 0, 1], "ret": [0.04, -0.02, 0.0015, 0.03]})
    s = trading.trade_stats(trades, cost_bps=10, n_years=0.5)
    assert s["n_trades"] == 4 and s["n_dates"] == 2 and s["trades_per_year"] == 8
    assert (s["target_rate"], s["stop_rate"], s["timeout_rate"]) == (0.5, 0.25, 0.25)
    # net: 0.039, -0.021, 0.0005, 0.029 -> three wins, one loss
    assert s["win_rate"] == 0.75
    assert s["avg_win"] == pytest.approx((0.039 + 0.0005 + 0.029) / 3)
    assert s["avg_loss"] == pytest.approx(-0.021)
    assert s["payoff_ratio"] == pytest.approx(s["avg_win"] / 0.021)
    assert s["profit_factor"] == pytest.approx(0.0685 / 0.021)
    assert s["expectancy"] == pytest.approx((0.04 - 0.02 + 0.0015 + 0.03) / 4 - 0.001)


def test_portfolio_compounds_non_overlapping_holds():
    days = pd.bdate_range("2020-01-01", periods=252)
    p = trading.portfolio(pd.Series(0.01, index=days), horizon=2, cost_bps=10)
    # 126 holds of +1% a year, whichever day it starts on
    assert p["annual_return"] == pytest.approx(1.01 ** 126 - 1)
    assert p["max_drawdown"] == 0 and p["n_start_days"] == 2
    assert p["cost_drag"] == pytest.approx(126 * 0.001)
    falling = trading.portfolio(pd.Series([0.1, -0.5, 0.1, -0.5], index=days[:4]), horizon=1, cost_bps=0)
    assert falling["max_drawdown"] == pytest.approx(1.1 * 0.5 * 1.1 * 0.5 / 1.1 - 1)
    # too short for two holds from any start day: NaN, not a crash
    assert np.isnan(trading.portfolio(pd.Series(0.01, index=days[:2]), horizon=2, cost_bps=0)["annual_return"])


def test_picks_take_each_dates_highest_ev():
    d = pd.to_datetime(["2020-01-02"] * 3 + ["2020-01-03"] * 3)
    preds = pd.DataFrame({"ticker": list("ABCABC"), "date": d, "fold": 2020,
                          "p_up": [0.5, 0.2, 0.5, 0.1, 0.6, 0.3], "p_down": [0.2, 0.5, 0.2, 0.6, 0.1, 0.3]})
    preds["p_neither"] = 1 - preds["p_up"] - preds["p_down"]
    frame = preds[["ticker", "date"]].assign(hit=1.0, ret=np.arange(6) / 100, atr=1.0, close_t=50.0)
    got = trading.picks(preds, frame, BarrierCell(21, 2.0, 1.0), {2020: 0.0}, k=1)
    assert list(got["ticker"]) == ["A", "B"]  # A and C tie on the 2nd: ticker breaks it


def _synthetic(shuffled: bool):
    """The planted panel under registered names: one MA column is the planted
    x (B4's columns are noise), so only the model can find the edge."""
    panel = planted_panel(PlantedSpec(n_tickers=60, start="2015-01-02", seed=3))
    if shuffled:
        panel = shuffle_within_date(panel, seed=1)
    rng = np.random.default_rng(0)
    features = panel[["ticker", "date"]].copy()
    for c in trading.FULL_COLUMNS:
        features[c] = rng.uniform(size=len(panel)).astype("float32")
    features["sector"] = pd.Categorical(rng.choice(["A", "B"], len(panel)))
    features["slope_log_21_sma_50_rank"] = panel["x"].astype("float32")
    features.attrs["manifest"] = {"created": "test", "universe": {"indices": ["sp500"], "floors": {}},
                                  "start": "2015-01-02", "end": "2021-12-31", "open_holdout": False,
                                  "disputes": dataset.disputes_fingerprint()}
    labels = panel[["ticker", "date", *LABEL_COLS]].copy()
    labels.attrs["manifest"] = {"created": "test", "disputes": "x", "n_disputed_dropped": 0}
    return features, labels


SMALL = trading.Scorecard(horizons=(21,), grid=((2.0, 1.5),), n_boot=200, test_years=(2019, 2020, 2021),
                          first_train_start="2015-01-02", eras=((2019,), (2020, 2021)), config=FAST)


@pytest.mark.parametrize("shuffled", [False, True])
def test_the_scorecard_finds_a_planted_edge_and_nothing_in_noise(tmp_path, monkeypatch, shuffled):
    features, labels = _synthetic(shuffled)
    monkeypatch.setattr(trading.dataset, "read_labels", lambda d, h, cell: labels)
    trials = tmp_path / "TRIALS.csv"

    [r] = trading.run_horizon(SMALL, 21, features, tmp_path, trials_path=trials, artifacts_root=tmp_path / "art")

    logged = trial_log.read_trials(trials)
    assert list(logged["status"]) == ["ok"] and logged.loc[0, "experiment_id"] == "S1"
    assert json.loads(logged.loc[0, "feature_groups"])["track"] == "A"
    assert logged.loc[0, "outcome"].startswith("Track A, no verdict")
    assert (tmp_path / "art" / r["trial_id"] / "predictions.parquet").exists()
    m = r["by_k"][5]
    if shuffled:
        assert m["vs_market"]["ci_low"] < 0 < m["vs_market"]["ci_high"]
        assert m["vs_reference"]["ci_low"] < 0 < m["vs_reference"]["ci_high"]
    else:
        assert m["vs_market"]["ci_low"] > 0 and m["vs_reference"]["ci_low"] > 0
        net = {s: m[s]["costs"][10]["expectancy"] for s in trading.STRATEGIES}
        assert net["model"] > net["reference"] and net["model"] > net["market"]
        assert m["model"]["costs"][0]["expectancy"] - net["model"] == pytest.approx(0.001)
        # the planted edge moves which barrier is hit first, so it shows in the target rate
        assert m["model"]["costs"][10]["target_rate"] > m["market"]["costs"][10]["target_rate"]
    assert sum(e["n_dates"] for e in m["model"]["by_era"].values()) == m["vs_market"]["n_dates"]
    table = trading.grid_table([r], k=5)
    assert list(table[["H", "U", "D"]].iloc[0]) == [21, 2.0, 1.5]


def test_ev_atr_ranks_the_edge_per_unit_of_risk():
    d = pd.to_datetime(["2020-01-02"] * 2)
    # A has the better odds; B is three times as volatile, so its EV in return units is larger
    preds = pd.DataFrame({"ticker": ["A", "B"], "date": d, "fold": 2020, "p_up": [0.5, 0.45],
                          "p_down": [0.2, 0.25], "p_neither": [0.3, 0.3]})
    frame = preds[["ticker", "date"]].assign(hit=1.0, ret=0.01, atr=[1.0, 3.0], close_t=50.0)
    cell = BarrierCell(21, 2.0, 1.0)
    assert list(trading.picks(preds, frame, cell, {2020: 0.0}, k=1)["ticker"]) == ["B"]
    assert list(trading.picks(preds, frame, cell, {2020: 0.0}, 1, "ev_atr", {2020: 0.0})["ticker"]) == ["A"]
    # Now B (volatile) has the better odds: 0.45*2 - 0.25 = 0.65 ATR vs A's 0.5.
    # A large "neither" return is the same number of ATRs for both, so B stays
    # ahead. Dividing return-EV by ATR / close would divide the 5% "neither"
    # return by each name's volatility and put A first (1.25 vs 0.90).
    flipped = preds.assign(p_up=[0.4, 0.45], p_down=[0.3, 0.25])
    assert list(trading.picks(flipped, frame, cell, {2020: 0.05}, 1, "ev_atr", {2020: 0.5})["ticker"]) == ["B"]
    with pytest.raises(ValueError):
        trading.picks(preds, frame, cell, {2020: 0.0}, k=1, rank="sharpe")
    with pytest.raises(ValueError, match="neither_atr"):
        trading.picks(preds, frame, cell, {2020: 0.0}, k=1, rank="ev_atr")


def test_random_picks_take_k_names_a_day_without_looking():
    days = pd.bdate_range("2020-01-01", periods=40)
    every = pd.DataFrame({"date": np.repeat(days, 30), "ticker": np.tile([f"T{i}" for i in range(30)], 40),
                          "hit": 0.0, "ret": 0.0})
    every["ret"] = np.tile(np.linspace(-0.05, 0.05, 30), 40)
    rng = np.random.default_rng(0)
    one = trading.random_picks(every, 5, rng)
    assert one.groupby("date").size().eq(5).all()
    assert trading.random_picks(every, 5, rng)["ticker"].tolist() != one["ticker"].tolist()
    p = trading.random_portfolio(every, 5, horizon=2, cost_bps=10, draws=5)
    assert p["n_draws"] == 5 and p["annual_return_min"] <= p["annual_return"] <= p["annual_return_max"]


def test_rescore_reuses_the_archived_predictions(tmp_path, monkeypatch):
    features, labels = _synthetic(shuffled=False)
    monkeypatch.setattr(trading.dataset, "read_labels", lambda d, h, cell: labels)
    trials, art = tmp_path / "TRIALS.csv", tmp_path / "art"
    [first] = trading.run_horizon(SMALL, 21, features, tmp_path, trials_path=trials, artifacts_root=art)
    monkeypatch.setattr(trading, "oos_predictions", lambda *a, **k: pytest.fail("rescore must not refit"))

    [again] = trading.rescore(SMALL, trial_log.read_trials(trials), features, tmp_path, trials_path=trials,
                              artifacts_root=art)
    [ev_atr] = trading.rescore(replace(SMALL, rank="ev_atr"), trial_log.read_trials(trials), features, tmp_path,
                               trials_path=trials, artifacts_root=art)

    logged = trial_log.read_trials(trials)
    assert list(logged["experiment_id"]) == ["S1", "S1b", "S1b"]
    assert json.loads(logged.loc[2, "feature_groups"])["rescored_from"] == first["trial_id"]
    assert json.loads(logged.loc[2, "feature_groups"])["rank"] == "ev_atr"
    # the same predictions and ranking score the same
    assert again["by_k"][5]["model"]["costs"][10] == first["by_k"][5]["model"]["costs"][10]
    assert ev_atr["by_k"][5]["model"]["atr_pct"] <= first["by_k"][5]["model"]["atr_pct"]
    assert again["by_k"][5]["random"]["portfolio"]["n_draws"] == trading.RANDOM_DRAWS
    with pytest.raises(ValueError, match="hyperparameters"):
        trading.rescore(replace(SMALL, config=BoostingConfig(max_iter=51, min_samples_leaf=50)),
                        trial_log.read_trials(trials), features, tmp_path, trials_path=trials, artifacts_root=art)
    rebuilt = labels.copy()
    rebuilt.attrs["manifest"] = {**labels.attrs["manifest"], "created": "later"}
    monkeypatch.setattr(trading.dataset, "read_labels", lambda d, h, cell: rebuilt)
    with pytest.raises(ValueError, match="labels_built"):
        trading.rescore(SMALL, trial_log.read_trials(trials), features, tmp_path, trials_path=trials,
                        artifacts_root=art)
    with pytest.raises(ValueError, match="other columns"):
        trading.rescore(replace(SMALL, model_columns=B4_COLUMNS), trial_log.read_trials(trials), features,
                        tmp_path, trials_path=trials, artifacts_root=art)

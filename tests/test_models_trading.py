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


def test_the_model_is_the_s1_columns_and_the_reference_is_b4():
    """FULL_COLUMNS stays S1's set (B4 + MA family) so S1/S1b reproduce; the
    step-2b columns registered since join through their own column set."""
    from src.models.features.registry import model_input, model_specs
    s1 = [s for s in model_specs() if s.group in ("baseline", "ma")]
    assert set(trading.FULL_COLUMNS) == {model_input(s) for s in s1}
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
    # A and C tie on the 2nd: the tie key decides, the same way every run
    assert got["ticker"].iloc[1] == "B" and got["ticker"].iloc[0] in ("A", "C")
    assert got.equals(trading.picks(preds, frame, BarrierCell(21, 2.0, 1.0), {2020: 0.0}, k=1))


def test_tied_scores_are_not_broken_by_ticker_name():
    """A flat prediction (an isotonic plateau) must pick a different, neutral
    set of names each day, not the alphabetically first ones every day."""
    days = pd.bdate_range("2020-01-01", periods=200)
    names = [f"T{i:02d}" for i in range(40)]
    preds = pd.DataFrame({"ticker": np.tile(names, len(days)), "date": np.repeat(days, len(names)), "fold": 2020,
                          "p_up": 0.4, "p_down": 0.3, "p_neither": 0.3})
    frame = preds[["ticker", "date"]].assign(hit=0.0, ret=0.0, atr=1.0, close_t=50.0)
    got = trading.picks(preds, frame, BarrierCell(21, 2.0, 1.0), {2020: 0.0}, 5, "ev_atr", {2020: 0.0})
    counts = got["ticker"].value_counts().reindex(names, fill_value=0)
    # 1,000 picks over 40 names: ~25 each; by name, T00-T04 would take all 200 days
    assert counts.max() < 50 and counts.loc[names[:5]].sum() < 250


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
        # Nothing in noise: within 2.6 bootstrap SEs of zero (a 99% two-sided
        # band). Not "the 90% CI spans zero": with ~18 date blocks the CIs
        # under-cover, and on noise they left out zero at about one readout
        # in five (Done #152).
        for other in ("market", "reference"):
            assert abs(m[f"vs_{other}"]["point_estimate"]) < 2.6 * m[f"vs_{other}"]["boot_std"]
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


def test_f2_compares_the_group_with_the_model_on_main_without_it():
    """F2's column lists are frozen literals; pinned here to the registry's
    groups as of the pre-registration (docs/fundamentals/PREREGISTRATION.md)."""
    from src.models.features.registry import model_input, model_specs
    sc = trading.PREREGISTERED["F2"]
    groups = lambda *g: {model_input(s) for s in model_specs() if s.group in g}
    assert set(sc.reference_columns) == groups("baseline", "ma", "volatility", "volume", "oscillator", "market",
                                               "relative")
    assert set(sc.model_columns) - set(sc.reference_columns) == groups("fundamentals")
    assert len(sc.model_columns) == len(set(sc.model_columns)) == 41
    assert (sc.track, sc.rank, sc.ci, sc.band, sc.verdict_k, sc.horizons) == ("B", "ev_atr", 0.99, 0.001, 20, (21, 63))
    with pytest.raises(ValueError, match="verdict_k"):
        replace(sc, ks=(5,))


def test_three_verdicts():
    assert trading.three_verdict(-0.0005, 0.0008, 0.001) == trading.DEAD
    assert trading.three_verdict(-0.0005, 0.002, 0.001) == trading.INCONCLUSIVE
    assert trading.three_verdict(0.0002, 0.0008, 0.001) == trading.DEAD  # inside the band, even off zero
    assert trading.three_verdict(0.0002, 0.0015, 0.001) == trading.POSITIVE
    assert trading.three_verdict(-0.003, -0.0011, 0.001) == trading.NEGATIVE
    g = trading.group_verdict
    assert g([trading.DEAD, trading.DEAD]) == trading.DEAD and g([trading.DEAD, trading.INCONCLUSIVE]) == trading.INCONCLUSIVE
    assert g([trading.POSITIVE, trading.DEAD]) == trading.POSITIVE and g([trading.NEGATIVE, trading.POSITIVE]) == trading.MIXED


def test_close_scorecard_pools_the_cells_and_judges_the_planted_edge(tmp_path, monkeypatch):
    features, labels = _synthetic(shuffled=False)
    monkeypatch.setattr(trading.dataset, "read_labels", lambda d, h, cell: labels)
    trials, art = tmp_path / "TRIALS.csv", tmp_path / "art"
    sc = replace(SMALL, experiment_id="F2", track="B", band=0.001, verdict_k=5, ci=0.95)
    [r] = trading.run_horizon(sc, 21, features, tmp_path, trials_path=trials, artifacts_root=art)
    logged = trial_log.read_trials(trials)
    assert logged.loc[0, "outcome"].startswith("Track B, verdict at close-scorecard")
    with pytest.raises(ValueError, match="Track A"):
        trading.close_scorecard(SMALL, logged, features, tmp_path, artifacts_root=art)
    empty = trading.close_scorecard(sc, logged.iloc[:0], features, tmp_path, artifacts_root=art, require_clean=False)
    assert empty["horizons"][21]["verdict"] == trading.INCONCLUSIVE and empty["horizons"][21]["missing_cells"]

    monkeypatch.setattr(trading, "oos_predictions", lambda *a, **k: pytest.fail("closing must not refit"))
    out = trading.close_scorecard(sc, logged, features, tmp_path, artifacts_root=art, require_clean=False)
    h = out["horizons"][21]
    # one cell: the pooled difference is that cell's model - reference
    assert h["point_estimate"] == pytest.approx(r["by_k"][5]["vs_reference"]["point_estimate"])
    assert h["verdict"] == trading.POSITIVE and h["ci_low"] > 0 and h["holm_positive"]
    assert out["group_verdict"] == trading.POSITIVE and h["trial_ids"] == {"2/1.5": r["trial_id"]}
    assert set(h["by_era"]) == {"2019-2019", "2020-2021"} and h["dates_missing_a_cell"] == 0
    # the caveat sensitivity re-reads the same predictions with tickers unpickable
    some = tuple(sorted(features["ticker"].unique())[:10])
    without = trading.close_scorecard(sc, logged, features, tmp_path, exclude_tickers=some, artifacts_root=art,
                                      require_clean=False)
    assert without["horizons"][21]["point_estimate"] != h["point_estimate"]
    # a first row from a dirty checkout voids the cell; it isn't replaced by a later one
    [cell] = sc.cells(21)
    spec = trading.trial_spec(sc, cell, features, labels)
    assert trading.registered_trial(sc, logged.assign(git_dirty="True"), cell, spec) is None
    assert trading.registered_trial(sc, logged, cell, spec, require_clean=False) == r["trial_id"]
    assert trading.registered_trial(replace(sc, rank="ev_atr"), logged, cell, spec, require_clean=False) is None
    # a cache rebuilt since the fit is refused, not scored silently
    rebuilt = labels.copy()
    rebuilt.attrs["manifest"] = {**labels.attrs["manifest"], "created": "later"}
    monkeypatch.setattr(trading.dataset, "read_labels", lambda d, h, cell: rebuilt)
    with pytest.raises(ValueError, match="labels_built"):
        trading.close_scorecard(sc, logged, features, tmp_path, artifacts_root=art, require_clean=False)


def test_tie_key_ignores_the_dates_storage_unit():
    from src.models.metrics import tie_key
    f = pd.DataFrame({"ticker": ["A", "B"], "date": pd.to_datetime(["2020-01-02", "2020-01-03"])})
    assert (tie_key(f) == tie_key(f.assign(date=f["date"].astype("datetime64[us]")))).all()

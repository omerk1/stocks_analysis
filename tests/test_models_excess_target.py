import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.models import excess_target, trading, trial_log
from src.models.ablation import B4_COLUMNS, LABEL_COLS, dataset
from src.models.learners import BoostedRegressor, BoostingConfig
from src.models.synthetic import PlantedSpec, planted_panel, shuffle_within_date

FAST = BoostingConfig(max_iter=50, min_samples_leaf=50)


def test_the_target_is_the_return_minus_the_dates_pool_mean():
    d1, d2 = pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-03")
    frame = pd.DataFrame({
        "ticker": ["A", "B", "C", "A", "B", "C"], "date": [d1, d1, d1, d2, d2, d2],
        "ret": [0.03, 0.00, -0.03, 0.01, 0.05, 0.02],
        "atr": [1.0, 1.0, 1.0, 1.0, np.nan, 1.0], "close_t": 50.0,
        # A on d1 is delisted early: its own window ends first
        "label_end_date": pd.to_datetime(["2020-01-10", "2020-02-01", "2020-02-01",
                                          "2020-02-03", "2020-02-20", "2020-02-04"]),
    })
    out = excess_target.excess_frame(frame, clip=(0.0, 1.0))

    assert out["market_ret"].iloc[:3].tolist() == pytest.approx([0.0] * 3)
    # B on d2 has no ATR: out of the pool, so out of the mean and with no target
    assert out["market_ret"].iloc[3] == pytest.approx(0.015) and np.isnan(out["target"].iloc[4])
    assert out["excess"].iloc[[3, 5]].tolist() == pytest.approx([-0.005, 0.005])
    # the purge window is the date's latest pool end, not the row's own
    assert out["label_end_date"].iloc[0] == pd.Timestamp("2020-02-01")
    assert out["own_label_end"].iloc[0] == pd.Timestamp("2020-01-10")
    assert out["label_end_date"].iloc[3] == pd.Timestamp("2020-02-04")


def test_the_training_target_is_clipped_per_date_but_excess_is_not():
    d = pd.Timestamp("2020-01-02")
    frame = pd.DataFrame({"ticker": list("ABCDE"), "date": d, "ret": [0.0, 0.0, 0.0, 0.0, 1.0],
                          "atr": 1.0, "close_t": 10.0, "label_end_date": pd.Timestamp("2020-02-01")})
    out = excess_target.excess_frame(frame, clip=(0.0, 0.75))
    assert out["excess"].iloc[4] == pytest.approx(0.8)
    assert out["target"].iloc[4] == pytest.approx(out["excess"].quantile(0.75))


def test_the_regressor_refuses_a_missing_target_and_predicts_per_row():
    x = pd.DataFrame({"a": np.linspace(0, 1, 200)})
    with pytest.raises(ValueError, match="non-finite"):
        BoostedRegressor(["a"], FAST, registered_only=False).fit(x, np.r_[np.nan, np.zeros(199)])
    m = BoostedRegressor(["a"], FAST, registered_only=False).fit(x, 2 * x["a"])
    p = m.predict(x)
    assert p.index.equals(x.index) and p.iloc[-1] > p.iloc[0]


def _synthetic(shuffled: bool = False):
    """The planted panel under registered names (as test_models_trading's):
    one MA column carries x, B4's columns are noise."""
    panel = planted_panel(PlantedSpec(n_tickers=60, start="2015-01-02", seed=3))
    if shuffled:
        panel = shuffle_within_date(panel, seed=1)
    rng = np.random.default_rng(0)
    features = panel[["ticker", "date"]].copy()
    for c in trading.FULL_COLUMNS:
        features[c] = rng.uniform(size=len(panel)).astype("float32")
    features["sector"] = pd.Categorical(rng.choice(["A", "B"], len(panel)))
    features["slope_log_21_sma_50_rank"] = panel["x"].astype("float32")
    features.attrs["manifest"] = {"created": "f", "universe": {"indices": ["sp500"], "floors": {}},
                                  "start": "2015-01-02", "end": "2021-12-31", "open_holdout": False,
                                  "disputes": dataset.disputes_fingerprint()}
    labels = panel[["ticker", "date", *LABEL_COLS]].copy()
    labels.attrs["manifest"] = {"created": "l", "disputes": "x", "n_disputed_dropped": 0}
    return features, labels


SMALL = trading.Scorecard(horizons=(21,), grid=((2.0, 1.5),), n_boot=200, test_years=(2019, 2020, 2021),
                          first_train_start="2015-01-02", eras=((2019,), (2020, 2021)), config=FAST,
                          rank="ev_atr")


def _frozen_runs(features, labels, tmp_path, monkeypatch):
    """The frozen model's three one-seed dev runs, as run-scorecard logs them."""
    monkeypatch.setattr(trading.dataset, "read_labels", lambda d, h, cell, open_holdout=False: labels)
    trials, art = tmp_path / "TRIALS.csv", tmp_path / "art"
    for seed, eid in zip(excess_target.SEEDS, excess_target.FROZEN_IDS):
        trading.run_horizon(replace(SMALL, experiment_id=eid, seeds=(seed,)), 21, features, tmp_path,
                            trials_path=trials, artifacts_root=art)
    return trials, art


def test_it_beats_the_frozen_runs_on_a_planted_edge_and_logs_one_trial_a_cell(tmp_path, monkeypatch):
    features, labels = _synthetic()
    trials, art = _frozen_runs(features, labels, tmp_path, monkeypatch)
    sc = replace(excess_target.scorecard(), model_columns=trading.FULL_COLUMNS, horizons=(21,),
                 grid=SMALL.grid, test_years=SMALL.test_years, first_train_start=SMALL.first_train_start,
                 eras=SMALL.eras, config=FAST)

    [r] = excess_target.run_horizon(21, features, tmp_path, art, trials, art, sc=sc)
    # a resumed run doesn't refit a logged cell
    assert excess_target.run_horizon(21, features, tmp_path, art, trials, art, sc=sc) == []

    logged = trial_log.read_trials(trials)
    mine = logged[logged["experiment_id"] == excess_target.EXPERIMENT_ID]
    assert list(mine["status"]) == ["ok"] and mine.iloc[0]["outcome"].startswith("Track A, no verdict")
    assert json.loads(mine.iloc[0]["feature_groups"])["rank"] == "pred_excess"
    preds = pd.read_parquet(art / r["trial_id"] / "predictions.parquet")
    assert set(preds["model"]) == {"new", "new_b4"}
    assert r["pairs"]["new_vs_market"]["ci_low"] > 0
    # B4's columns are noise: the new target finds nothing there
    assert abs(r["pairs"]["new_b4_vs_b4"]["point_estimate"]) < 2.6 * r["pairs"]["new_b4_vs_b4"]["boot_std"]

    out = excess_target.close(features, tmp_path, art, (21,), trials, art, n_boot=200, sc=sc)
    pooled = out["horizons"][21]["pairs"]
    assert pooled["new_vs_market"]["point_estimate"] == pytest.approx(r["pairs"]["new_vs_market"]["point_estimate"])
    assert "verdict" not in pooled["new_vs_market"]
    assert set(out["horizons"][21]["sides"]) == {*excess_target.TRADERS, "market"}
    assert out["horizons"][21]["sides"]["market"]["beta"] == pytest.approx(1.0)
    assert isinstance(out["carry_forward"]["met"], bool)


def test_the_frozen_runs_must_be_one_per_seed_on_these_caches(tmp_path, monkeypatch):
    features, labels = _synthetic()
    trials, art = _frozen_runs(features, labels, tmp_path, monkeypatch)
    cell = SMALL.cells(21)[0]
    logged = trial_log.read_trials(trials)
    p = excess_target.frozen_predictions(logged, cell, art, features, labels)
    assert set(p["model"]) == {"model", "B4"} and not p.duplicated(["ticker", "date", "model"]).any()

    rebuilt = labels.copy()
    rebuilt.attrs["manifest"] = {**labels.attrs["manifest"], "created": "later"}
    with pytest.raises(ValueError, match="other caches"):
        excess_target.frozen_predictions(logged, cell, art, features, rebuilt)
    with pytest.raises(ValueError, match="need 1"):
        excess_target.frozen_predictions(logged[logged["experiment_id"] != excess_target.FROZEN_IDS[1]], cell, art,
                                         features, labels)


def test_the_sides_refuse_pools_that_differ(tmp_path, monkeypatch):
    features, labels = _synthetic()
    trials, art = _frozen_runs(features, labels, tmp_path, monkeypatch)
    cell = SMALL.cells(21)[0]
    frozen = excess_target.frozen_predictions(trial_log.read_trials(trials), cell, art, features, labels)
    frame = excess_target.cell_frame(features, labels)
    new = frozen[frozen["model"] == "model"][["ticker", "date", "fold"]].assign(pred=0.0)
    picked, baskets = excess_target.cell_sides(frame, new, new, frozen, cell, SMALL)
    assert set(baskets) == {*excess_target.TRADERS, "market"}
    assert (picked["new"].groupby("date").size() <= excess_target.K).all()
    with pytest.raises(ValueError, match="pools differ"):
        excess_target.cell_sides(frame, new.iloc[1:], new, frozen, cell, SMALL)


def _pooled(new_frozen, beta_new, beta_frozen, atr_new=0.02, atr_frozen=0.02, years=5, ci_high=0.01):
    pair = {"point_estimate": new_frozen, "years_positive": years, "ci_high": ci_high}
    return {"pairs": {"new_vs_frozen": pair},
            "sides": {"new": {"beta": beta_new, "atr_pct": atr_new}, "frozen": {"beta": beta_frozen, "atr_pct": atr_frozen}}}


def test_carry_forward_needs_the_gain_the_years_and_calmer_picks():
    ok = _pooled(0.0012, 0.9, 1.1)
    assert excess_target.carry_forward({21: ok, 63: _pooled(-0.0005, 1.0, 1.0)})["met"]
    assert not excess_target.carry_forward({21: _pooled(0.0009, 0.9, 1.1)})["met"]          # under the band
    assert not excess_target.carry_forward({21: _pooled(0.0012, 0.9, 1.1, years=4)})["met"]  # too few years
    assert not excess_target.carry_forward({21: _pooled(0.0012, 1.2, 1.1, 0.03, 0.02)})["met"]  # not calmer
    assert not excess_target.carry_forward({21: ok, 63: _pooled(-0.004, 1.0, 1.0, ci_high=-0.001)})["met"]
    assert not excess_target.carry_forward({21: ok, 63: {"missing_cells": [(2.0, 1.0)]}})["met"]


def test_the_default_run_is_the_frozen_models_columns_on_the_dev_window():
    sc = excess_target.scorecard()
    assert sc.model_columns == trading.PREREGISTERED["HT1"].model_columns
    assert sc.reference_columns == B4_COLUMNS and sc.seeds == (0, 1, 2)
    assert max(sc.test_years) == 2021 and not sc.open_holdout

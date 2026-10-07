import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.models import ablation, trial_log
from src.models.ablation import INCONCLUSIVE, NULL, PASS, PREREGISTERED, Experiment, Step
from src.models.features.registry import check_columns, model_input, model_specs
from src.models.learners import BoostingConfig
from src.models.synthetic import PlantedSpec, planted_panel

FAST = BoostingConfig(max_iter=50, min_samples_leaf=50)


def test_e1_is_the_registered_ma_family_over_b4():
    e1 = PREREGISTERED["E1"]
    t1, t2 = e1.steps
    check_columns(list(t2.columns))
    assert set(ablation.MA_SUPPORTED) == {model_input(s) for s in model_specs("ma", ("supported",))}
    assert set(ablation.MA_WEAK) == {model_input(s) for s in model_specs("ma", ("weak",))}
    assert t1.columns[:5] == ablation.B4_COLUMNS and t2.columns[:len(t1.columns)] == t1.columns
    assert e1.n_trials == 8 and e1.reference(1) == ("T1", t1.columns)
    assert e1.cell(63).upper_atr == pytest.approx(2 * np.sqrt(3))


def test_relevance_band_is_what_a_cost_covering_signal_would_gain():
    # Cell 2/2 at H=21: U + D = 4 ATR. A spread s = 0.001 / (2.6 * 4 * 0.02)
    # lifts the top picks' EV by exactly 10 bps; its Brier gain is 2 s^2.
    cell = PREREGISTERED["E1"].cell(21)
    s = 0.001 / (2.6 * 4 * 0.02)
    assert ablation.relevance_band(cell, 10) == pytest.approx(2 * s * s)
    # Wider barriers at longer horizons: the same cost needs a smaller spread.
    bands = [ablation.relevance_band(PREREGISTERED["E1"].cell(h), 10) for h in (10, 21, 42, 63)]
    assert bands == sorted(bands, reverse=True)
    assert bands[0] / bands[1] == pytest.approx(21 / 10)


def _synthetic(n_tickers=60):
    """The planted panel under registered names: the supported slope rank is
    the planted x, everything else is noise."""
    panel = planted_panel(PlantedSpec(n_tickers=n_tickers, start="2015-01-02", seed=3))
    rng = np.random.default_rng(0)
    n = len(panel)
    features = panel[["ticker", "date"]].copy()
    for c in ablation.B4_COLUMNS + ablation.MA_SUPPORTED + ablation.MA_WEAK:
        features[c] = rng.uniform(size=n).astype("float32")
    features["sector"] = pd.Categorical(rng.choice(["A", "B"], n))
    features["slope_log_21_sma_50_rank"] = panel["x"].astype("float32")
    features.attrs["manifest"] = {"created": "test", "universe": {"indices": ["sp500"], "floors": {}},
                                  "start": "2015-01-02", "end": "2021-12-31", "open_holdout": False,
                                  "disputes": ablation.dataset.disputes_fingerprint()}
    labels = panel[["ticker", "date", *ablation.LABEL_COLS]].copy()
    labels.attrs["manifest"] = {"created": "test", "disputes": "x", "n_disputed_dropped": 0}
    return features, labels


def _small(exp: Experiment) -> Experiment:
    return replace(exp, horizons=(21,), seeds=(0, 1), n_boot=200, test_years=(2019, 2020, 2021),
                   first_train_start="2015-01-02", eras=((2019,), (2020, 2021)), min_folds_improving=2, config=FAST)


def test_a_planted_group_passes_and_a_noise_group_does_not(tmp_path, monkeypatch):
    features, labels = _synthetic()
    monkeypatch.setattr(ablation.dataset, "read_labels", lambda d, h, cell: labels)
    exp = _small(PREREGISTERED["E1"])
    trials = tmp_path / "TRIALS.csv"

    results = ablation.run_horizon(exp, 21, features, tmp_path, trials_path=trials,
                                   artifacts_root=tmp_path / "art")

    logged = trial_log.read_trials(trials)
    assert list(logged["status"]) == ["ok", "ok"] and len(results) == 2
    assert json.loads(logged.loc[0, "feature_groups"])["reference"] == "B4"
    assert json.loads(logged.loc[1, "feature_groups"])["reference"] == "T1"
    t1, t2 = results
    assert t1["brier"]["ci_high"] < 0 and t1["folds_improving"] == 3
    assert t1["brier"]["point_estimate"] < t1["band"] * -10
    assert set(t1["brier_by_seed"]) == {0, 1}
    assert (tmp_path / "art" / t1["trial_id"] / "brier.npz").exists()
    assert "vs_baseline" in t2 and "vs_baseline" not in t1
    assert t2["vs_baseline"]["brier"]["ci_high"] < 0  # T2 still holds T1's planted gain over B4

    table, groups = ablation.close_experiment(exp, logged, require_clean=False)
    assert groups["T1"] == PASS and groups["T2"] != PASS
    assert table["bh_significant"].tolist()[0]


def test_a_label_cache_missing_rows_is_refused():
    exp = _small(PREREGISTERED["E1"])
    features, labels = _synthetic(n_tickers=10)
    assert ablation.check_labels(exp, features, ablation.cell_frame(features, labels)) == 0
    later = labels[labels["date"] >= "2016-01-01"]  # built with a later start
    with pytest.raises(ValueError, match="no label"):
        ablation.check_labels(exp, features, ablation.cell_frame(features, later))


def test_a_cache_for_another_universe_is_refused():
    features, _ = _synthetic(n_tickers=5)
    features.attrs["manifest"]["universe"]["indices"] = ["sp500", "nasdaq100"]
    with pytest.raises(ValueError, match="indices"):
        ablation.check_features(_small(PREREGISTERED["E1"]), features)
    features.attrs["manifest"]["universe"]["indices"] = ["sp500"]
    features.attrs["manifest"]["disputes"] = "built-before-a-fix"
    with pytest.raises(ValueError, match="price_disputes"):
        ablation.check_features(_small(PREREGISTERED["E1"]), features)


def _trial_row(step, horizon, p, ci_low, band=1e-4, folds=6, eras=(-1e-4, -1e-4), point=None, n_boot=1000,
               date="2026-10-07T00:00:00", dirty=False, **design_changes):
    exp = PREREGISTERED["E1"]
    spec = {**ablation.design(exp, [s.name for s in exp.steps].index(step), horizon), **design_changes}
    return {"experiment_id": "E1", "status": "ok", "date": date, "git_dirty": dirty,
            "trial_id": f"{step}-{horizon}-{date}", **{f: json.dumps(v) for f, v in spec.items()},
            "metrics": json.dumps({"brier_p": p, "brier": {"point_estimate": ci_low / 2 if point is None else point,
                                                            "ci_low": ci_low, "ci_high": -ci_low, "n_boot": n_boot},
                                   "band": band, "folds_improving": folds,
                                   "brier_by_era": {"a": eras[0], "b": eras[1]}})}


def test_close_applies_bh_and_the_three_verdicts():
    exp = PREREGISTERED["E1"]
    rows = [
        _trial_row("T1", 10, 0.001, -5e-4),                         # pass
        _trial_row("T1", 21, 0.001, -5e-4, eras=(-1e-4, 2e-5)),     # significant but an era flips
        _trial_row("T1", 42, 0.4, -5e-5),                            # inside the band: null
        _trial_row("T1", 63, 0.4, -5e-4),                            # wide CI: inconclusive
        _trial_row("T2", 10, 0.001, -5e-5, point=-3e-5),             # significant but below the band: null
        *[_trial_row("T2", h, 0.5, -5e-5) for h in (21, 42, 63)],
    ]
    table, groups = ablation.close_experiment(exp, pd.DataFrame(rows))
    assert table["verdict"].tolist() == [PASS, INCONCLUSIVE, NULL, INCONCLUSIVE] + [NULL] * 4
    assert bool(table["bh_significant"].iloc[4])
    assert groups == {"T1": PASS, "T2": NULL}


def test_a_rerun_never_replaces_the_first_valid_trial():
    exp = PREREGISTERED["E1"]
    rows = [_trial_row("T1", 10, 0.001, -5e-4),
            _trial_row("T1", 10, 0.4, -5e-4, date="2026-10-08T00:00:00"),               # later rerun
            _trial_row("T1", 21, 0.001, -5e-4, n_boot=50),                              # quick look
            _trial_row("T1", 42, 0.4, -5e-4, dirty=True),                               # uncommitted code ...
            _trial_row("T1", 42, 0.001, -5e-4, date="2026-10-08T00:00:00"),             # ... then a clean rerun
            _trial_row("T1", 63, 0.001, -5e-4, seeds=[0])]                              # not the registered design
    table, _ = ablation.close_experiment(exp, pd.DataFrame(rows))
    t1 = table[table["step"] == "T1"].set_index("horizon")
    assert t1.loc[10, "p"] == 0.001 and t1.loc[10, "n_other_rows"] == 1
    assert t1.loc[[21, 42, 63], "trial_id"].isna().all()
    assert (t1.loc[[21, 42, 63], "p"] == 1.0).all()


def test_a_missing_trial_counts_against_the_experiment():
    exp = PREREGISTERED["E1"]
    rows = [_trial_row("T2", h, 0.5, -5e-5) for h in (10, 21, 42)]
    failed = {**_trial_row("T2", 63, 0.001, -5e-4), "status": "failed"}
    table, groups = ablation.close_experiment(exp, pd.DataFrame(rows + [failed]))
    assert table.loc[(table["step"] == "T2") & (table["horizon"] == 63), "p"].item() == 1.0
    assert groups == {"T1": INCONCLUSIVE, "T2": INCONCLUSIVE}

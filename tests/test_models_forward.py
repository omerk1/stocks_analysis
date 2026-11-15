"""src/models/forward.py: on a test date, forward scoring is the walk-forward
test's own pick list; it also scores rows whose outcome isn't known yet; and
a holdout date waits for the registered test."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.models import dataset, forward, trading
from src.models.ablation import LABEL_COLS, cell_frame, neither_returns, oos_predictions, seed_mean
from src.models.learners import BoostingConfig
from src.models.splits import walk_forward_folds
from src.models.synthetic import PlantedSpec, planted_panel

FAST = BoostingConfig(max_iter=50, min_samples_leaf=50)
SC = trading.Scorecard(horizons=(21,), grid=((2.0, 1.5),), test_years=(2020,), first_train_start="2015-01-02",
                       eras=((2020,),), seeds=(0, 1), config=FAST, rank="ev_atr")


def _frame():
    """The planted panel under the registered model columns (one of them the
    planted x), joined with its labels."""
    panel = planted_panel(PlantedSpec(n_tickers=60, start="2015-01-02", seed=3))
    rng = np.random.default_rng(0)
    features = panel[["ticker", "date"]].copy()
    for c in SC.model_columns:
        features[c] = rng.uniform(size=len(panel)).astype("float32")
    features["sector"] = pd.Categorical(rng.choice(["A", "B"], len(panel)))
    features["slope_log_21_sma_50_rank"] = panel["x"].astype("float32")
    return cell_frame(features, panel[["ticker", "date", *LABEL_COLS]])


def test_on_a_test_date_it_is_the_tests_own_pick_list():
    frame = _frame()
    [cell] = SC.cells(21)
    day = sorted(frame.loc[frame["date"].dt.year == 2020, "date"].unique())[100]
    folds = walk_forward_folds(SC.test_years, SC.first_train_start)
    preds = seed_mean(oos_predictions(frame, SC.model_columns, folds, SC.seeds, SC.config))
    test = trading.picks(preds, frame, cell, neither_returns(frame, folds), SC.verdict_k, rank="ev_atr",
                         neither_atr=trading.neither_atr_returns(frame, folds))
    got = forward.score_cell(SC, frame, cell, pd.Timestamp(day))
    assert len(got) == SC.verdict_k and list(got["rank"]) == list(range(1, SC.verdict_k + 1))
    assert list(got["ticker"]) == list(test.loc[test["date"] == day, "ticker"])
    assert got["score"].is_monotonic_decreasing
    np.testing.assert_allclose(got[["p_up", "p_down", "p_neither"]].sum(axis=1), 1, rtol=1e-6)
    np.testing.assert_allclose(got["target_px"] - got["close_t"], cell.upper_atr * got["atr"], rtol=1e-5)
    np.testing.assert_allclose(got["close_t"] - got["stop_px"], cell.lower_atr * got["atr"], rtol=1e-5)

    # rows with no outcome yet are scored the same: the fit only sees the training years
    unknown = frame.copy()
    later = unknown["date"] >= day
    unknown.loc[later, ["hit", "ret", "label_end_date"]] = np.nan
    pd.testing.assert_frame_equal(forward.score_cell(SC, unknown, cell, pd.Timestamp(day)), got)


def test_only_the_ev_in_atr_rank():
    with pytest.raises(ValueError, match="EV in ATR units"):
        forward.score_cell(replace(SC, rank="ev"), _frame(), SC.cells(21)[0], pd.Timestamp("2020-06-01"))


def test_a_holdout_date_waits_for_the_registered_test(tmp_path, monkeypatch):
    sc = replace(trading.PREREGISTERED["HT1"], horizons=(21,))
    monkeypatch.setattr(dataset, "read_labels", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(forward, "cell_frame", lambda f, labels: f)
    monkeypatch.setattr(forward, "score_cell", lambda sc, frame, cell, as_of, k: pd.DataFrame({"ticker": ["X"]}))
    kwargs = {"trials_path": tmp_path / "TRIALS.csv", "artifacts_root": tmp_path / "art"}
    with pytest.raises(dataset.HoldoutError, match="hasn't run 9 of its cells"):
        forward.score_date(sc, pd.DataFrame(), tmp_path, "2026-08-18", **kwargs)
    for cell in sc.cells(21)[:-1]:
        trading.mark_started(sc, cell, kwargs["artifacts_root"])
    with pytest.raises(dataset.HoldoutError, match="hasn't run 1 of its cells"):
        forward.score_date(sc, pd.DataFrame(), tmp_path, "2026-08-18", **kwargs)
    trading.mark_started(sc, sc.cells(21)[-1], kwargs["artifacts_root"])
    assert len(forward.score_date(sc, pd.DataFrame(), tmp_path, "2026-08-18", **kwargs)) == 9
    with pytest.raises(dataset.HoldoutError):                      # a dev scorecard never scores past 2021
        forward.score_date(SC, pd.DataFrame(), tmp_path, "2022-01-03", **kwargs)


def test_the_command_confirms_a_holdout_date_and_refuses_one_inside_the_window(monkeypatch):
    from src.models import cli
    from src.models.features import cache
    monkeypatch.setattr(cache, "read_feature_cache", lambda *a, **k: pytest.fail("read a cache"))
    with pytest.raises(SystemExit, match="pass --open-holdout"):
        cli.main(["score-forward", "HT1", "--as-of", "2026-08-18"])
    with pytest.raises(SystemExit, match="leave --open-holdout out"):
        cli.main(["score-forward", "HT1", "--as-of", "2021-06-30", "--open-holdout"])
    with pytest.raises(SystemExit, match="no pre-registered scorecard"):
        cli.main(["score-forward", "NOPE", "--as-of", "2021-06-30"])

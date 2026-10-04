import numpy as np
import pandas as pd
import pytest

from src.models import metrics
from src.models.baselines import ConstantModel, StratumModel, make_baseline
from src.models.learners import BoostedModel, BoostingConfig, IsotonicCalibrator, fit_predict, monotonicity_violations
from src.models.splits import walk_forward_folds

FAST = BoostingConfig(max_iter=50, min_samples_leaf=20)


def _panel(start="2011-01-03", end="2016-12-30", names=30, seed=0, horizon=10):
    """Synthetic cell: P(+1) rises with x, P(-1) falls with it; `noise` is unrelated."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, end)
    dates = np.repeat(days, names)
    n = len(dates)
    x = rng.uniform(size=n)
    p_up = 0.15 + 0.6 * x
    p_down = (1 - p_up) * 0.7
    u = rng.uniform(size=n)
    hit = np.where(u < p_up, 1.0, np.where(u < p_up + p_down, -1.0, 0.0))
    end_pos = np.minimum(np.searchsorted(days, dates) + horizon, len(days) - 1)
    return pd.DataFrame({
        "ticker": np.tile([f"T{i:02d}" for i in range(names)], len(days)),
        "date": dates, "x": x, "noise": rng.uniform(size=n),
        "sector": pd.Categorical(rng.choice(["A", "B", "C"], n)),
        "hit": hit, "label_end_date": days[end_pos],
    })


def _brier(preds, y):
    return float(metrics.brier_rows(preds.assign(hit=np.asarray(y))).mean())


def test_constant_model_is_the_training_frequency():
    y = pd.Series([1, 1, -1, 0])
    p = ConstantModel().fit(pd.DataFrame(index=y.index), y).predict_proba(pd.DataFrame(index=range(3)))
    np.testing.assert_allclose(p.iloc[0], [0.5, 0.25, 0.25])
    w = ConstantModel().fit(pd.DataFrame(index=y.index), y, sample_weight=[1, 1, 2, 0]).freqs_
    np.testing.assert_allclose(w, [0.5, 0.5, 0.0])


def test_unresolved_labels_are_refused():
    with pytest.raises(ValueError, match="unresolved"):
        ConstantModel().fit(pd.DataFrame(index=range(2)), [1.0, np.nan])


def test_boosted_model_recovers_a_planted_signal():
    train, test = _panel(end="2012-12-31", seed=1), _panel(end="2011-12-31", seed=2)
    boosted = BoostedModel(["x", "noise", "sector"], FAST).fit(train, train["hit"])
    p = boosted.predict_proba(test)
    assert list(p.columns) == ["p_up", "p_down", "p_neither"]
    np.testing.assert_allclose(p.sum(axis=1), 1.0)
    flat = ConstantModel().fit(train, train["hit"]).predict_proba(test)
    assert _brier(p, test["hit"]) < _brier(flat, test["hit"]) - 0.02
    assert np.corrcoef(test["x"], p["p_up"])[0, 1] > 0.9


def test_seeds_change_a_wide_fit_and_not_a_narrow_one():
    train = _panel(end="2011-12-31")
    rng = np.random.default_rng(9)
    train["n2"], train["n3"] = rng.uniform(size=len(train)), rng.uniform(size=len(train))

    def fit(cols, seed):
        return BoostedModel(cols, FAST, seed=seed).fit(train, train["hit"]).predict_proba(train)

    wide = ["x", "noise", "n2", "n3", "sector"]  # 0.8 x 5 = 4 columns per split: subsampled
    assert not np.allclose(fit(wide, 0), fit(wide, 1))
    narrow = ["x", "noise", "sector"]  # 0.8 x 3 rounds up to all 3: deterministic
    np.testing.assert_array_equal(fit(narrow, 0), fit(narrow, 1))


def test_stratum_model_shrinks_and_falls_back():
    frame = pd.DataFrame({"r": [0.1, 0.2, 0.9, 0.95], "s": pd.Categorical(["A", "A", "A", "B"])})
    y = pd.Series([1, 1, -1, 0])
    m = StratumModel(["r"], ["s"], n_buckets=3, prior_rows=2.0).fit(frame, y)
    overall = np.array([0.5, 0.25, 0.25])
    p = m.predict_proba(pd.DataFrame({"r": [0.15, 0.5, np.nan], "s": pd.Categorical(["A", "A", "A"])}))
    np.testing.assert_allclose(p.iloc[0], (np.array([2, 0, 0]) + 2 * overall) / 4)  # 2 rows, shrunk
    np.testing.assert_allclose(p.iloc[1], overall)  # unseen stratum
    np.testing.assert_allclose(p.iloc[2], overall)  # NaN key


def test_isotonic_calibration_fixes_a_squashed_model():
    test = _panel(end="2012-12-31", seed=3)
    true = pd.DataFrame({"p_up": 0.15 + 0.6 * test["x"]})
    true["p_down"] = (1 - true["p_up"]) * 0.7
    true["p_neither"] = 1 - true["p_up"] - true["p_down"]
    squashed = (true + 1 / 3) / 2  # pulled halfway to uniform: right ranking, wrong scale
    cal = IsotonicCalibrator().fit(squashed, test["hit"])
    fixed = cal.transform(squashed)
    np.testing.assert_allclose(fixed.sum(axis=1), 1.0)
    assert _brier(fixed, test["hit"]) < _brier(squashed, test["hit"])
    assert abs(_brier(fixed, test["hit"]) - _brier(true, test["hit"])) < 0.005


class Recorder:
    """Wraps a model and remembers which rows it was fitted on and asked about."""
    log: list = []

    def __init__(self):
        self.inner = ConstantModel()

    def fit(self, frame, y, sample_weight=None):
        Recorder.log.append(("fit", frame))
        self.inner.fit(frame, y, sample_weight)
        return self

    def predict_proba(self, frame):
        Recorder.log.append(("predict", frame))
        return self.inner.predict_proba(frame)


def test_fit_predict_purges_training_and_calibration_rows():
    panel = _panel()
    panel.loc[panel.index[-40:], "hit"] = np.nan  # unresolved tail
    fold = walk_forward_folds(test_years=(2016,))[0]
    Recorder.log = []
    out = fit_predict(panel, fold, Recorder, calibrate=True, n_inner=2)
    # Returned: every resolved test-year row, labels attached.
    expected = panel[(panel["date"].dt.year == 2016) & panel["hit"].notna()]
    assert len(out) == len(expected) and out["hit"].notna().all()
    assert set(out.columns) == {"ticker", "date", "hit", "p_up", "p_down", "p_neither"}
    *inner, final_fit, final_predict = Recorder.log
    # Nothing fitted or calibrated on reaches the outer test year.
    for kind, frame in [*inner, final_fit]:
        assert (frame["label_end_date"] < fold.test_start).all(), kind
    assert final_predict[1]["date"].dt.year.eq(2016).all()
    # Calibration predictions are the inner test years (2014, 2015), out of sample.
    inner_predicts = [f for kind, f in inner if kind == "predict"]
    assert [f["date"].dt.year.unique().tolist() for f in inner_predicts] == [[2014], [2015]]


def test_fit_predict_with_the_boosted_learner_beats_b0():
    panel = _panel(names=20)
    fold = walk_forward_folds(test_years=(2016,))[0]
    model = fit_predict(panel, fold, lambda: BoostedModel(["x", "sector"], FAST))
    base = fit_predict(panel, fold, ConstantModel)
    assert _brier(model, model["hit"]) < _brier(base, base["hit"]) - 0.02


def test_monotonicity_violations_are_counted():
    keys = {"ticker": ["A", "B", "C"], "date": pd.to_datetime(["2020-01-02"] * 3)}
    preds = {
        1.0: pd.DataFrame({**keys, "p_down": [0.5, 0.4, 0.3]}),
        1.5: pd.DataFrame({**keys, "p_down": [0.4, 0.45, 0.3]}),  # B rises: violation
        2.0: pd.DataFrame({**keys, "p_down": [0.3, 0.3, 0.31]}),  # C rises: violation
    }
    r = monotonicity_violations(preds)
    assert r["n_rows"] == 3 and r["n_violations"] == 2 and r["lowers"] == [1.0, 1.5, 2.0]


def test_baselines_by_name():
    assert isinstance(make_baseline("B0"), ConstantModel)
    assert make_baseline("B4").columns == ["mom_12_1_rank", "realized_vol_63_rank", "sector", "mom_1_0_rank",
                                           "dist_pct_sma_50_rank"]
    assert isinstance(make_baseline("B2_stratum"), StratumModel)
    with pytest.raises(ValueError):
        make_baseline("B5")

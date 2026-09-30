import numpy as np
import pandas as pd
import pytest

from src.models import splits
from src.models.labels.barriers import BarrierCell, barrier_labels


def _frame(horizons=(5, 21, 63), seed=0):
    """Rows on every business day 2011-2021, each with a label window of a
    random horizon (in business days), like barrier labels."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2011-01-03", "2021-12-31")
    h = rng.choice(horizons, size=len(dates))
    ends = [d + pd.offsets.BDay(int(k)) for d, k in zip(dates, h)]
    ends = [e if e <= dates[-1] else pd.NaT for e in ends]
    return pd.DataFrame({"date": dates, "label_end_date": ends})


def test_v1_folds_are_yearly_2014_to_2021():
    expanding = splits.walk_forward_folds()
    sliding = splits.walk_forward_folds(scheme=splits.SLIDING)
    assert [f.test_start.year for f in expanding] == list(range(2014, 2022))
    assert all(f.train_start == pd.Timestamp("2011-01-01") for f in expanding)
    assert sliding[-1].train_start == pd.Timestamp("2018-01-01")
    assert sliding[0].train_start == pd.Timestamp("2011-01-01")  # clipped at the first training date


def test_purge_drops_training_rows_whose_label_reaches_the_test_year():
    frame = pd.DataFrame({
        "date": pd.to_datetime(["2013-11-01", "2013-12-20", "2014-03-03"]),
        "label_end_date": pd.to_datetime(["2013-12-02", "2014-01-15", "2014-04-01"]),
    })
    fold = splits.walk_forward_folds(test_years=(2014,))[0]

    train, test = splits.fold_masks(frame, fold)

    assert list(train) == [True, False, False]
    assert list(test) == [False, False, True]


@pytest.mark.parametrize("scheme", [splits.EXPANDING, splits.SLIDING])
def test_no_training_label_window_ever_touches_its_test_fold(scheme):
    frame = _frame()
    folds = splits.walk_forward_folds(scheme=scheme)
    folds += [inner for outer in folds for inner in splits.inner_folds(outer, scheme=scheme)]
    for fold in folds:
        train, test = splits.fold_masks(frame, fold, embargo_days=21)
        tr = frame[train]
        assert not (train & test).any(), fold.name
        overlap = (tr["date"] <= fold.test_end) & (tr["label_end_date"] >= fold.test_start)
        assert not overlap.any(), fold.name
        te = frame[test]
        assert te["date"].between(fold.test_start, fold.test_end).all(), fold.name


def test_embargo_drops_training_rows_just_after_the_test_period():
    frame = _frame(horizons=(1,))
    # A fold whose training window straddles the test year, as an inner scheme might.
    fold = splits.Fold("straddle", pd.Timestamp("2014-01-01"), pd.Timestamp("2016-12-31"),
                       pd.Timestamp("2015-01-01"), pd.Timestamp("2015-12-31"))

    train, _ = splits.fold_masks(frame, fold, embargo_days=5)

    after = frame[train & (frame["date"] > fold.test_end).to_numpy()]["date"]
    assert after.min() == pd.bdate_range("2016-01-01", periods=6)[5]


def test_unlabelled_rows_are_in_neither_mask():
    frame = pd.DataFrame({"date": pd.to_datetime(["2013-05-01", "2014-05-01"]), "label_end_date": [pd.NaT, pd.NaT]})
    train, test = splits.fold_masks(frame, splits.walk_forward_folds(test_years=(2014,))[0])
    assert not train.any() and not test.any()


def test_inner_folds_sit_inside_the_outer_training_window():
    outer = splits.walk_forward_folds(test_years=(2018,))[0]
    inner = splits.inner_folds(outer, n_inner=2)
    assert [f.test_start.year for f in inner] == [2016, 2017]
    assert all(f.train_start >= outer.train_start and f.test_end <= outer.train_end for f in inner)


def test_invalid_scheme_and_empty_training_window_raise():
    with pytest.raises(ValueError, match="scheme"):
        splits.walk_forward_folds(scheme="random")
    with pytest.raises(ValueError, match="no training window"):
        splits.walk_forward_folds(test_years=(2011,))


def test_folds_apply_directly_to_barrier_label_output():
    days = pd.bdate_range("2012-01-02", "2015-12-31")
    rng = np.random.default_rng(1)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
    bars = pd.DataFrame({"ticker": "AAA", "date": days, "open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close})
    labels = barrier_labels(bars, [BarrierCell(21, 2.0, 1.0)])
    fold = splits.walk_forward_folds(test_years=(2015,), first_train_start="2012-01-01")[0]

    train, test = splits.fold_masks(labels, fold)

    assert train.sum() > 0 and test.sum() > 0
    assert (labels.loc[train, "label_end_date"] < fold.test_start).all()

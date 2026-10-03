import numpy as np
import pandas as pd
import pytest

from src.models import inference, metrics
from src.models.labels.barriers import BarrierCell
from src.signals.moving_averages.stats.inference import InsufficientBlocksError

H = 5  # block length 10


def _pair(n_dates=120, names=30, seed=0):
    """A model whose P(+1) is the true probability, and a uniform baseline, on the same rows."""
    rng = np.random.default_rng(seed)
    dates = np.repeat(pd.bdate_range("2014-01-01", periods=n_dates), names)
    n = len(dates)
    p_up = rng.uniform(0.1, 0.7, n)
    p_down = (1 - p_up) * 0.6
    u = rng.uniform(size=n)
    hit = np.where(u < p_up, 1, np.where(u < p_up + p_down, -1, 0)).astype(float)
    keys = {"date": dates, "ticker": [f"T{i % names:03d}" for i in range(n)], "hit": hit}
    model = pd.DataFrame({**keys, "p_up": p_up, "p_down": p_down, "p_neither": 1 - p_up - p_down})
    base = pd.DataFrame({**keys, "p_up": 1 / 3, "p_down": 1 / 3, "p_neither": 1 / 3})
    return model, base


def test_identical_models_differ_by_exactly_zero():
    model, _ = _pair()
    r = inference.paired_loss_diff(model, model.copy(), H)
    assert r.point_estimate == 0 and r.ci_low == 0 and r.ci_high == 0
    assert len(r.draws) == inference.N_BOOT and r.block_length == 2 * H


def test_planted_improvement_is_recovered_and_point_matches_pooled_metric():
    model, base = _pair()
    r = inference.paired_loss_diff(model, base, H, loss="brier")
    cell = BarrierCell(H, 2.0, 1.0)
    pooled = (metrics.cell_metrics(model.assign(ret=0.0, atr=1.0, close_t=100.0), cell, 0.0, by=None)["brier"]
              - metrics.cell_metrics(base.assign(ret=0.0, atr=1.0, close_t=100.0), cell, 0.0, by=None)["brier"])
    assert r.point_estimate == pytest.approx(float(pooled.iloc[0]))
    assert r.ci_high < 0 and r.near_edge == r.ci_high  # lower loss is better: the near edge is the high one
    assert r.n_dates == 120 and r.n_rows == 120 * 30
    ll = inference.paired_loss_diff(model, base, H, loss="log_loss")
    assert ll.ci_high < 0


def test_draws_are_reproducible_from_the_seed():
    model, base = _pair()
    a = inference.paired_loss_diff(model, base, H, seed=7)
    b = inference.paired_loss_diff(model, base, H, seed=7)
    c = inference.paired_loss_diff(model, base, H, seed=8)
    np.testing.assert_array_equal(a.draws, b.draws)
    assert not np.array_equal(a.draws, c.draws)


def test_too_few_dates_raise():
    model, base = _pair(n_dates=29)
    with pytest.raises(InsufficientBlocksError):
        inference.paired_loss_diff(model, base, H)


def test_rows_and_labels_must_match():
    model, base = _pair()
    with pytest.raises(ValueError, match="same"):
        inference.paired_loss_diff(model, base.iloc[1:], H)
    flipped = base.copy()
    flipped.loc[0, "hit"] = -flipped.loc[0, "hit"] if flipped.loc[0, "hit"] else 1.0
    with pytest.raises(ValueError, match="labels"):
        inference.paired_loss_diff(model, flipped, H)


def test_per_date_diff_is_date_weighted():
    dates = pd.bdate_range("2014-01-01", periods=100)
    rng = np.random.default_rng(0)
    base = pd.Series(rng.normal(0, 0.01, 100), index=dates)
    r = inference.per_date_diff(base + 0.002, base, H)
    assert r.point_estimate == pytest.approx(0.002)
    assert r.ci_low == pytest.approx(0.002) and r.near_edge == r.ci_low
    with pytest.raises(ValueError):
        inference.per_date_diff(base.iloc[1:], base, H)


def test_archive_round_trip(tmp_path):
    model, base = _pair()
    r = inference.paired_loss_diff(model, base, H)
    path = inference.archive_draws(r, tmp_path / "trial", "brier_vs_b0")
    back = inference.load_draws(path)
    np.testing.assert_array_equal(back.draws, r.draws)
    assert back.summary() == r.summary()

"""Tests for M16's kernel-space diagnostics (`stats/kernel_space.py`).
Validates the empirical impulse-response machinery against known-exact
closed forms before trusting it for constructions with no closed form
(`slope_log_k`) -- same discipline M8's `impulse_center_of_mass` used for
HMA/DEMA.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.distance import dist_pct
from src.signals.moving_averages.features.ma import compute_ma
from src.signals.moving_averages.features.slope import slope_log_k
from src.signals.moving_averages.stats import kernel_space as ks


def test_sma_distance_matches_its_own_exact_triangular_closed_form():
    """`(close_t - SMA_n(t)) = (1/n) * sum_{j=0}^{n-2} (n-1-j) * r_{t-j}`
    in raw price units (derived directly from the SMA's own definition via
    telescoping) -- a linearly-decaying ("triangular") weight on the return
    from `j` bars back, zero beyond `j = n-2`. Tested on `dist_pct` itself
    (the fractional form, `(close-ma)/ma`), not raw price distance: to
    first order in the impulse's own fractional size `epsilon`, dividing by
    `ma` (~100, the synthetic base price, to O(epsilon)) just rescales the
    raw formula by the same base price the impulse itself is expressed
    relative to, so the *fractional* weight collapses back to the same
    dimensionless `(n-1-j)/n` -- this only holds in the small-epsilon limit
    `impulse_response`'s own docstring names, not exactly, which is why
    `epsilon` defaults small. Checked at several `j` values directly, not
    just centroid, since a centroid match alone wouldn't rule out a
    differently-shaped kernel with the same mean lag.
    """
    n = 20

    def feature(close: pd.Series) -> pd.Series:
        return dist_pct(close, compute_ma(close, "sma", n))

    weights = ks.impulse_response(feature, max_lag=n + 5)
    expected = np.array([(n - 1 - j) / n if j <= n - 2 else 0.0 for j in range(n + 5)])
    np.testing.assert_allclose(weights, expected, atol=1e-4)


def test_mom_12_1_is_a_boxcar_over_its_own_known_window():
    """`mom_12_1 = close[t-21]/close[t-252] - 1` -- a return over the window
    strictly between 21 and 252 bars back, zero outside it. Checked
    qualitatively (well inside vs. well outside the window) rather than at
    the exact fencepost, since the ratio construction (not a plain sum)
    makes the boundary a modeling convention, not load-bearing for this
    diagnostic's own centroid/dispersion/clustering use.
    """
    from src.signals.moving_averages.features.context import mom_12_1

    weights = ks.impulse_response(mom_12_1, max_lag=300)
    assert abs(weights[100] - 1.0) < 0.05  # well inside (21, 252)
    assert abs(weights[5]) < 0.05  # well before the window opens
    assert abs(weights[280]) < 0.05  # well past the window's far edge


def test_slope_log_k_has_a_nonzero_short_lag_response():
    """No independent closed form exists for `slope_log_k` (it's a
    log-of-an-average difference, not a plain linear combination) -- this
    is exactly the case the empirical impulse-response method exists for.
    Sanity-checked only: the response should be nonzero and concentrated
    at short lags (a slope reacts to recent price action), not that it
    matches a hand-derived formula.
    """

    def feature(close: pd.Series) -> pd.Series:
        ma = compute_ma(close, "sma", 50)
        return slope_log_k(ma, 21)

    weights = ks.impulse_response(feature, max_lag=150)
    valid = ~np.isnan(weights)
    assert valid.any()
    assert np.abs(weights[valid]).sum() > 0
    centroid = ks.kernel_centroid(weights)
    assert 0 < centroid < 100  # concentrated well inside the lookback+slope-k window


def test_kernel_centroid_and_dispersion_on_a_single_spike():
    weights = np.zeros(50)
    weights[10] = 1.0
    assert ks.kernel_centroid(weights) == 10.0
    assert ks.kernel_dispersion(weights) == 0.0


def test_kernel_centroid_on_a_uniform_box():
    n = 21
    weights = np.zeros(50)
    weights[:n] = 1.0
    assert abs(ks.kernel_centroid(weights) - (n - 1) / 2) < 1e-9


def test_cosine_similarity_identical_vectors_is_one():
    a = np.array([1.0, 2.0, 3.0, 0.0])
    assert abs(ks.cosine_similarity(a, a) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal_vectors_is_zero():
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 0.0])
    assert abs(ks.cosine_similarity(a, b)) < 1e-9


def test_cosine_similarity_handles_nan_as_zero():
    a = np.array([1.0, np.nan, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    assert abs(ks.cosine_similarity(a, b) - 1.0) < 1e-9


def test_cluster_by_threshold_groups_near_identical_vectors():
    vectors = {
        "a": np.array([1.0, 0.9, 0.1]),
        "b": np.array([1.0, 0.9, 0.1]) * 2,  # same direction, different magnitude -> cos sim 1.0
        "c": np.array([0.0, 0.0, 1.0]),  # orthogonal to a/b
    }
    sim = ks.similarity_matrix(vectors)
    clusters = ks.cluster_by_threshold(sim, threshold=0.95)
    assert clusters["a"] == clusters["b"]
    assert clusters["c"] != clusters["a"]


def test_impulse_response_degenerate_when_feature_needs_more_history_than_available():
    def feature(close: pd.Series) -> pd.Series:
        return compute_ma(close, "sma", 5000)  # far longer than impulse_at itself

    weights = ks.impulse_response(feature, n=1600, impulse_at=800, max_lag=50)
    assert np.isnan(weights).all() or np.allclose(weights, 0.0)

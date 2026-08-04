import math

import pytest

from src.sr_lines.candidates import generate_diagonal_candidates, generate_horizontal_candidates
from src.sr_lines.config import SRConfig
from src.sr_lines.models import Pivot, PivotKind


def _pivot(price: float, atr_pct: float, timestamp: str) -> Pivot:
    return Pivot(
        kind=PivotKind.LOW, timestamp=timestamp, price=price,
        confirmed_at=timestamp, atr_at_pivot=price * atr_pct,
    )


def _diag_pivot(price: float, bar_index: int, atr_pct: float, kind: PivotKind = PivotKind.HIGH) -> Pivot:
    return Pivot(
        kind=kind, timestamp=f"2020-{1 + bar_index // 28:02d}-{1 + bar_index % 28:02d}",
        price=price, confirmed_at="irrelevant-for-diagonal-fitting",
        atr_at_pivot=price * atr_pct, bar_index=bar_index,
    )


def test_clustering_is_scale_invariant_across_price_levels():
    # Same relative gap (3%) and same ATR% (2%) at two very different price
    # levels should cluster the same way -- this is the whole point of
    # thresholding on ATR% of price rather than raw dollar ATR (which would
    # give a $1.50 threshold at price 50 but a $9 threshold at price 300,
    # not a consistent relative tolerance).
    config = SRConfig(zone_width_atr=1.0, min_pivots_per_cluster=2)

    low_price_pivots = [
        _pivot(50.0, 0.02, "2020-01-01"),
        _pivot(51.5, 0.02, "2020-02-01"),  # 3% above 50
    ]
    high_price_pivots = [
        _pivot(300.0, 0.02, "2024-01-01"),
        _pivot(309.0, 0.02, "2024-02-01"),  # 3% above 300
    ]

    low_candidates = generate_horizontal_candidates(low_price_pivots, config)
    high_candidates = generate_horizontal_candidates(high_price_pivots, config)

    # threshold = zone_width_atr * atr_pct * price = 1.0 * 0.02 * price = 2%
    # of price -- a 3% gap exceeds that at *both* price levels, so neither
    # should merge into a single 2-pivot cluster.
    assert len(low_candidates) == 0  # gap too wide relative to width -> no cluster of 2
    assert len(high_candidates) == 0

    # Tighten the gap to 1% (under the 2% threshold) at both price levels --
    # now both should cluster, consistently.
    low_tight = [_pivot(50.0, 0.02, "2020-01-01"), _pivot(50.5, 0.02, "2020-02-01")]
    high_tight = [_pivot(300.0, 0.02, "2024-01-01"), _pivot(303.0, 0.02, "2024-02-01")]

    assert len(generate_horizontal_candidates(low_tight, config)) == 1
    assert len(generate_horizontal_candidates(high_tight, config)) == 1


def test_half_width_scales_with_price_not_just_raw_atr():
    config = SRConfig(zone_width_atr=1.0, min_pivots_per_cluster=2)

    low_price = [_pivot(50.0, 0.02, "2020-01-01"), _pivot(50.3, 0.02, "2020-02-01")]
    high_price = [_pivot(300.0, 0.02, "2024-01-01"), _pivot(301.8, 0.02, "2024-02-01")]

    low_cand = generate_horizontal_candidates(low_price, config)[0]
    high_cand = generate_horizontal_candidates(high_price, config)[0]

    # Same 2% ATR at both levels -> half_width should scale roughly with
    # price (proportionally ~6x wider at 6x the price), not stay flat.
    ratio = high_cand.half_width / low_cand.half_width
    assert 5.0 < ratio < 7.0


def test_diagonal_disabled_by_default_returns_empty():
    config = SRConfig()  # diagonal_enabled defaults to False
    pivots = [_diag_pivot(100.0 * math.exp(0.001 * bi), bi, 0.02) for bi in (0, 25, 50, 75, 100)]

    assert generate_diagonal_candidates(pivots, config) == []


def test_diagonal_fits_a_clean_uptrend_and_collects_all_its_pivots_as_inliers():
    config = SRConfig(diagonal_enabled=True, zone_width_atr=1.0)
    bar_indices = (0, 25, 50, 75, 100)
    slope = 0.001
    # Every point lies exactly on the line -> every seed pair among them
    # should find all 5 as inliers, and the dedup pass should collapse the
    # resulting duplicate seed-pair fits down to one final candidate.
    pivots = [_diag_pivot(100.0 * math.exp(slope * bi), bi, 0.02) for bi in bar_indices]

    candidates = generate_diagonal_candidates(pivots, config)

    assert len(candidates) == 1
    cand = candidates[0]
    assert len(cand.pivots) == 5
    assert cand.slope == pytest.approx(slope, abs=1e-6)


def test_diagonal_half_width_is_price_level_invariant_in_log_space():
    # Same 2% ATR at two very different price levels should give the exact
    # same log-space half_width -- log-space bands don't need a separate
    # price-scaling correction the way horizontal's dollar half_width did;
    # the real-dollar width naturally scales when converted back via exp()
    # at whatever price level the trend currently sits at (see events.py).
    config = SRConfig(diagonal_enabled=True, zone_width_atr=1.0)
    bar_indices = (0, 25, 50, 75, 100)
    slope = 0.001

    low_pivots = [_diag_pivot(50.0 * math.exp(slope * bi), bi, 0.02) for bi in bar_indices]
    high_pivots = [_diag_pivot(300.0 * math.exp(slope * bi), bi, 0.02) for bi in bar_indices]

    low_cand = generate_diagonal_candidates(low_pivots, config)[0]
    high_cand = generate_diagonal_candidates(high_pivots, config)[0]

    assert low_cand.half_width == pytest.approx(high_cand.half_width, rel=0.01)


def test_diagonal_rejects_seed_pairs_exceeding_the_slope_cap():
    config = SRConfig(diagonal_enabled=True, max_diagonal_slope_atr_per_bar=0.01, diagonal_min_inliers=2)
    # log-slope ~0.0277/bar between every pair -- well above the 0.01 cap.
    pivots = [_diag_pivot(100.0, 0, 0.02), _diag_pivot(200.0, 25, 0.02), _diag_pivot(400.0, 50, 0.02)]

    assert generate_diagonal_candidates(pivots, config) == []


def test_diagonal_requires_minimum_pivot_separation():
    config = SRConfig(diagonal_enabled=True, diagonal_min_pivot_separation_bars=20, diagonal_min_inliers=2)
    # Only 10 bars apart -- under the 20-bar minimum separation.
    pivots = [_diag_pivot(100.0, 0, 0.02), _diag_pivot(101.0, 10, 0.02)]

    assert generate_diagonal_candidates(pivots, config) == []


def test_diagonal_does_not_mix_high_and_low_pivots():
    config = SRConfig(diagonal_enabled=True, diagonal_min_inliers=2)
    highs = [_diag_pivot(110.0, 0, 0.02, kind=PivotKind.HIGH), _diag_pivot(111.0, 25, 0.02, kind=PivotKind.HIGH)]
    lows = [_diag_pivot(90.0, 5, 0.02, kind=PivotKind.LOW), _diag_pivot(91.0, 30, 0.02, kind=PivotKind.LOW)]

    candidates = generate_diagonal_candidates(highs + lows, config)

    # Two separate 2-pivot fits (one per kind), not one mixed 4-pivot fit.
    assert len(candidates) == 2
    for cand in candidates:
        kinds = {p.kind for p in cand.pivots}
        assert len(kinds) == 1

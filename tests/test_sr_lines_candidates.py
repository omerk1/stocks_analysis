import math

import pytest

from src.sr_lines.candidates import (
    DiagonalCandidate,
    _dedupe_diagonal_candidates,
    generate_diagonal_candidates,
    generate_horizontal_candidates,
)
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
    # A perfect fit -- every inlier sits exactly on the line -- should have
    # ~zero fit-quality penalty.
    assert cand.fit_rms_atr_pct == pytest.approx(0.0, abs=1e-6)


def test_diagonal_fit_rms_is_higher_for_a_looser_scattered_fit():
    config = SRConfig(diagonal_enabled=True, zone_width_atr=1.0)
    bar_indices = (0, 25, 50, 75, 100)
    slope = 0.001

    tight_pivots = [_diag_pivot(100.0 * math.exp(slope * bi), bi, 0.02) for bi in bar_indices]
    # Same trend, but each point nudged by a random-ish offset within the
    # inlier tolerance (zone_width_atr * atr_pct = 1.0 * 0.02 = 2% here) --
    # still all inliers, just scattered instead of sitting exactly on the line.
    offsets = [1.0, -1.006, 1.006, -1.0, 0.5]
    scattered_pivots = [
        _diag_pivot(100.0 * math.exp(slope * bi) * (1 + 0.019 * off), bi, 0.02)
        for bi, off in zip(bar_indices, offsets)
    ]

    tight_cand = generate_diagonal_candidates(tight_pivots, config)[0]
    scattered_cand = generate_diagonal_candidates(scattered_pivots, config)[0]

    assert scattered_cand.fit_rms_atr_pct > tight_cand.fit_rms_atr_pct
    assert scattered_cand.fit_rms_atr_pct > 0.05  # meaningfully loose, not just float noise


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


def test_diagonal_rejects_a_candidate_whose_drift_never_exceeds_its_own_half_width():
    # Regression: a diagonal fit whose price barely moves across its own
    # claimed lifetime is functionally a horizontal zone wearing a slope --
    # confirmed on real GEVO data, where several kept diagonals had slopes
    # of -0.000002 to -0.000005/bar (drift/half_width ratio 0.16-0.95) sitting
    # in the identical price band as several of that same run's own kept
    # horizontal lines, rendering the same level twice (horizontal and
    # diagonal candidates are never deduped against each other).
    config = SRConfig(diagonal_enabled=True, zone_width_atr=1.0, diagonal_min_inliers=3)
    bar_indices = (0, 50, 100)
    slope = 0.00005  # drift over 100 bars = 0.005; half_width = 0.01 -> ratio 0.5, below the 1.0 floor
    pivots = [_diag_pivot(100.0 * math.exp(slope * bi), bi, 0.02) for bi in bar_indices]

    assert generate_diagonal_candidates(pivots, config) == []


def test_diagonal_keeps_a_candidate_whose_drift_clears_its_own_half_width():
    config = SRConfig(diagonal_enabled=True, zone_width_atr=1.0, diagonal_min_inliers=3)
    bar_indices = (0, 50, 100)
    slope = 0.001  # drift over 100 bars = 0.1; half_width = 0.01 -> ratio 10, comfortably above the floor
    pivots = [_diag_pivot(100.0 * math.exp(slope * bi), bi, 0.02) for bi in bar_indices]

    candidates = generate_diagonal_candidates(pivots, config)
    assert len(candidates) == 1


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


def _bare_diag_candidate(
    slope: float, bar_indices: list[int], intercept: float = math.log(100.0), half_width: float = 0.02,
    fit_rms_atr_pct: float = 0.0,
) -> DiagonalCandidate:
    pivots = [_diag_pivot(100.0, bi, 0.02) for bi in bar_indices]
    return DiagonalCandidate(slope=slope, intercept=intercept, origin_index=bar_indices[0],
                              half_width=half_width, pivots=pivots, fit_rms_atr_pct=fit_rms_atr_pct)


def test_dedup_does_not_drop_a_candidate_with_a_different_slope_even_if_prices_happen_to_cross():
    # Regression: a real AAPL run had a short, visually obvious 3-pivot
    # descending trendline discarded because it shared 2 of its 3 pivots
    # with several longer, unrelated *ascending* candidates that had more
    # inliers (sorted first) -- pivot overlap alone isn't proof of
    # duplication; a single pivot can legitimately sit on two geometrically
    # unrelated lines. Anchored so their prices are close at bar 100 (where
    # they'd have shared a pivot under the old pivot-overlap check) -- the
    # slope difference alone must still be enough to keep both.
    long_ascending = _bare_diag_candidate(slope=0.001, bar_indices=[0, 50, 100, 150])
    short_descending = _bare_diag_candidate(
        slope=-0.01, bar_indices=[100, 150, 200], intercept=long_ascending.log_price_at(100),
    )
    config = SRConfig(diagonal_enabled=True, max_diagonal_slope_atr_per_bar=0.05)

    kept = _dedupe_diagonal_candidates([long_ascending, short_descending], 200, config)

    assert len(kept) == 2


def test_dedup_drops_a_geometrically_close_candidate_with_a_similar_slope():
    # A real T run showed this: many diagonal candidates fit from entirely
    # disjoint pivot subsets (so the old pivot-overlap check never even
    # looked at them) but tracking nearly the same price band with a
    # similar slope -- 8+ "different" ascending lines all within a few % of
    # each other, cluttering the chart. Anchored close together at bar 100.
    long_line = _bare_diag_candidate(slope=0.001, bar_indices=[0, 50, 100, 150])
    near_duplicate = _bare_diag_candidate(
        slope=0.0011, bar_indices=[300, 350, 400], intercept=long_line.log_price_at(300) + 0.005,
    )
    config = SRConfig(diagonal_enabled=True, max_diagonal_slope_atr_per_bar=0.05, dedup_overlap_threshold=0.6)

    kept = _dedupe_diagonal_candidates([long_line, near_duplicate], 400, config)

    assert len(kept) == 1
    assert kept[0] is long_line  # more pivots -> sorted/kept first


def test_dedup_keeps_parallel_lines_that_are_offset_far_apart_in_price():
    # Same slope, but genuinely different price levels (e.g. the top and
    # bottom of a channel) -- must not be merged just because they're
    # roughly parallel.
    upper = _bare_diag_candidate(slope=0.001, bar_indices=[0, 50, 100, 150])
    lower = _bare_diag_candidate(
        slope=0.001, bar_indices=[0, 50, 100], intercept=upper.log_price_at(0) - 0.5,  # ~40% lower
    )
    config = SRConfig(diagonal_enabled=True, dedup_overlap_threshold=0.6)

    kept = _dedupe_diagonal_candidates([upper, lower], 150, config)

    assert len(kept) == 2


def test_cap_truncates_by_fit_quality_not_by_processing_order():
    # Regression: an earlier version applied `diagonal_max_candidates` mid-
    # loop (stopping as soon as `len(kept)` hit the cap), with candidates
    # processed in pivot-count-descending order -- a genuinely non-duplicate
    # short, tightly-fit candidate simply never got a turn once the cap
    # filled with longer, higher-touch-count (but worse-fit) lines ahead of
    # it. Confirmed on real GEVO data: a real 3-pivot ~7-month ascending
    # trendline was generated correctly but discarded this way, 300 raw
    # candidates deep into a run that had 1,144 raw same-kind fits.
    #
    # Three genuinely distinct candidates (very different slopes/positions,
    # so none collide under `_candidates_are_duplicate`): two long,
    # high-touch-count but loosely-fit lines, and one short, low-touch-count
    # but tightly-fit line. With a cap of 2, the tightest-fit one -- not the
    # two with the most pivots -- must survive.
    loose_long_a = _bare_diag_candidate(
        slope=0.001, bar_indices=[0, 30, 60, 90, 120], fit_rms_atr_pct=0.9,
    )
    loose_long_b = _bare_diag_candidate(
        slope=-0.001, bar_indices=[200, 230, 260, 290], intercept=math.log(300.0), fit_rms_atr_pct=0.8,
    )
    tight_short = _bare_diag_candidate(
        slope=0.02, bar_indices=[500, 520, 540], intercept=math.log(700.0), fit_rms_atr_pct=0.05,
    )
    config = SRConfig(diagonal_enabled=True, diagonal_max_candidates=2)

    kept = _dedupe_diagonal_candidates([loose_long_a, loose_long_b, tight_short], 540, config)

    assert len(kept) == 2
    assert tight_short in kept
    assert loose_long_a not in kept  # worst fit -- dropped in favor of the tight short line

from src.sr_lines.candidates import generate_horizontal_candidates
from src.sr_lines.config import SRConfig
from src.sr_lines.models import Pivot, PivotKind


def _pivot(price: float, atr_pct: float, timestamp: str) -> Pivot:
    return Pivot(
        kind=PivotKind.LOW, timestamp=timestamp, price=price,
        confirmed_at=timestamp, atr_at_pivot=price * atr_pct,
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

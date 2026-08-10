import pandas as pd

from src.market_common.models import PivotKind
from src.market_common.pivots import detect_pivots


def _series(values: list[float], start: str = "2020-01-01") -> pd.Series:
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx)


def test_two_series_reproduces_known_zigzag_pattern():
    # A clean plateau-swing-plateau-swing series in true high/low: down to
    # a low, up to a high, down to a low, with a final (unconfirmed, since
    # nothing reverses away from it before the series ends) rise -- flat
    # threshold 10.0 ignores the ~1-2 unit noise within each plateau and
    # only confirms the ~20+ unit real swings. Verified by direct run
    # before writing these assertions, not hand-simulated.
    highs = _series([10, 10, 10, 30, 30, 30, 5, 5, 5, 25, 25, 25])
    lows = _series([9, 9, 9, 28, 28, 28, 3, 3, 3, 23, 23, 23])

    pivots = detect_pivots(highs, lows, threshold_fn=lambda i: 10.0)

    kinds = [p.kind for p in pivots]
    assert kinds == [PivotKind.LOW, PivotKind.HIGH, PivotKind.LOW]
    assert [p.value for p in pivots] == [9.0, 30.0, 3.0]
    assert [p.bar_index for p in pivots] == [0, 3, 6]


def test_single_series_defaults_lows_to_highs():
    # An RSI-like series with one clean swing; lows=None should behave
    # identically to passing the same series twice.
    rsi_like = _series([50, 55, 60, 75, 65, 55, 45, 35, 30, 40, 55, 70])

    via_default = detect_pivots(rsi_like, threshold_fn=lambda i: 10.0)
    via_explicit = detect_pivots(rsi_like, rsi_like, threshold_fn=lambda i: 10.0)

    assert len(via_default) == len(via_explicit) > 0
    for a, b in zip(via_default, via_explicit):
        assert a.value == b.value
        assert a.kind == b.kind
        assert a.bar_index == b.bar_index


def test_magnitude_fn_defaults_to_threshold_fn():
    highs = _series([10, 11, 20, 12, 8, 16])
    pivots = detect_pivots(highs, threshold_fn=lambda i: 3.0)
    assert pivots
    assert pivots[0].threshold_at_pivot == 3.0


def test_magnitude_fn_can_differ_from_threshold_fn():
    # Regression: sr_lines confirms reversals at pivot_atr_mult * ATR but
    # needs threshold_at_pivot to store *raw* ATR (a separately-configured
    # multiplier is applied to it again downstream, for a different
    # purpose) -- confirming the two are genuinely decoupled, not just
    # defaulting to the same thing by coincidence.
    highs = _series([10, 11, 20, 12, 8, 16])
    raw_atr = 2.0
    mult = 3.0

    pivots = detect_pivots(
        highs, threshold_fn=lambda i: mult * raw_atr, magnitude_fn=lambda i: raw_atr,
    )

    assert pivots
    assert pivots[0].threshold_at_pivot == raw_atr  # not mult * raw_atr


def test_nan_threshold_never_confirms_a_reversal():
    highs = _series([10, 11, 20, 12, 8, 16])
    pivots = detect_pivots(highs, threshold_fn=lambda i: float("nan"))
    assert pivots == []


def test_fewer_than_two_points_returns_empty():
    highs = _series([10])
    assert detect_pivots(highs, threshold_fn=lambda i: 1.0) == []


def test_confirmed_at_is_the_bar_where_reversal_actually_completed():
    highs = _series([10, 11, 20, 18, 16, 12])
    lows = _series([9, 10, 19, 17, 15, 11])

    pivots = detect_pivots(highs, lows, threshold_fn=lambda i: 5.0)

    assert pivots
    high_pivot = pivots[0]
    assert high_pivot.timestamp != high_pivot.confirmed_at
    assert pd.Timestamp(high_pivot.confirmed_at) > pd.Timestamp(high_pivot.timestamp)

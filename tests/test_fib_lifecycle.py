import pandas as pd

from src.fibonacci.config import FibConfig
from src.fibonacci.lifecycle import evaluate_level_touches
from src.fibonacci.models import FibLevel, FibLevelKind, FibSwing, SwingDirection


def _bars(rows: list[tuple]) -> pd.DataFrame:
    """rows: list of (date_str, high, low, close)"""
    df = pd.DataFrame(rows, columns=["timestamp", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp").sort_index()


def _swing(end_date: str) -> FibSwing:
    return FibSwing(
        origin_date="2020-01-01", origin_price=100.0, end_date=end_date, end_price=150.0,
        direction=SwingDirection.UP, scale_mult=2.0, magnitude_atr=10.0, duration_bars=10,
        confirmed_at=end_date,
    )


def _level(price: float = 120.0) -> FibLevel:
    return FibLevel(id="lvl", ratio=0.618, kind=FibLevelKind.RETRACEMENT, price=price)


def test_touch_counted_when_range_enters_band_and_close_stays_on_established_side():
    # level=120, tolerance=0.3*atr=0.3*2=0.6 -> zone=[119.7,120.3].
    # Established side: bar 1 closes well above -> "above". Bar 2's range
    # dips into the zone but the close stays above zone_hi.
    dates = pd.date_range("2020-02-01", periods=4, freq="D")
    rows = [
        (dates[0], 125.0, 124.0, 124.5),   # establishes "above"
        (dates[1], 124.0, 119.9, 123.0),   # low dips into zone, close stays above
        (dates[2], 124.0, 123.0, 123.5),
        (dates[3], 124.0, 123.0, 123.5),
    ]
    bars = _bars(rows)
    atr = pd.Series(2.0, index=bars.index)
    swing = _swing(end_date="2020-01-31")
    config = FibConfig()
    level = _level(price=120.0)

    evaluate_level_touches([level], bars, atr, swing, config)

    assert level.n_touches == 1
    assert level.n_violations == 0
    assert level.first_touch_date == dates[1].isoformat()
    assert level.last_touch_date == dates[1].isoformat()
    assert level.respected is True


def test_violation_counted_when_close_crosses_and_is_never_reclaimed():
    dates = pd.date_range("2020-02-01", periods=5, freq="D")
    rows = [
        (dates[0], 125.0, 124.0, 124.5),  # establishes "above"
        (dates[1], 120.0, 118.0, 118.5),  # closes below zone_lo -> pending violation
        (dates[2], 118.5, 117.0, 117.5),  # stays below
        (dates[3], 117.5, 116.0, 116.5),
        (dates[4], 116.5, 115.0, 115.5),  # reclaim window (2 bars) elapsed
    ]
    bars = _bars(rows)
    atr = pd.Series(2.0, index=bars.index)
    swing = _swing(end_date="2020-01-31")
    config = FibConfig(level_violation_reclaim_bars=2)
    level = _level(price=120.0)

    evaluate_level_touches([level], bars, atr, swing, config)

    assert level.n_violations == 1
    assert level.n_touches == 0
    assert level.respected is False


def test_reclaimed_cross_counts_as_a_touch_not_a_violation():
    dates = pd.date_range("2020-02-01", periods=3, freq="D")
    rows = [
        (dates[0], 125.0, 124.0, 124.5),  # establishes "above"
        (dates[1], 120.0, 118.0, 118.5),  # closes below zone_lo -> pending
        (dates[2], 124.0, 119.0, 123.0),  # reclaims (closes back above zone_hi)
    ]
    bars = _bars(rows)
    atr = pd.Series(2.0, index=bars.index)
    swing = _swing(end_date="2020-01-31")
    config = FibConfig(level_violation_reclaim_bars=5)
    level = _level(price=120.0)

    evaluate_level_touches([level], bars, atr, swing, config)

    assert level.n_touches == 1
    assert level.n_violations == 0
    assert level.first_touch_date == dates[1].isoformat()
    assert level.respected is True


def test_never_tested_level_is_not_respected():
    dates = pd.date_range("2020-02-01", periods=3, freq="D")
    rows = [
        (dates[0], 200.0, 199.0, 199.5),
        (dates[1], 200.0, 199.0, 199.5),
        (dates[2], 200.0, 199.0, 199.5),
    ]
    bars = _bars(rows)
    atr = pd.Series(2.0, index=bars.index)
    swing = _swing(end_date="2020-01-31")
    config = FibConfig()
    level = _level(price=120.0)

    evaluate_level_touches([level], bars, atr, swing, config)

    assert level.n_touches == 0
    assert level.n_violations == 0
    assert level.respected is False
    assert level.avg_reaction_atr is None


def test_no_bars_after_swing_end_leaves_levels_at_defaults():
    bars = _bars([("2020-01-01", 101.0, 99.0, 100.0)])
    atr = pd.Series(2.0, index=bars.index)
    swing = _swing(end_date="2020-06-01")  # well after the only available bar
    config = FibConfig()
    level = _level(price=120.0)

    result = evaluate_level_touches([level], bars, atr, swing, config)

    assert result[0].n_touches == 0
    assert result[0].respected is False

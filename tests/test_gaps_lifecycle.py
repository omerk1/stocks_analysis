import pandas as pd
import pytest

from src.gaps.config import GapConfig
from src.gaps.lifecycle import apply_lifecycle
from src.gaps.models import Direction, Gap, GapKind, GapStatus, Timeframe


def _flat_bars(n: int, start: str = "2020-01-01", price: float = 100.0, volume: float = 1000.0) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"open": price, "high": price + 0.1, "low": price - 0.1, "close": price, "volume": volume},
        index=idx,
    )


def _extend(bars: pd.DataFrame, rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    """rows: list of (open, high, low, close, volume)."""
    idx = pd.bdate_range(bars.index[-1] + pd.Timedelta(days=1), periods=len(rows))
    extra = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    return pd.concat([bars, extra])


def _bullish_gap(created_at: str, zone_bottom: float = 100.0, zone_top: float = 105.0) -> Gap:
    return Gap(
        id="g1", ticker="TEST", timeframe=Timeframe.DAILY, kind=GapKind.CLASSIC,
        direction=Direction.BULLISH, created_at=created_at, zone_top=zone_top, zone_bottom=zone_bottom,
        size_atr=1.0,
    )


def test_n_approaches_counts_distinct_reentries_not_just_the_running_max():
    # zone=[100,105]. Touches (wick/low dips into the zone) at bars 2 and 7,
    # receding fully out of the zone for 4 bars in between (more than
    # _APPROACH_MERGE_GAP_BARS=3, so these stay genuinely separate) --
    # two separate approaches, never fully filling (max_fill_pct stays at
    # 40, from bar 7).
    bars = _flat_bars(20)
    bars = _extend(bars, [
        (106.0, 107.0, 106.0, 106.0, 1000.0),  # bar1: low=106, not touching
        (104.0, 105.0, 104.0, 104.0, 1000.0),  # bar2: low=104, touching (pct=20) -- approach 1
        (106.0, 107.0, 106.0, 106.0, 1000.0),  # bar3: recedes
        (107.0, 108.0, 107.0, 107.0, 1000.0),  # bar4: still out
        (107.0, 108.0, 107.0, 107.0, 1000.0),  # bar5: still out
        (107.0, 108.0, 107.0, 107.0, 1000.0),  # bar6: still out (4-bar gap now)
        (103.0, 104.0, 103.0, 103.0, 1000.0),  # bar7: low=103, touching (pct=40) -- approach 2
        (106.0, 107.0, 106.0, 106.0, 1000.0),  # bar8: recedes
    ])
    gap = _bullish_gap(created_at=bars.index[19].isoformat())
    config = GapConfig(atr_period=5, warmup_bars=0)

    apply_lifecycle(bars, [gap], config)

    assert gap.n_approaches == 2
    assert gap.max_fill_pct == pytest.approx(40.0)
    assert gap.status == GapStatus.PARTIAL


def test_a_brief_recede_and_return_does_not_inflate_n_approaches():
    # Regression: zone=[100,105]. Touch, recede for exactly 1 bar, touch
    # again -- this must count as ONE continuous approach, not two, the
    # same class of fix avwap.lifecycle's n_crosses needed for bare
    # boundary-flip noise.
    bars = _flat_bars(20)
    bars = _extend(bars, [
        (104.0, 105.0, 104.0, 104.0, 1000.0),  # bar1: touching
        (106.0, 107.0, 106.0, 106.0, 1000.0),  # bar2: recedes for exactly 1 bar
        (103.0, 104.0, 103.0, 103.0, 1000.0),  # bar3: touching again
    ])
    gap = _bullish_gap(created_at=bars.index[19].isoformat())
    config = GapConfig(atr_period=5, warmup_bars=0)

    apply_lifecycle(bars, [gap], config)

    assert gap.n_approaches == 1


def test_n_approaches_does_not_count_activity_after_the_gap_has_closed():
    # Regression: once the gap fully closes, later, unrelated revisits to
    # the same price level (which can happen years later in real data)
    # must not keep inflating n_approaches -- it should reflect the gap's
    # own active lifetime, not the rest of history.
    bars = _flat_bars(20)
    bars = _extend(bars, [
        (99.0, 100.0, 99.0, 99.0, 1000.0),      # bar1: low=99 <= zone_bottom=100 -> fully closed here
        (110.0, 111.0, 109.0, 110.0, 1000.0),   # bar2: far away, irrelevant
        (110.0, 111.0, 109.0, 110.0, 1000.0),   # bar3
        (110.0, 111.0, 109.0, 110.0, 1000.0),   # bar4
        (110.0, 111.0, 109.0, 110.0, 1000.0),   # bar5
        (104.0, 105.0, 104.0, 104.0, 1000.0),   # bar6: price wanders back through the zone, long after closing
        (110.0, 111.0, 109.0, 110.0, 1000.0),   # bar7
    ])
    gap = _bullish_gap(created_at=bars.index[19].isoformat())
    config = GapConfig(atr_period=5, warmup_bars=0)

    apply_lifecycle(bars, [gap], config)

    assert gap.status == GapStatus.CLOSED
    # Only the closing bar itself counts -- bar6's later revisit (well
    # after closed_date) must not add a second approach.
    assert gap.n_approaches == 1


def test_volume_ratio_at_creation_uses_the_rolling_20_bar_average():
    bars = _flat_bars(25)  # 25 bars of volume=1000, enough for a real rolling(20) window
    bars = _extend(bars, [(106.0, 107.0, 106.0, 106.0, 3000.0)])
    gap = _bullish_gap(created_at=bars.index[-1].isoformat())
    config = GapConfig(atr_period=5, warmup_bars=0)

    apply_lifecycle(bars, [gap], config)

    expected_avg = (19 * 1000.0 + 3000.0) / 20  # rolling(20) includes the creation bar itself
    assert gap.volume_ratio_at_creation == pytest.approx(3000.0 / expected_avg)


def test_reaction_atr_measures_favorable_move_back_in_the_original_direction_after_close():
    # Bullish gap fully closes (price falls all the way through zone_bottom),
    # then reverses back up -- reaction_atr_after_close should capture that
    # recovery, anchored at the close of the bar where it first fully closed.
    # created_at is the last flat bar (index 19); everything below is walked.
    bars = _flat_bars(20)
    bars = _extend(bars, [
        (106.0, 107.0, 106.0, 106.0, 1000.0),  # walked bar1: low=106, not touching
        (99.0, 100.0, 99.0, 99.0, 1000.0),     # walked bar2: low=99 <= zone_bottom=100 -> fully closed here
        (100.0, 101.0, 99.5, 100.5, 1000.0),   # walked bar3: modest bounce, high=101
        (104.0, 106.0, 103.0, 105.5, 1000.0),  # walked bar4: bigger bounce, high=106
    ])
    gap = _bullish_gap(created_at=bars.index[19].isoformat())
    config = GapConfig(atr_period=5, warmup_bars=0, reaction_window_bars=10)

    apply_lifecycle(bars, [gap], config)

    assert gap.status == GapStatus.CLOSED
    assert gap.closed_date == bars.index[21].isoformat()  # the "low=99" bar
    assert gap.reaction_atr_after_close is not None
    assert gap.bars_to_reaction_peak == 2  # the "high=106" bar is 2 bars after closed_date


def test_reaction_is_not_computed_when_the_gap_never_fully_closes():
    bars = _flat_bars(20)
    bars = _extend(bars, [
        (106.0, 107.0, 106.0, 106.0, 1000.0),
        (104.0, 105.0, 104.0, 104.0, 1000.0),  # only partial fill, never closes
    ])
    gap = _bullish_gap(created_at=bars.index[19].isoformat())
    config = GapConfig(atr_period=5, warmup_bars=0)

    apply_lifecycle(bars, [gap], config)

    assert gap.status != GapStatus.CLOSED
    assert gap.reaction_atr_after_close is None
    assert gap.bars_to_reaction_peak is None

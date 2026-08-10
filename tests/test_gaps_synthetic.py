import copy

import pandas as pd
import pytest

from src.gaps.config import GapConfig
from src.gaps.detect import detect_gaps
from src.gaps.lifecycle import apply_lifecycle
from src.gaps.models import Direction, GapKind, GapStatus, Timeframe


def _flat_bars(n: int, start: str = "2020-01-01", price: float = 100.0, half_range: float = 1.0) -> pd.DataFrame:
    """A perfectly flat, gap-free background series -- long enough (n=20 by
    default) to fully warm up a short-period ATR before any test's actual
    event bars, and flat enough that no classic/FVG condition ever fires on
    it by accident."""
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"open": price, "high": price + half_range, "low": price - half_range, "close": price, "volume": 1000.0},
        index=idx,
    )


def _extend(bars: pd.DataFrame, rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    """rows: list of (open, high, low, close, volume), appended as the next
    business days after `bars`' last date."""
    idx = pd.bdate_range(bars.index[-1] + pd.Timedelta(days=1), periods=len(rows))
    extra = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    return pd.concat([bars, extra])


def _config(**overrides) -> GapConfig:
    defaults = dict(atr_period=5, warmup_bars=0, min_gap_atr=0.3)
    defaults.update(overrides)
    return GapConfig(**defaults)


# ---------------------------------------------------------------------------
# M1: detection (tests 1, 5, 6, 7)
# ---------------------------------------------------------------------------

def test_bullish_classic_gap_never_revisited():
    bars = _flat_bars(20)
    # prev bar (index 19) high=101; gap bar low=110 -> zone [101, 110]
    bars = _extend(bars, [
        (110.0, 111.0, 110.0, 110.0, 1000.0),
        (112.0, 113.0, 111.0, 112.0, 1000.0),
        (113.0, 114.0, 112.0, 113.0, 1000.0),
    ])
    config = _config()

    gaps = detect_gaps(bars, "TEST", Timeframe.DAILY, config)
    classics = [g for g in gaps if g.kind == GapKind.CLASSIC]
    assert len(classics) == 1
    gap = classics[0]
    assert gap.direction == Direction.BULLISH
    assert gap.zone_bottom == pytest.approx(101.0)
    assert gap.zone_top == pytest.approx(110.0)

    apply_lifecycle(bars, [gap], config)
    assert gap.status == GapStatus.OPEN
    assert gap.max_fill_pct == pytest.approx(0.0)
    assert gap.first_touch_date is None
    assert gap.soft_closed_date is None
    assert gap.closed_date is None


def test_fvg_without_classic_gap_on_overlapping_bars():
    bars = _flat_bars(20)
    # t-2 (index 20): high=101 (background-like)
    # t-1 (index 21): displacement candle
    # t   (index 22): low=105 <= high[t-1]=115 (no classic gap), but
    #                 high[t-2]=101 < low[t]=105 (FVG condition holds)
    bars = _extend(bars, [
        (100.0, 101.0, 99.0, 100.0, 1000.0),
        (100.0, 115.0, 100.0, 114.0, 1000.0),
        (114.0, 116.0, 105.0, 115.0, 1000.0),
    ])
    config = _config()

    gaps = detect_gaps(bars, "TEST", Timeframe.DAILY, config)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.kind == GapKind.FVG
    assert gap.direction == Direction.BULLISH
    assert gap.zone_bottom == pytest.approx(101.0)
    assert gap.zone_top == pytest.approx(105.0)
    assert gap.related_id is None


def test_same_bar_classic_and_fvg_linked_by_related_id():
    bars = _flat_bars(20)
    bars = _extend(bars, [(110.0, 111.0, 110.0, 110.0, 1000.0)])
    config = _config()

    gaps = detect_gaps(bars, "TEST", Timeframe.DAILY, config)

    classics = [g for g in gaps if g.kind == GapKind.CLASSIC]
    fvgs = [g for g in gaps if g.kind == GapKind.FVG]
    assert len(classics) == 1
    assert len(fvgs) == 1
    assert classics[0].related_id is None
    assert fvgs[0].related_id == classics[0].id


def test_gap_smaller_than_min_gap_atr_is_discarded():
    bars = _flat_bars(20)
    # true range on background bars is 2.0 (high=101, low=99) so ATR ~2.0;
    # gap height 0.5 -> size_atr 0.25, below a raised min_gap_atr=2.0 floor.
    bars = _extend(bars, [(101.5, 102.0, 101.5, 101.5, 1000.0)])
    config = _config(min_gap_atr=2.0)

    gaps = detect_gaps(bars, "TEST", Timeframe.DAILY, config)

    assert gaps == []


# ---------------------------------------------------------------------------
# M2: lifecycle (tests 2, 3, 4, 8, 9)
# ---------------------------------------------------------------------------

def _bullish_gap_bars(after_rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    bars = _flat_bars(20)
    bars = _extend(bars, [(110.0, 111.0, 110.0, 110.0, 1000.0)])  # zone [101, 110]
    if after_rows:
        bars = _extend(bars, after_rows)
    return bars


def test_wick_40pct_fill_is_partial_with_first_touch_date():
    # open edge 110, far edge 101, height 9 -> 40% penetration at price 106.4
    bars = _bullish_gap_bars([(112.0, 113.0, 106.4, 111.0, 1000.0)])
    config = _config(fill_by="wick")

    gap = detect_gaps(bars, "TEST", Timeframe.DAILY, config)[0]
    apply_lifecycle(bars, [gap], config)

    assert gap.status == GapStatus.PARTIAL
    assert gap.max_fill_pct == pytest.approx(40.0, abs=1e-6)
    assert gap.first_touch_date is not None


def test_wick_only_fill_is_open_under_body_close_mode():
    bars = _bullish_gap_bars([(112.0, 113.0, 106.4, 111.0, 1000.0)])
    config = _config(fill_by="body_close")

    gap = detect_gaps(bars, "TEST", Timeframe.DAILY, config)[0]
    apply_lifecycle(bars, [gap], config)

    assert gap.status == GapStatus.OPEN
    assert gap.max_fill_pct == pytest.approx(0.0)
    assert gap.first_touch_date is None


def test_85pct_fill_then_retreat_is_soft_closed():
    # 85% penetration at price 102.35, then price retreats to 108
    bars = _bullish_gap_bars([
        (109.0, 109.5, 102.35, 103.0, 1000.0),
        (103.0, 109.0, 103.0, 108.0, 1000.0),
    ])
    config = _config()

    gap = detect_gaps(bars, "TEST", Timeframe.DAILY, config)[0]
    apply_lifecycle(bars, [gap], config)

    assert gap.status == GapStatus.SOFT_CLOSED
    assert gap.max_fill_pct == pytest.approx(85.0, abs=1e-6)
    assert gap.soft_closed_date is not None


def test_full_traversal_closes_and_later_reentry_leaves_it_unchanged():
    bars = _bullish_gap_bars([
        (105.0, 105.0, 100.0, 101.0, 1000.0),  # full traversal -> CLOSED
        (150.0, 151.0, 149.0, 150.0, 1000.0),  # big rebound, irrelevant
        (100.0, 100.5, 95.0, 96.0, 1000.0),   # re-entry, deeper than before
    ])
    config = _config()

    gap = detect_gaps(bars, "TEST", Timeframe.DAILY, config)[0]
    apply_lifecycle(bars, [gap], config)

    assert gap.status == GapStatus.CLOSED
    assert gap.max_fill_pct == pytest.approx(100.0)
    first_closed_date = gap.closed_date
    assert first_closed_date is not None

    # Re-running the walk against the very same (full) bars is idempotent --
    # the terminal CLOSED state and its date must not move.
    apply_lifecycle(bars, [gap], config)
    assert gap.closed_date == first_closed_date
    assert gap.status == GapStatus.CLOSED


def test_as_of_before_fill_reports_open():
    full_bars = _bullish_gap_bars([
        (112.0, 113.0, 112.0, 112.0, 1000.0),  # no penetration yet
        (105.0, 105.0, 100.0, 101.0, 1000.0),  # full close, but after as_of
    ])
    as_of_ts = full_bars.index[-2]  # the "no penetration yet" bar
    truncated = full_bars.loc[:as_of_ts]
    config = _config()

    gap = detect_gaps(truncated, "TEST", Timeframe.DAILY, config)[0]
    apply_lifecycle(truncated, [gap], config)
    assert gap.status == GapStatus.OPEN
    assert gap.max_fill_pct == pytest.approx(0.0)
    assert gap.closed_date is None

    # Sanity check the truncation actually mattered -- the full series
    # really does close this same gap once the later bar is included.
    full_gap = copy.deepcopy(gap)
    apply_lifecycle(full_bars, [full_gap], config)
    assert full_gap.status == GapStatus.CLOSED


def test_gap_created_on_final_bar_is_open_with_no_error():
    bars = _bullish_gap_bars([])
    config = _config()

    gap = detect_gaps(bars, "TEST", Timeframe.DAILY, config)[0]
    apply_lifecycle(bars, [gap], config)

    assert gap.status == GapStatus.OPEN
    assert gap.max_fill_pct == pytest.approx(0.0)
    assert gap.first_touch_date is None

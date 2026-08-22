import numpy as np
import pandas as pd
import pytest

from src.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.patterns.config import PatternConfig
from src.patterns.detectors.cup_and_handle import CupAndHandleDetector
from src.patterns.models import PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, volume_sma_period=5, prior_trend_min_bars=5, breakout_buffer_pct=0.001,
        failed_breakout_reclaim_bars=5, expire_lifespan_mult=2.0,
    )
    defaults.update(overrides)
    return PatternConfig(**defaults)


# Prior uptrend (0-24, 80->140, steep enough that the last 15 bars alone
# clear the 30% prior-trend requirement) -> left rim @24=140 -> an exact
# parabola down to 100 and back to 140 over bars 24-64 (right rim @64=140)
# -> a small handle pullback to 130 over bars 65-68. Every test appends
# its own tail after bar 68 (or, for the roundedness-rejection test,
# swaps the cup segment itself for a non-parabolic shape).
def _cup_df(tail_closes: np.ndarray, start: str = "2020-01-01") -> pd.DataFrame:
    uptrend = np.linspace(80.0, 140.0, 25)
    t = np.arange(41, dtype=float)
    cup = (0.1 * (t - 20) ** 2 + 100.0)[1:]
    handle = np.linspace(138.0, 130.0, 4)
    closes = np.concatenate([uptrend, cup, handle, tail_closes])
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes + 0.3, "low": closes - 0.3, "close": closes, "volume": 1000.0}, index=idx,
    )


def _inverse_cup_df(tail_closes: np.ndarray, start: str = "2020-01-01") -> pd.DataFrame:
    downtrend = np.linspace(260.0, 140.0, 25)
    t = np.arange(41, dtype=float)
    cup = (-0.1 * (t - 20) ** 2 + 180.0)[1:]
    handle = np.linspace(142.0, 150.0, 4)
    closes = np.concatenate([downtrend, cup, handle, tail_closes])
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes + 0.3, "low": closes - 0.3, "close": closes, "volume": 1000.0}, index=idx,
    )


def _pivot(bar_index: int, price: float, kind: PivotKind, df: pd.DataFrame) -> Pivot:
    ts = df.index[bar_index].isoformat()
    return Pivot(kind=kind, timestamp=ts, value=price, confirmed_at=ts, threshold_at_pivot=1.0, bar_index=bar_index)


def _cup_pivots(df):
    return [
        _pivot(24, 140.0, PivotKind.HIGH, df),
        _pivot(44, 100.0, PivotKind.LOW, df),
        _pivot(64, 140.0, PivotKind.HIGH, df),
        _pivot(68, 130.0, PivotKind.LOW, df),
    ]


def _inverse_cup_pivots(df):
    return [
        _pivot(24, 140.0, PivotKind.LOW, df),
        _pivot(44, 180.0, PivotKind.HIGH, df),
        _pivot(64, 140.0, PivotKind.LOW, df),
        _pivot(68, 150.0, PivotKind.HIGH, df),
    ]


def test_cup_and_handle_confirmed_breakout_hits_target():
    df = _cup_df(np.linspace(132.0, 200.0, 20))
    df.loc[df.index[72], "volume"] = 1600.0
    pivots = _cup_pivots(df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.CUP_AND_HANDLE
    assert m.direction == Direction.BULLISH
    assert m.key_levels == {
        "left_rim": 140.0, "cup_extreme": 100.0, "right_rim": 140.0, "handle": 130.0, "neckline": 140.0,
    }
    assert m.target_price == pytest.approx(180.0)
    assert m.stop_price == pytest.approx(100.0)
    assert m.breakout_bar == 72
    assert m.volume_confirmed is True
    assert m.status == PatternStatus.HIT_TARGET
    assert 0.0 < m.confidence <= 1.0
    assert len(m.notes) == 5


def test_inverse_cup_and_handle_mirrors_cup_and_handle():
    df = _inverse_cup_df(np.linspace(148.0, 80.0, 20))
    pivots = _inverse_cup_pivots(df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.INVERSE_CUP_AND_HANDLE
    assert m.direction == Direction.BEARISH
    assert m.target_price == pytest.approx(100.0)
    assert m.stop_price == pytest.approx(180.0)
    assert m.breakout_bar == 72
    assert m.status == PatternStatus.HIT_TARGET


def test_rim_symmetry_gate_rejects_weak_recovery():
    # Right rim recovering only to 120 -- 120 < 140*(1-0.05)=133.
    df = _cup_df(np.linspace(132.0, 200.0, 20))
    pivots = _cup_pivots(df)
    pivots[2] = _pivot(64, 120.0, PivotKind.HIGH, df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_depth_hard_gate_rejects_too_shallow_for_configured_floor():
    # The fixture's real depth is ~28.6% -- raising the hard floor above
    # that rejects it as too shallow.
    df = _cup_df(np.linspace(132.0, 200.0, 20))
    pivots = _cup_pivots(df)
    config = _config(cup_depth_hard_min_pct=50.0)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_depth_hard_gate_rejects_too_deep_for_configured_ceiling():
    df = _cup_df(np.linspace(132.0, 200.0, 20))
    pivots = _cup_pivots(df)
    config = _config(cup_depth_hard_max_pct=20.0)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_handle_below_cup_midpoint_rejects_candidate():
    # midpoint=(140+100)/2=120; a handle at 110 sits in the lower half.
    df = _cup_df(np.linspace(132.0, 200.0, 20))
    pivots = _cup_pivots(df)
    pivots[3] = _pivot(68, 110.0, PivotKind.LOW, df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_handle_retrace_gate_rejects_when_configured_tighter_than_actual():
    # The fixture's real handle retrace is 25% of the cup's advance.
    df = _cup_df(np.linspace(132.0, 200.0, 20))
    pivots = _cup_pivots(df)
    config = _config(cup_handle_max_retrace_pct=10.0)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_weak_prior_trend_rejects_candidate():
    # The fixture's real prior-trend move is ~37% -- raising the
    # requirement above that rejects it.
    df = _cup_df(np.linspace(132.0, 200.0, 20))
    pivots = _cup_pivots(df)
    config = _config(cup_prior_trend_min_pct=50.0)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_non_parabolic_price_path_rejects_on_roundedness():
    # Same rim/handle geometry, but the cup itself is a single-bar spike
    # (flat at 140, one bar plunging to 100, immediately back) instead of
    # a smooth curve -- fails the R² floor even though every other gate
    # (rim symmetry, depth, handle position, prior trend) would pass.
    uptrend = np.linspace(80.0, 140.0, 25)
    spike = np.full(41, 140.0)
    spike[20] = 100.0
    handle = np.linspace(138.0, 130.0, 4)
    closes = np.concatenate([uptrend, spike[1:], handle, np.full(3, 133.0)])
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    df = pd.DataFrame(
        {"open": closes, "high": closes + 0.3, "low": closes - 0.3, "close": closes, "volume": 1000.0}, index=idx,
    )
    pivots = _cup_pivots(df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_new_low_below_cup_bottom_invalidates():
    df = _cup_df(np.linspace(128.0, 90.0, 5))
    pivots = _cup_pivots(df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.INVALIDATED
    assert matches[0].breakout_bar is None


def test_failed_breakout_reclaim_within_window_flags_failed_breakout():
    tail = np.concatenate([[141.0], np.full(4, 135.0)])
    df = _cup_df(tail)
    pivots = _cup_pivots(df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.breakout_bar == 69
    assert m.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT


def test_expired_when_no_breakout_within_deadline():
    df = _cup_df(np.full(90, 135.0))
    pivots = _cup_pivots(df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.EXPIRED
    assert matches[0].breakout_bar is None


def test_pending_when_not_enough_bars_yet_to_resolve():
    df = _cup_df(np.full(3, 133.0))
    pivots = _cup_pivots(df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.PENDING
    assert matches[0].breakout_bar is None

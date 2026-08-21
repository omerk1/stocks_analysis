import uuid

import numpy as np
import pandas as pd
import pytest

from src.market_common.models import Direction, Timeframe
from src.patterns.config import PatternConfig
from src.patterns.lifecycle import apply_lifecycle_bidirectional
from src.patterns.models import PatternMatch, PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(breakout_buffer_pct=0.001, failed_breakout_reclaim_bars=3, expire_lifespan_mult=2.0)
    defaults.update(overrides)
    return PatternConfig(**defaults)


def _bars(closes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes, "high": [c + 0.3 for c in closes], "low": [c - 0.3 for c in closes],
            "close": closes, "volume": [1000.0] * len(closes),
        },
        index=idx,
    )


def _match(direction: Direction = Direction.NEUTRAL) -> PatternMatch:
    return PatternMatch(
        id=str(uuid.uuid4()), ticker="TST", timeframe=Timeframe.DAILY,
        pattern_type=PatternType.SYMMETRIC_TRIANGLE, direction=direction,
        pivots=[], formation_start="2020-01-01", formation_end="2020-01-01",
    )


def test_bidirectional_resolves_bullish_on_upside_break():
    # Flat boundaries at 110 (upper) / 90 (lower); price sits inside, then
    # breaks up through 110.
    closes = [100.0] * 5 + [115.0] * 5
    df = _bars(closes)
    match = _match()
    config = _config()

    apply_lifecycle_bidirectional(
        df, match,
        formation_end_bar_index=4, formation_bars=4,
        upper_trigger_at=lambda i: 110.0, lower_trigger_at=lambda i: 90.0,
        upper_target=130.0, lower_target=70.0, upper_stop=90.0, lower_stop=110.0,
        pre_breakout_invalidated_at=lambda i: False,
        volume=df["volume"], volume_sma_series=df["volume"], config=config,
    )

    assert match.direction == Direction.BULLISH
    assert match.target_price == pytest.approx(130.0)
    assert match.stop_price == pytest.approx(90.0)
    assert match.breakout_bar == 5


def test_bidirectional_resolves_bearish_on_downside_break():
    closes = [100.0] * 5 + [85.0] * 5
    df = _bars(closes)
    match = _match()
    config = _config()

    apply_lifecycle_bidirectional(
        df, match,
        formation_end_bar_index=4, formation_bars=4,
        upper_trigger_at=lambda i: 110.0, lower_trigger_at=lambda i: 90.0,
        upper_target=130.0, lower_target=70.0, upper_stop=90.0, lower_stop=110.0,
        pre_breakout_invalidated_at=lambda i: False,
        volume=df["volume"], volume_sma_series=df["volume"], config=config,
    )

    assert match.direction == Direction.BEARISH
    assert match.target_price == pytest.approx(70.0)
    assert match.stop_price == pytest.approx(110.0)
    assert match.breakout_bar == 5


def test_bidirectional_keeps_bias_direction_while_pending():
    closes = [100.0] * 8  # never crosses either boundary
    df = _bars(closes)
    match = _match(direction=Direction.NEUTRAL)
    config = _config()

    apply_lifecycle_bidirectional(
        df, match,
        formation_end_bar_index=4, formation_bars=4,
        upper_trigger_at=lambda i: 110.0, lower_trigger_at=lambda i: 90.0,
        upper_target=130.0, lower_target=70.0, upper_stop=90.0, lower_stop=110.0,
        pre_breakout_invalidated_at=lambda i: False,
        volume=df["volume"], volume_sma_series=df["volume"], config=config,
    )

    assert match.status == PatternStatus.PENDING
    assert match.direction == Direction.NEUTRAL  # untouched -- no breakout happened
    assert match.target_price is None
    assert match.stop_price is None


def test_bidirectional_respects_pending_deadline_override():
    closes = [100.0] * 20  # would stay PENDING forever without a deadline
    df = _bars(closes)
    match = _match()
    config = _config()

    apply_lifecycle_bidirectional(
        df, match,
        formation_end_bar_index=4, formation_bars=4,
        upper_trigger_at=lambda i: 110.0, lower_trigger_at=lambda i: 90.0,
        upper_target=130.0, lower_target=70.0, upper_stop=90.0, lower_stop=110.0,
        pre_breakout_invalidated_at=lambda i: False,
        volume=df["volume"], volume_sma_series=df["volume"], config=config,
        pending_deadline_bar_index=6,
    )

    assert match.status == PatternStatus.EXPIRED
    assert match.breakout_bar is None


def test_bidirectional_pre_breakout_invalidation():
    closes = [100.0] * 8
    df = _bars(closes)
    match = _match()
    config = _config()

    apply_lifecycle_bidirectional(
        df, match,
        formation_end_bar_index=4, formation_bars=4,
        upper_trigger_at=lambda i: 110.0, lower_trigger_at=lambda i: 90.0,
        upper_target=130.0, lower_target=70.0, upper_stop=90.0, lower_stop=110.0,
        pre_breakout_invalidated_at=lambda i: i == 5,
        volume=df["volume"], volume_sma_series=df["volume"], config=config,
    )

    assert match.status == PatternStatus.INVALIDATED
    assert match.breakout_bar is None


def test_bidirectional_failed_breakout_reclaim():
    # Breaks up at bar 5, then closes back below the (still-live) upper
    # trigger within failed_breakout_reclaim_bars.
    closes = [100.0] * 5 + [115.0] + [95.0] * 4
    df = _bars(closes)
    match = _match()
    config = _config(failed_breakout_reclaim_bars=3)

    apply_lifecycle_bidirectional(
        df, match,
        formation_end_bar_index=4, formation_bars=4,
        upper_trigger_at=lambda i: 110.0, lower_trigger_at=lambda i: 90.0,
        upper_target=130.0, lower_target=70.0, upper_stop=90.0, lower_stop=110.0,
        pre_breakout_invalidated_at=lambda i: False,
        volume=df["volume"], volume_sma_series=df["volume"], config=config,
    )

    assert match.breakout_bar == 5
    assert match.direction == Direction.BULLISH
    assert match.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT

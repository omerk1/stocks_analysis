import uuid

import numpy as np
import pandas as pd
import pytest

from src.market_common.models import Direction, Timeframe
from src.patterns.config import PatternConfig
from src.patterns.lifecycle import apply_lifecycle, apply_lifecycle_bidirectional, resolution_horizon_bars
from src.patterns.models import PatternMatch, PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(breakout_buffer_pct=0.001, expire_lifespan_mult=2.0)
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
    # Breaks up at bar 5, closes back below the (still-live) upper trigger,
    # and never reaches target before the resolution horizon elapses. Needs
    # enough bars to actually run the horizon out -- a reclaim alone no
    # longer resolves the match, so a short frame would leave it ACTIVE
    # (right-censored) rather than failed.
    closes = [100.0] * 5 + [115.0] + [95.0] * 30
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

    assert match.breakout_bar == 5
    assert match.direction == Direction.BULLISH
    assert match.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT


def _flat_trigger(level: float):
    return lambda _i: level


def _apply(df, match, *, formation_end_bar_index, formation_bars, trigger, config):
    return apply_lifecycle(
        df, match, formation_end_bar_index=formation_end_bar_index, formation_bars=formation_bars,
        trigger_at=_flat_trigger(trigger), pre_breakout_invalidated_at=lambda _i: False,
        volume=df["volume"], volume_sma_series=df["volume"], config=config,
    )


def test_target_reached_after_the_resolution_horizon_is_not_a_hit():
    # The bug this fixes: the walk ran to the end of available history, so a
    # target reached ~2 years after breakout still scored HIT_TARGET, which
    # is not comparable to the weeks-to-months literature benchmarks §7.3
    # measures against.
    config = _config(target_horizon_mult=2.0, target_horizon_min_bars=5, target_horizon_max_bars=252)
    closes = [100.0] * 5 + [120.0] + [120.0] * 40 + [500.0] * 5
    df = _bars(closes)
    match = _match(Direction.BULLISH)
    match.target_price = 400.0
    _apply(df, match, formation_end_bar_index=4, formation_bars=4, trigger=110.0, config=config)
    assert match.status is PatternStatus.EXPIRED_UNRESOLVED


def test_target_reached_inside_the_resolution_horizon_still_hits():
    config = _config(target_horizon_mult=2.0, target_horizon_min_bars=5, target_horizon_max_bars=252)
    closes = [100.0] * 5 + [120.0] + [400.0] * 10
    df = _bars(closes)
    match = _match(Direction.BULLISH)
    match.target_price = 300.0
    _apply(df, match, formation_end_bar_index=4, formation_bars=4, trigger=110.0, config=config)
    assert match.status is PatternStatus.HIT_TARGET


def test_still_open_inside_the_horizon_stays_active_not_unresolved():
    # Right-censored: the horizon hasn't elapsed in the data we have, which
    # is a different fact from "ran its full horizon and resolved to
    # nothing" and must not be collapsed into it.
    config = _config(target_horizon_mult=2.0, target_horizon_min_bars=50, target_horizon_max_bars=252)
    closes = [100.0] * 5 + [120.0] + [121.0] * 5
    df = _bars(closes)
    match = _match(Direction.BULLISH)
    match.target_price = 400.0
    _apply(df, match, formation_end_bar_index=4, formation_bars=4, trigger=110.0, config=config)
    assert match.status is PatternStatus.ACTIVE


def test_resolution_horizon_is_clamped_at_both_ends():
    config = _config(target_horizon_mult=2.0, target_horizon_min_bars=20, target_horizon_max_bars=252)
    assert resolution_horizon_bars(1, config) == 20        # floor: a days-long flag
    assert resolution_horizon_bars(60, config) == 120      # 2x its own formation
    assert resolution_horizon_bars(5000, config) == 252    # cap: one trading year


def test_reclaim_then_target_is_a_hit_not_a_failed_breakout():
    # The whole point of not terminating on reclaim: this is a throwback,
    # which Bulkowski counts as a working pattern. Under the old fixed
    # reclaim window the early close back through the trigger resolved it
    # INVALIDATED_FAILED_BREAKOUT immediately and the target was never seen.
    config = _config(target_horizon_mult=2.0, target_horizon_min_bars=20, target_horizon_max_bars=252)
    closes = [100.0] * 5 + [120.0] + [105.0] * 3 + [400.0] * 30
    df = _bars(closes)
    match = _match(Direction.BULLISH)
    match.target_price = 300.0
    _apply(df, match, formation_end_bar_index=4, formation_bars=4, trigger=110.0, config=config)
    assert match.status is PatternStatus.HIT_TARGET


def test_reclaim_without_target_inside_the_horizon_is_a_failed_breakout():
    config = _config(target_horizon_mult=2.0, target_horizon_min_bars=20, target_horizon_max_bars=252)
    closes = [100.0] * 5 + [120.0] + [105.0] * 40
    df = _bars(closes)
    match = _match(Direction.BULLISH)
    match.target_price = 300.0
    _apply(df, match, formation_end_bar_index=4, formation_bars=4, trigger=110.0, config=config)
    assert match.status is PatternStatus.INVALIDATED_FAILED_BREAKOUT


def test_no_reclaim_and_no_target_is_unresolved_not_failed():
    # Held above the trigger the whole way and simply went nowhere -- a
    # different outcome from giving the level back, and kept distinct.
    config = _config(target_horizon_mult=2.0, target_horizon_min_bars=20, target_horizon_max_bars=252)
    closes = [100.0] * 5 + [120.0] + [121.0] * 40
    df = _bars(closes)
    match = _match(Direction.BULLISH)
    match.target_price = 300.0
    _apply(df, match, formation_end_bar_index=4, formation_bars=4, trigger=110.0, config=config)
    assert match.status is PatternStatus.EXPIRED_UNRESOLVED


def test_reclaim_still_active_while_data_runs_out_inside_the_horizon():
    config = _config(target_horizon_mult=2.0, target_horizon_min_bars=50, target_horizon_max_bars=252)
    closes = [100.0] * 5 + [120.0] + [105.0] * 5
    df = _bars(closes)
    match = _match(Direction.BULLISH)
    match.target_price = 300.0
    _apply(df, match, formation_end_bar_index=4, formation_bars=4, trigger=110.0, config=config)
    assert match.status is PatternStatus.ACTIVE

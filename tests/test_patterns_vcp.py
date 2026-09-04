import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Direction, Timeframe
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.detectors.vcp import VCPDetector
from src.signals.patterns.models import PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, volume_sma_period=5, breakout_buffer_pct=0.001, expire_lifespan_mult=2.0,
        # Test-friendly overrides of the daily-preset MA/ATR windows -- a
        # 200+-bar Trend Template gate and literal ATR(10)/ATR(50) would
        # need a much larger fixture than a synthetic unit test warrants;
        # the gate logic itself is period-agnostic.
        vcp_52w_high_lookback_bars=100, vcp_atr_short_period=5, vcp_atr_long_period=20,
    )
    defaults.update(overrides)
    return PatternConfig(**defaults)


# A long, smooth linear ramp (50->92 over 220 bars) puts every Trend
# Template condition (price above rising medium/long MAs, short MA
# stacked above both, price at its own trailing high) trivially in place
# for *any* sufficiently-long straight-line uptrend -- SMA(N) on linear
# data is just the value N/2 bars back, so SMA50 > SMA150 > SMA200 (and
# both rising) falls out for free. Three contraction legs follow, each
# shallower than the last (29.5% -> 8.2% -> 1.2%) with higher lows
# (64.9 < 80.9 < 84.1) and a genuinely tightening final leg (big absolute
# swings early, a near-flat final leg) so the ATR(short)/ATR(long) ratio
# actually contracts, not just the % depths.
def _prefix() -> np.ndarray:
    ramp = np.linspace(50.0, 92.0, 220)
    leg1_down = np.linspace(90.0, 65.0, 20)
    leg1_up = np.linspace(67.0, 88.0, 15)
    leg2_down = np.linspace(87.0, 81.0, 10)
    leg2_up = np.linspace(82.0, 85.0, 8)
    leg3_down = np.linspace(84.7, 84.2, 6)
    return np.concatenate([ramp, leg1_down, leg1_up, leg2_down, leg2_up, leg3_down])
    # Pivots this produces (via VCP's own internal fine detect_pivots):
    # HIGH@219=92.1, LOW@239=64.9, HIGH@254=88.1, LOW@264=80.9,
    # HIGH@272=85.1, LOW@278=84.1 -- a 3-contraction base (6 pivots) with
    # a 2-contraction subset (the last 4) also independently valid.


def _df(tail_closes: np.ndarray, start: str = "2020-01-01") -> pd.DataFrame:
    closes = np.concatenate([_prefix(), tail_closes])
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes + 0.1, "low": closes - 0.1, "close": closes, "volume": 1000.0}, index=idx,
    )


def test_vcp_confirmed_breakout_hits_target():
    df = _df(np.linspace(84.5, 130.0, 25))
    df.loc[df.index[280], "volume"] = 1600.0
    config = _config()

    matches = VCPDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    # The full 3-contraction base and two independent 2-contraction
    # subsets of it (bars 219-264 and 254-278) all pass every gate --
    # expected per §9's "return every candidate, don't force exclusivity"
    # (already established for every other detector here).
    assert len(matches) == 3
    m = next(m for m in matches if len(m.pivots) == 6)
    assert m.pattern_type == PatternType.VCP
    assert m.direction == Direction.BULLISH
    assert m.key_levels["pivot_price"] == pytest.approx(85.1, abs=0.05)
    assert m.key_levels["base_low"] == pytest.approx(64.9, abs=0.05)
    assert m.key_levels["contraction_0_depth_pct"] > m.key_levels["contraction_1_depth_pct"] > m.key_levels["contraction_2_depth_pct"]
    assert m.target_price == pytest.approx(m.key_levels["pivot_price"] + (m.key_levels["pivot_price"] - m.key_levels["base_low"]))
    assert m.stop_price == pytest.approx(m.key_levels["base_low"])
    assert m.breakout_bar == 280
    assert m.volume_confirmed is True
    assert m.status == PatternStatus.HIT_TARGET
    assert 0.0 < m.confidence <= 1.0
    assert len(m.notes) == 5


def test_weak_trend_template_rejects_candidate():
    # An impossible "within -1% of the 52-week high" requirement rejects
    # every candidate regardless of the base's own geometry.
    df = _df(np.linspace(84.5, 130.0, 25))
    config = _config(vcp_pct_from_52w_high_max=-1.0)

    matches = VCPDetector().scan(df, [], "TST", Timeframe.DAILY, config)
    assert matches == []


def test_monotonicity_gate_rejects_when_no_violations_allowed():
    # The fixture's real contraction sequence has zero violations
    # (29.5% -> 8.2% -> 1.2%, strictly shrinking) -- disallowing even
    # that still-clean sequence proves the violation-count comparison
    # itself is wired correctly.
    df = _df(np.linspace(84.5, 130.0, 25))
    config = _config(vcp_contraction_violations_allowed=-1)

    matches = VCPDetector().scan(df, [], "TST", Timeframe.DAILY, config)
    assert matches == []


def test_atr_contraction_ratio_gate_rejects_when_configured_tighter_than_actual():
    df = _df(np.linspace(84.5, 130.0, 25))
    config = _config(vcp_atr_contraction_max_ratio=0.1)

    matches = VCPDetector().scan(df, [], "TST", Timeframe.DAILY, config)
    assert matches == []


def test_lower_low_in_later_contraction_rejects_candidate():
    # Second contraction's low (60.0) sits below the first's (64.9) --
    # violates §4.5 point 5's higher-lows requirement.
    ramp = np.linspace(50.0, 92.0, 220)
    leg1_down = np.linspace(90.0, 65.0, 20)
    leg1_up = np.linspace(67.0, 88.0, 15)
    leg2_down = np.linspace(87.0, 60.0, 10)
    leg2_up = np.linspace(62.0, 85.0, 8)
    leg3_down = np.linspace(84.7, 84.2, 6)
    closes = np.concatenate([ramp, leg1_down, leg1_up, leg2_down, leg2_up, leg3_down, np.linspace(84.5, 130.0, 25)])
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    df = pd.DataFrame(
        {"open": closes, "high": closes + 0.1, "low": closes - 0.1, "close": closes, "volume": 1000.0}, index=idx,
    )
    config = _config()

    matches = VCPDetector().scan(df, [], "TST", Timeframe.DAILY, config)
    assert matches == []


def test_new_low_below_base_invalidates():
    # A small bounce first (confirms bar 278 as its own zigzag low pivot
    # -- without it, an immediately-continuing decline would just push
    # the *candidate* low further out and bar 278 would never be
    # confirmed as a pivot at all, so this wouldn't test post-detection
    # invalidation, it'd just prevent detection). The bounce stays under
    # the 85.1 breakout trigger, then price falls well below base_low
    # (64.9) without ever closing above the trigger first.
    tail = np.concatenate([np.linspace(84.4, 84.8, 3), np.linspace(83.0, 55.0, 6)])
    df = _df(tail)
    config = _config()

    matches = VCPDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 3
    assert all(m.status == PatternStatus.INVALIDATED for m in matches)
    assert all(m.breakout_bar is None for m in matches)


def test_reclaim_without_reaching_target_flags_failed_breakout():
    tail = np.concatenate([[86.0], np.full(40, 84.5)])
    df = _df(tail)
    config = _config(target_horizon_min_bars=5, target_horizon_max_bars=10)

    matches = VCPDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    # The 2-contraction candidate spanning bars 219-264 has its own
    # pivot_price (88.1, off the bar-254 high) rather than 85.1 -- the
    # 86.0 spike here never reaches it, so that one candidate stays
    # PENDING while the other two (both anchored to the bar-272 high)
    # see the same breakout-then-reclaim.
    assert len(matches) == 3
    resolved = [m for m in matches if m.key_levels["pivot_price"] == pytest.approx(85.1, abs=0.05)]
    assert len(resolved) == 2
    assert all(m.breakout_bar == 279 for m in resolved)
    assert all(m.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT for m in resolved)
    still_pending = next(m for m in matches if m.key_levels["pivot_price"] == pytest.approx(88.1, abs=0.05))
    assert still_pending.status == PatternStatus.PENDING


def test_expired_when_no_breakout_within_deadline():
    df = _df(np.full(130, 84.3))
    config = _config()

    matches = VCPDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 3
    assert all(m.status == PatternStatus.EXPIRED for m in matches)
    assert all(m.breakout_bar is None for m in matches)


def test_pending_when_not_enough_bars_yet_to_resolve():
    df = _df(np.full(3, 84.3))
    config = _config()

    matches = VCPDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 3
    assert all(m.status == PatternStatus.PENDING for m in matches)
    assert all(m.breakout_bar is None for m in matches)

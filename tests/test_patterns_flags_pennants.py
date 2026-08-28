import numpy as np
import pandas as pd
import pytest

from src.market_common.models import Direction, Timeframe
from src.patterns.config import PatternConfig
from src.patterns.detectors.flags_pennants import FlagPennantDetector
from src.patterns.models import PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, volume_sma_period=5, breakout_buffer_pct=0.001,
        expire_lifespan_mult=2.0,
        flag_typical_min_bars=1, flag_typical_max_bars=50,
        # A much smaller test-only multiplier than the real 1.5 default --
        # see config.py's own comment on flag_pivot_atr_mult for why the
        # real default needed real-data calibration; the gate logic under
        # test here is period-agnostic, and a tiny synthetic fixture needs
        # a correspondingly tiny confirmation threshold to produce a
        # clean, small pole + 4-pivot consolidation deterministically
        # (see the module-level comment below for the mechanics).
        flag_pivot_atr_mult=0.3,
    )
    defaults.update(overrides)
    return PatternConfig(**defaults)


def _df(tail_closes: np.ndarray, prefix: np.ndarray, start: str = "2020-01-01") -> pd.DataFrame:
    closes = np.concatenate([prefix, tail_closes])
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes + 0.1, "low": closes - 0.1, "close": closes, "volume": 1000.0}, index=idx,
    )


# Unlike every other detector's tests, FlagPennantDetector runs its own
# internal detect_pivots pass (like VCP) rather than accepting a hand-built
# pivot list -- so these fixtures are real close-price paths whose *own*
# zigzag naturally produces the pole + 4-pivot consolidation shape, not
# arbitrary Pivot objects. Two mechanics worth recording, both found by
# iterating against the real detect_pivots output before locking these in:
#   1. A pivot's confirmation threshold uses ATR *at that pivot's own bar*
#      -- right at a sharp pole's peak, that's elevated by the pole itself,
#      so the pole's own start needs a real prior downtrend to confirm as
#      its own LOW pivot (a flat lead-in never reverses, so it never
#      "confirms" one at all).
#   2. A consolidation pivot only confirms once a *later* bar reverses far
#      enough away from it -- the bull-flag fixture's consolidation needs
#      a 5th value (123.0) purely to supply that reversal and confirm the
#      4th (bar 18) pivot; that 5th bar is therefore part of the *fixed*
#      prefix every lifecycle-variant test below shares, not a "tail" bar
#      -- appending a *different* tail starting one bar later, on top of
#      an unconfirmed 4th pivot, would silently change which bars end up
#      confirmed as pivots at all (caught by a first attempt at these
#      fixtures that produced nonsensical results across every variant).
#
# Pole: LOW@9=99.9 -> HIGH@14=130.1 (five bars, ~30%). Consolidation
# (4 confirmed pivots): LOW@15=125.9, HIGH@16=129.1, LOW@17=123.9,
# HIGH@18=128.1 -- upper line slope -0.5, lower line slope -1.0 (upper >
# lower, so these do NOT converge -> a flag, not a pennant). retrace ~20%
# of the pole, range_ratio ~0.17. formation_end_bar_index=18 -- bar 19
# (123.0, the reversal that confirms bar 18) is therefore the first
# post-formation bar baked into every fixture below, not a "tail" bar.
_BULL_FLAG_PREFIX = np.concatenate([
    np.linspace(115.0, 100.0, 10),          # downtrend into the pole's own start
    np.linspace(103.0, 130.0, 5),           # the pole itself
    [126.0, 129.0, 124.0, 128.0, 123.0],    # 4 consolidation pivots + their confirming reversal
])


def test_bull_flag_confirmed_breakout_hits_target():
    df = _df(np.linspace(125.0, 175.0, 15), _BULL_FLAG_PREFIX)
    df.loc[df.index[21], "volume"] = 1600.0
    config = _config()

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.BULL_FLAG
    assert m.direction == Direction.BULLISH
    assert m.key_levels["pole_start"] == pytest.approx(99.9, abs=0.05)
    assert m.key_levels["pole_end"] == pytest.approx(130.1, abs=0.05)
    assert m.trendlines["upper"] == pytest.approx((-0.5, 137.1), abs=0.05)
    assert m.trendlines["lower"] == pytest.approx((-1.0, 140.9), abs=0.05)
    assert m.target_price == pytest.approx(158.3, abs=0.1)
    assert m.stop_price == pytest.approx(122.9, abs=0.1)
    assert m.breakout_bar == 21
    assert m.volume_confirmed is True
    assert m.status == PatternStatus.HIT_TARGET
    assert 0.0 < m.confidence <= 1.0
    assert len(m.notes) == 5


def test_bear_flag_mirrors_bull_flag():
    # Direct mirror of the bull-flag fixture (price reflected around 115).
    prefix = np.concatenate([
        np.linspace(115.0, 130.0, 10),
        np.linspace(127.0, 100.0, 5),
        [104.0, 101.0, 106.0, 102.0, 107.0],
    ])
    df = _df(np.linspace(105.0, 55.0, 15), prefix)
    config = _config()

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.BEAR_FLAG
    assert m.direction == Direction.BEARISH
    assert m.status == PatternStatus.HIT_TARGET


def test_pennant_classified_when_boundaries_converge():
    # Same pole; consolidation highs decline (129.1->128.8) while lows
    # rise (125.9->126.9) -- upper_slope < lower_slope, a genuine
    # convergence, classified as a pennant instead of a flag.
    prefix = np.concatenate([
        np.linspace(115.0, 100.0, 10),
        np.linspace(103.0, 130.0, 5),
        [126.0, 129.0, 127.0, 128.7, 127.3],
    ])
    df = _df(np.linspace(128.5, 175.0, 15), prefix)
    config = _config()

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].pattern_type == PatternType.PENNANT
    assert matches[0].direction == Direction.BULLISH
    assert matches[0].status == PatternStatus.HIT_TARGET


def test_pole_too_weak_rejects_candidate():
    # Real pole move is ~30% -- raising the requirement above that rejects.
    df = _df(np.linspace(125.0, 175.0, 15), _BULL_FLAG_PREFIX)
    config = _config(flag_pole_min_pct=35.0)

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)
    assert matches == []


def test_pole_too_slow_rejects_candidate():
    # Real pole spans 5 bars -- tightening the ceiling below that rejects.
    df = _df(np.linspace(125.0, 175.0, 15), _BULL_FLAG_PREFIX)
    config = _config(flag_pole_max_bars=3)

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)
    assert matches == []


def test_retrace_gate_rejects_when_configured_tighter_than_actual():
    df = _df(np.linspace(125.0, 175.0, 15), _BULL_FLAG_PREFIX)
    config = _config(flag_max_retrace_pct=10.0)

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)
    assert matches == []


def test_consolidation_range_gate_rejects_when_configured_tighter_than_actual():
    df = _df(np.linspace(125.0, 175.0, 15), _BULL_FLAG_PREFIX)
    config = _config(flag_consolidation_max_range_ratio=0.05)

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)
    assert matches == []


def test_consolidation_too_long_rejects_candidate():
    df = _df(np.linspace(125.0, 175.0, 15), _BULL_FLAG_PREFIX)
    config = _config(flag_consolidation_max_bars=1)

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)
    assert matches == []


def test_retrace_violation_after_formation_invalidates():
    # retrace_violation_level = 130.1 - 30.2*0.5 = 115.0 -- price falls
    # below that without ever closing above the (declining) upper trigger
    # first.
    df = _df(np.linspace(120.0, 100.0, 5), _BULL_FLAG_PREFIX)
    config = _config()

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.INVALIDATED
    assert matches[0].breakout_bar is None


def test_reclaim_without_reaching_target_flags_failed_breakout():
    tail = np.concatenate([[130.0], np.full(40, 125.0)])
    df = _df(tail, _BULL_FLAG_PREFIX)
    config = _config()

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.breakout_bar == 20
    assert m.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT


def test_expired_when_no_breakout_within_deadline():
    # formation_bars = 18-9 = 9 -> pending deadline at bar 18+18=36. A
    # flat 118.0 stays below the still-declining upper trigger (down to
    # ~119.1 by bar 36) and above the fixed 115.0 retrace floor the whole
    # way, so neither ever resolves before the deadline does.
    df = _df(np.full(18, 118.0), _BULL_FLAG_PREFIX)
    config = _config()

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.EXPIRED
    assert matches[0].breakout_bar is None


def test_pending_when_not_enough_bars_yet_to_resolve():
    df = _df(np.full(2, 123.0), _BULL_FLAG_PREFIX)
    config = _config()

    matches = FlagPennantDetector().scan(df, [], "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.PENDING
    assert matches[0].breakout_bar is None

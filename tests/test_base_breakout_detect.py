"""Base-breakout-retest detection: episode construction against engineered OHLC bars.

Bars are built from explicit (high, low, close) rows with ATR pinned at 1, so every
threshold reads directly: the level is 100, the retest tolerance 0.5 means "low <= 100.5",
the kill tolerance 0.25 means "close < 99.75".
"""

import numpy as np
import pandas as pd
import pytest

from src.signals.base_breakout.detect import (
    EXPIRED, KILLED, RETEST_HELD, BreakoutRetestConfig, Episode, detect, level_overlay)

ATR = 1.0
LEVEL = 100.0


def bars_from(rows: list[tuple[float, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["high", "low", "close"])
    frame.insert(0, "date", pd.bdate_range("2015-01-02", periods=len(frame)))
    frame["open"] = frame["close"]
    return frame


def atr_for(frame: pd.DataFrame) -> pd.Series:
    return pd.Series(ATR, index=frame.index)


def base(bars: int = 35, floor: float = 88.0) -> list[tuple[float, float, float]]:
    """A flat base: the first bar sets the level at 100, the second carries the depth
    low, the rest sit quietly below both thresholds."""
    return [(LEVEL, 95.0, 95.0), (95.0, floor, 92.0)] + [(95.0, 92.0, 93.0)] * (bars - 2)


BREAKOUT = (102.0, 100.6, 101.0)   # close above the level; low stays off it
RALLY = (103.0, 101.0, 102.0)      # neither a retest (low > 100.5) nor a kill
RETEST_HOLD = (101.5, 100.3, 100.6)  # low within 0.5 of the level, close holds above it
KILL = (100.5, 98.0, 98.7)         # close more than 0.25 below the level


def run(rows, **config_overrides) -> list[Episode]:
    frame = bars_from(rows)
    return detect(frame, atr_for(frame), BreakoutRetestConfig(**config_overrides))


def test_clean_episode_base_breakout_then_holding_retest():
    episodes = run(base(35) + [BREAKOUT, RALLY, RETEST_HOLD])
    assert len(episodes) == 1
    e = episodes[0]
    assert (e.base_start, e.breakout, e.retest, e.end) == (0, 35, 37, 37)
    assert e.outcome == RETEST_HELD
    assert e.level == LEVEL and e.base_bars == 35
    assert e.depth_pct == pytest.approx(12.0)


def test_close_exactly_at_the_level_holds():
    at_level = (101.0, 100.2, 100.0)
    episodes = run(base(35) + [BREAKOUT, at_level])
    assert episodes[0].outcome == RETEST_HELD and episodes[0].retest == 36


def test_decisive_close_below_kills_before_any_retest():
    episodes = run(base(35) + [BREAKOUT, KILL, RETEST_HOLD])
    assert len(episodes) == 1
    e = episodes[0]
    assert e.outcome == KILLED and e.retest is None and e.end == 36


def test_no_retest_within_the_window_expires():
    episodes = run(base(35) + [BREAKOUT] + [RALLY] * 6, retest_window_bars=4)
    e, = episodes
    assert e.outcome == EXPIRED and e.retest is None and e.end == 35 + 4


def test_short_base_is_not_an_episode():
    assert run(base(20) + [BREAKOUT, RETEST_HOLD]) == []


def test_depth_outside_the_bounds_is_not_an_episode():
    assert run(base(35, floor=95.0) + [BREAKOUT, RETEST_HOLD]) == []   # 5% — too shallow
    assert run(base(35, floor=55.0) + [BREAKOUT, RETEST_HOLD]) == []   # 45% — too deep


def test_depth_is_measured_over_the_base_only():
    # A post-breakout crash low of 50 would read as 50% depth if the base window leaked
    # forward; the episode (12% deep) must still exist, resolved as killed by the crash.
    crash = (100.5, 50.0, 98.0)
    episodes = run(base(35) + [BREAKOUT, crash])
    assert len(episodes) == 1 and episodes[0].depth_pct == pytest.approx(12.0)
    assert episodes[0].outcome == KILLED


def test_base_max_bars_caps_the_base_length():
    assert run(base(35) + [BREAKOUT, RETEST_HOLD], base_max_bars=30) == []
    assert len(run(base(35) + [BREAKOUT, RETEST_HOLD], base_max_bars=40)) == 1


def test_rally_closes_above_a_rising_max_do_not_start_overlapping_episodes():
    rising = [(104.0, 102.0, 103.5), (105.0, 103.0, 104.5)]  # each close above the prior max
    episodes = run(base(35) + [BREAKOUT] + rising + [RETEST_HOLD], retest_window_bars=40)
    assert len(episodes) == 1 and episodes[0].breakout == 35


def test_detection_is_point_in_time():
    rows = base(35) + [BREAKOUT, RALLY, RETEST_HOLD, RALLY, KILL]
    full = run(rows)
    truncated = run(rows[:38])  # cut right at the retest bar
    assert full[0] == truncated[0]


def test_nan_atr_ends_the_episode_instead_of_reading_as_nothing_happened():
    frame = bars_from(base(35) + [BREAKOUT, RETEST_HOLD])
    atr = atr_for(frame)
    atr.iloc[36] = np.nan  # the would-be retest bar is undecidable
    e, = detect(frame, atr, BreakoutRetestConfig())
    assert e.outcome == EXPIRED and e.retest is None and e.end == 36


def test_level_overlay_spans_each_episode_and_is_nan_elsewhere():
    episodes = run(base(35) + [BREAKOUT, RALLY, RETEST_HOLD, RALLY])
    overlay = level_overlay(39, episodes)
    assert np.allclose(overlay[0:38], LEVEL)
    assert np.isnan(overlay[38])


def test_config_validation_refuses_degenerate_bounds():
    with pytest.raises(ValueError, match="depth bounds"):
        BreakoutRetestConfig(depth_min_pct=40.0, depth_max_pct=10.0).validate()
    with pytest.raises(ValueError, match="lookback"):
        BreakoutRetestConfig(base_max_bars=600, base_lookback_bars=504).validate()
    with pytest.raises(ValueError, match="base_min_bars"):
        BreakoutRetestConfig(base_min_bars=1).validate()

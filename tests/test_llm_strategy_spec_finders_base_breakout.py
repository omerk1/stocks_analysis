"""The base-breakout-retest instance finder: detection against an engineered panel,
the five near-miss rings, the rubric's source labels, the in-place overlay column, and
the refusals.

The panel is built from explicit (high, low, close) rows with ATR pinned at 1 — the base
high (the level) is 100, so the retest tolerance 0.5 reads as "low <= 100.5" and the kill
tolerance 0.25 as "close < 99.75". Detection runs on unlagged OHLC, so unlike the MA
finder's tests nothing here is shifted: the match date IS the engineered retest bar.
"""

import numpy as np
import pandas as pd
import pytest

from src.llm.strategy_spec.finders import (
    BASE_BREAKOUT_OVERLAY, GroundingError, dispatch, find_base_breakout_retest)
from src.llm.strategy_spec.schema import Duration, Rule, Size, StrategySpec, Trigger

LEVEL = 100.0


def base(bars: int = 35, floor: float = 88.0) -> list[tuple[float, float, float]]:
    return [(LEVEL, 95.0, 95.0), (95.0, floor, 92.0)] + [(95.0, 92.0, 93.0)] * (bars - 2)


BREAKOUT = (102.0, 100.6, 101.0)
RALLY = (103.0, 101.0, 102.0)
RETEST_HOLD = (101.5, 100.3, 100.6)   # low within 0.5 ATR of the level, close holds
RETEST_LOOSE = (101.5, 100.6, 101.0)  # low within 0.75 ATR only — the tolerance ring

MATCH = base(35) + [BREAKOUT, RALLY, RETEST_HOLD]
LENGTH_RING = base(25) + [BREAKOUT, RALLY, RETEST_HOLD]          # base 25: >= 20, < 30
FLOOR_RING = base(35, floor=92.0) + [BREAKOUT, RALLY, RETEST_HOLD]  # depth 8%: >= 6.67, < 10
CAP_RING = base(35, floor=50.0) + [BREAKOUT, RALLY, RETEST_HOLD]    # depth 50%: <= 60, > 40
WINDOW_RING = base(35) + [BREAKOUT] + [RALLY] * 44 + [RETEST_HOLD]  # retest on bar 45 after the breakout
TOL_RING = base(35) + [BREAKOUT, RALLY, RETEST_LOOSE] + [RALLY] * 45  # never retests strictly


def panel(ticker_rows: dict[str, list[tuple[float, float, float]]],
          start: str = "2015-01-02") -> pd.DataFrame:
    frames = []
    for ticker, rows in ticker_rows.items():
        frame = pd.DataFrame(rows, columns=["high", "low", "close"])
        frame.insert(0, "ticker", ticker)
        frame.insert(1, "date", pd.bdate_range(start, periods=len(frame)))
        frame["open"] = frame["close"]
        frame["atr_14"] = 1.0
        frames.append(frame)
    return (pd.concat(frames, ignore_index=True)
            .sort_values(["ticker", "date"]).reset_index(drop=True))


def spec(**overrides) -> StrategySpec:
    fields = dict(direction="long", timeframe="daily",
                  duration=Duration(min_bars=30),
                  size=Size(normalisation="pct", min=10.0, max=40.0),
                  trigger=Trigger(price_basis="close", execution="next_open"),
                  uses=["detector:base_breakout.retest"])
    return StrategySpec(**{**fields, **overrides})


def signal_date(rows: list, position: int, start: str = "2015-01-02") -> pd.Timestamp:
    return pd.bdate_range(start, periods=len(rows))[position]


def test_finds_the_match_on_the_retest_bar_and_paints_the_overlay():
    frame = panel({"AAA": MATCH})
    result = find_base_breakout_retest(spec(), frame)
    assert [(c.ticker, c.date) for c in result.matches] == [("AAA", signal_date(MATCH, 37))]
    assert result.matches[0].fails is None and result.near_misses == ()
    # The candidate carries its own chart geometry: the level across its episode
    # (base start through the retest bar), so the chart never shows another episode's.
    assert result.matches[0].overlay_span == (signal_date(MATCH, 0), signal_date(MATCH, 37), LEVEL)
    assert (result.overlay_column, result.overlay_name) == (BASE_BREAKOUT_OVERLAY, "breakout level")
    # The overlay was added to the caller's panel in place, one-bar-lagged: the level
    # spans the episode (base start through the retest, positions 0-37), shifted one
    # row forward — the retest bar's own value lands past the 38-row frame's end.
    overlay = frame[BASE_BREAKOUT_OVERLAY]
    assert overlay.iloc[1:38].eq(LEVEL).all() and np.isnan(overlay.iloc[0])


def test_each_ring_yields_its_near_miss_and_no_match():
    result = find_base_breakout_retest(spec(), panel(
        {"LEN": LENGTH_RING, "FLR": FLOOR_RING, "CAP": CAP_RING, "WIN": WINDOW_RING, "TOL": TOL_RING}))
    assert result.matches == ()
    by_ticker = {c.ticker: c for c in result.near_misses}
    assert set(by_ticker) == {"LEN", "FLR", "CAP", "WIN", "TOL"}
    assert by_ticker["LEN"].fails.startswith("base length") and ">= 20" in by_ticker["LEN"].fails
    assert by_ticker["FLR"].fails.startswith("base depth floor")
    assert by_ticker["CAP"].fails.startswith("base depth cap") and "60" in by_ticker["CAP"].fails
    assert by_ticker["WIN"].fails.startswith("retest window") and "41-60" in by_ticker["WIN"].fails
    assert by_ticker["WIN"].date == signal_date(WINDOW_RING, 35 + 45)
    assert by_ticker["TOL"].fails.startswith("retest tolerance") and "0.75" in by_ticker["TOL"].fails
    assert len(result.near_misses) == len({(c.ticker, c.date) for c in result.near_misses})
    # Every near-miss carries its own ring episode's geometry, ending on its signal bar.
    for c in result.near_misses:
        assert c.overlay_span[2] == LEVEL and c.overlay_span[1] == c.date
    assert by_ticker["LEN"].overlay_span[0] == signal_date(LENGTH_RING, 0)


def test_a_loose_early_retest_of_a_strictly_firing_episode_is_suppressed():
    # The relaxed tolerance pulls the retest one bar earlier, but the same episode still
    # fires strictly a bar later — the early bar says nothing about the tolerance.
    rows = base(35) + [BREAKOUT, RETEST_LOOSE, RETEST_HOLD]
    result = find_base_breakout_retest(spec(), panel({"AAA": rows}))
    assert [c.date for c in result.matches] == [signal_date(rows, 37)]
    assert result.near_misses == ()


def test_spec_numbers_override_the_defaults():
    result = find_base_breakout_retest(
        spec(duration=Duration(min_bars=20)), panel({"AAA": LENGTH_RING}))
    assert len(result.matches) == 1  # a 25-bar base qualifies under the spec's own floor
    floor_line = next(r for r in result.rubric if r.parameter == "base length floor")
    assert floor_line.source == "spec" and ">= 20" in floor_line.value


def test_rubric_discloses_every_default_and_the_invalidation_convention():
    result = find_base_breakout_retest(
        spec(invalidation=[Rule(description="retest closes decisively back below", phase="before_entry"),
                           Rule(description="close below within 3 bars", phase="after_entry")]),
        panel({"AAA": MATCH}))
    by_parameter = {r.parameter: r for r in result.rubric}
    for parameter in ("timeframe", "price basis", "direction", "base length floor",
                      "base depth floor", "base depth cap"):
        assert by_parameter[parameter].source == "spec"
    for parameter in ("trigger", "retest tolerance", "retest window",
                      'failed-retest kill ("decisively below")', "minimum rally", "base length cap"):
        assert by_parameter[parameter].source == "default"
    before = by_parameter["invalidation (before entry): retest closes decisively back below"]
    assert before.value == "NOT READ"
    assert not any("after_entry" in r.parameter or "within 3 bars" in r.parameter for r in result.rubric)


def test_unstated_direction_grounds_long_with_a_disclosed_default():
    result = find_base_breakout_retest(spec(direction=None), panel({"AAA": MATCH}))
    assert len(result.matches) == 1
    line = next(r for r in result.rubric if r.parameter == "direction")
    assert line.source == "default" and "long" in line.value


def test_near_misses_false_keeps_matches_rubric_and_overlay_identical():
    frame_full, frame_lean = panel({"AAA": MATCH, "LEN": LENGTH_RING}), panel({"AAA": MATCH, "LEN": LENGTH_RING})
    full = find_base_breakout_retest(spec(), frame_full)
    lean = find_base_breakout_retest(spec(), frame_lean, near_misses=False)
    assert lean.matches == full.matches and lean.rubric == full.rubric
    assert lean.near_misses == () and full.near_misses != ()
    # The strict episode's overlay is painted either way (ring overlays only with rings):
    # 38 episode rows, one-bar-lagged, the last falling off the 38-row frame leaves 37.
    aaa = frame_lean["ticker"] == "AAA"
    assert frame_lean.loc[aaa, BASE_BREAKOUT_OVERLAY].eq(LEVEL).sum() == 37


def test_dispatch_finds_the_finder_from_the_spec_uses():
    finder_id, result = dispatch(spec(), panel({"AAA": MATCH}), note=lambda _: None)
    assert finder_id == "detector:base_breakout.retest" and len(result.matches) == 1


@pytest.mark.parametrize("bad_spec, message", [
    (dict(direction="short"), "long side only"),
    (dict(direction="both"), "long side only"),
    (dict(timeframe=None), "doesn't state a timeframe"),
    (dict(timeframe="weekly"), "weekly idea"),
    (dict(size=Size(normalisation="atr", min=1.0)), "in percent"),
    (dict(size=Size(min=10.0, max=40.0)), "no units"),
    (dict(trigger=Trigger(price_basis="intraday")), "intraday trigger"),
    (dict(size=Size(normalisation="pct", min=40.0, max=10.0)), "detectable definition"),
])
def test_refusals_name_the_problem(bad_spec, message):
    with pytest.raises(GroundingError, match=message):
        find_base_breakout_retest(spec(**bad_spec), panel({"AAA": MATCH}))


def test_missing_panel_column_and_unsorted_panel_are_refused():
    frame = panel({"AAA": MATCH})
    with pytest.raises(GroundingError, match="atr_14"):
        find_base_breakout_retest(spec(), frame.drop(columns=["atr_14"]))
    shuffled = frame.sample(frac=1.0, random_state=7).reset_index(drop=True)
    with pytest.raises(GroundingError, match="date-sorted"):
        find_base_breakout_retest(spec(), shuffled)

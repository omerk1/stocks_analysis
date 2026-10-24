"""The base-breakout-retest instance finder: detection against an engineered panel,
the ten near-miss rings, the rubric's source labels, the in-place overlay column, and
the refusals.

The panel is built from explicit (high, low, close) rows with ATR pinned at 1 (the
finder's `same_bar_atr` is swapped for the fixture's `true_atr` column) — the base
high (the level) is 100, so the retest tolerance 0.5 reads as "low <= 100.5" and the kill
tolerance 0.25 as "close < 99.75". Detection runs on unlagged OHLC, so unlike the MA
finder's tests nothing here is shifted: the match date IS the engineered retest bar.
"""

import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common import indicators
from src.llm.strategy_spec import finders
from src.llm.strategy_spec.finders import (
    BASE_BREAKOUT_OVERLAY, GroundingError, dispatch, find_base_breakout_retest)
from src.llm.strategy_spec.schema import Duration, Rule, Size, StrategySpec, Trigger


@pytest.fixture(autouse=True)
def pinned_atr(monkeypatch):
    monkeypatch.setattr(finders, "same_bar_atr", lambda frame: frame["true_atr"])

LEVEL = 100.0
TOUCH = (99.6, 95.0, 96.0)  # high back within 0.5 ATR of the level without exceeding it


def base(bars: int = 35, floor: float = 88.0, touches: int = 2) -> list[tuple[float, float, float]]:
    return ([(LEVEL, 95.0, 95.0), (95.0, floor, 92.0)] + [TOUCH] * touches
            + [(95.0, 92.0, 93.0)] * (bars - 2 - touches))


BREAKOUT = (102.0, 100.6, 101.0)      # decisive close; the high also arms the 1-ATR rally
WEAK_BREAKOUT = (100.9, 100.3, 100.8)  # decisive close, but never 1 ATR above the level
MARGINAL_BREAKOUT = (100.6, 100.0, 100.2)  # clears the level by 0.2 ATR: inside the 0.25 margin
RALLY = (103.0, 101.0, 102.0)
DRIFT = (100.8, 100.6, 100.7)         # above the level but arms nothing and retests nothing
RETEST_HOLD = (101.5, 100.3, 100.6)   # low within 0.5 ATR of the level, close holds
RETEST_LOOSE = (101.5, 100.6, 101.0)  # low within 0.75 ATR only — the tolerance ring
AWAY = [RALLY] * 4                    # fills the 5-bar retest gap after the breakout


def ramp_touch_base() -> list[tuple[float, float, float]]:
    """Touches only 4 and 5 bars before the breakout — ramp bars the strict exclusion
    (last 5) ignores and the relaxed exclusion (last 3) counts."""
    rows = base(35, touches=0)
    rows[30], rows[31] = TOUCH, TOUCH
    return rows


MATCH = base(35) + [BREAKOUT] + AWAY + [RETEST_HOLD]
LENGTH_RING = base(25) + [BREAKOUT] + AWAY + [RETEST_HOLD]          # base 25: >= 20, < 30
FLOOR_RING = base(35, floor=92.0) + [BREAKOUT] + AWAY + [RETEST_HOLD]  # depth 8%: >= 6.67, < 10
CAP_RING = base(35, floor=50.0) + [BREAKOUT] + AWAY + [RETEST_HOLD]    # depth 50%: <= 60, > 40
WINDOW_RING = base(35) + [BREAKOUT] + [RALLY] * 44 + [RETEST_HOLD]  # retest on bar 45 after the breakout
TOUCHES_RING = base(35, touches=1) + [BREAKOUT] + AWAY + [RETEST_HOLD]  # 1 touch: >= 1, < 2
EXCLUDE_RING = ramp_touch_base() + [BREAKOUT] + AWAY + [RETEST_HOLD]
MARGIN_RING = base(35) + [MARGINAL_BREAKOUT] + AWAY + [RETEST_HOLD]  # breaks out only past 0.167 ATR
RALLY_RING = base(35) + [WEAK_BREAKOUT] + [DRIFT] * 4 + [RETEST_HOLD] + [RALLY] * 45  # armed only at 0.667 ATR
GAP_RING = base(35) + [BREAKOUT, RALLY, RALLY, RETEST_HOLD] + [RALLY] * 45  # retest 3 bars after the breakout
TOL_RING = base(35) + [BREAKOUT] + AWAY + [RETEST_LOOSE] + [RALLY] * 45  # never retests strictly


def panel(ticker_rows: dict[str, list[tuple[float, float, float]]],
          start: str = "2015-01-02") -> pd.DataFrame:
    frames = []
    for ticker, rows in ticker_rows.items():
        frame = pd.DataFrame(rows, columns=["high", "low", "close"])
        frame.insert(0, "ticker", ticker)
        frame.insert(1, "date", pd.bdate_range(start, periods=len(frame)))
        frame["open"] = frame["close"]
        frame["true_atr"] = 1.0
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
    assert [(c.ticker, c.date) for c in result.matches] == [("AAA", signal_date(MATCH, 40))]
    assert result.matches[0].fails is None and result.near_misses == ()
    # The candidate carries its own chart geometry: the level across its episode
    # (base start through the retest bar), so the chart never shows another episode's.
    assert result.matches[0].overlay_span == (signal_date(MATCH, 0), signal_date(MATCH, 40), LEVEL)
    assert (result.overlay_column, result.overlay_name) == (BASE_BREAKOUT_OVERLAY, "breakout level")
    # The overlay was added to the caller's panel in place, one-bar-lagged: the level
    # spans the episode (base start through the retest, positions 0-40), shifted one
    # row forward — the retest bar's own value lands past the 41-row frame's end. The
    # match itself sits on the ticker's LAST bar: a final-bar signal still fires.
    overlay = frame[BASE_BREAKOUT_OVERLAY]
    assert overlay.iloc[1:41].eq(LEVEL).all() and np.isnan(overlay.iloc[0])


def test_each_ring_yields_its_near_miss_and_no_match():
    result = find_base_breakout_retest(spec(), panel(
        {"LEN": LENGTH_RING, "FLR": FLOOR_RING, "CAP": CAP_RING, "WIN": WINDOW_RING,
         "TCH": TOUCHES_RING, "EXC": EXCLUDE_RING, "MGN": MARGIN_RING,
         "RLY": RALLY_RING, "GAP": GAP_RING, "TOL": TOL_RING}))
    assert result.matches == ()
    by_ticker = {c.ticker: c for c in result.near_misses}
    assert set(by_ticker) == {"LEN", "FLR", "CAP", "WIN", "TCH", "EXC", "MGN", "RLY", "GAP", "TOL"}
    assert by_ticker["LEN"].fails.startswith("base length") and ">= 20" in by_ticker["LEN"].fails
    assert by_ticker["FLR"].fails.startswith("base depth floor")
    assert by_ticker["CAP"].fails.startswith("base depth cap") and "60" in by_ticker["CAP"].fails
    assert by_ticker["WIN"].fails.startswith("retest window") and "41-60" in by_ticker["WIN"].fails
    assert by_ticker["WIN"].date == signal_date(WINDOW_RING, 35 + 45)
    assert by_ticker["TCH"].fails.startswith("level touches") and ">= 1" in by_ticker["TCH"].fails
    assert by_ticker["EXC"].fails.startswith("level touch timing") and "relaxed to 3" in by_ticker["EXC"].fails
    assert by_ticker["MGN"].fails.startswith("breakout decisiveness") and "0.167" in by_ticker["MGN"].fails
    assert by_ticker["RLY"].fails.startswith("minimum rally") and "0.667" in by_ticker["RLY"].fails
    assert by_ticker["RLY"].date == signal_date(RALLY_RING, 40)
    assert by_ticker["GAP"].fails.startswith("retest gap") and "3-4 bars" in by_ticker["GAP"].fails
    assert by_ticker["GAP"].date == signal_date(GAP_RING, 38)
    assert by_ticker["TOL"].fails.startswith("retest tolerance") and "0.75" in by_ticker["TOL"].fails
    assert len(result.near_misses) == len({(c.ticker, c.date) for c in result.near_misses})
    # Every near-miss carries its own ring episode's geometry, ending on its signal bar.
    for c in result.near_misses:
        assert c.overlay_span[2] == LEVEL and c.overlay_span[1] == c.date
    assert by_ticker["LEN"].overlay_span[0] == signal_date(LENGTH_RING, 0)


def test_a_loose_early_retest_of_a_strictly_firing_episode_is_suppressed():
    # The relaxed tolerance pulls the retest one bar earlier, but the same episode still
    # fires strictly a bar later — the early bar says nothing about the tolerance.
    rows = base(35) + [BREAKOUT] + AWAY + [RETEST_LOOSE, RETEST_HOLD]
    result = find_base_breakout_retest(spec(), panel({"AAA": rows}))
    assert [c.date for c in result.matches] == [signal_date(rows, 41)]
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
    for parameter in ("trigger", "retest tolerance", "retest window", "level touches",
                      "breakout decisiveness", "retest gap",
                      'failed-retest kill ("decisively below")', "minimum rally", "base length cap"):
        assert by_parameter[parameter].source == "default"
    assert "grounding round" in by_parameter["minimum rally"].detail
    assert "ramp exclusion" in by_parameter["level touches"].detail
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
    # 41 episode rows, one-bar-lagged, the last falling off the 41-row frame leaves 40.
    aaa = frame_lean["ticker"] == "AAA"
    assert frame_lean.loc[aaa, BASE_BREAKOUT_OVERLAY].eq(LEVEL).sum() == 40


def test_same_bar_atr_is_point_in_time_and_aligned_to_its_own_bar(monkeypatch):
    monkeypatch.undo()  # the real ATR, not the pinned one
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 1, 80))
    frame = pd.DataFrame({"high": close + rng.uniform(0.1, 2, 80),
                          "low": close - rng.uniform(0.1, 2, 80), "close": close},
                         index=range(500, 580))  # a non-zero-based slice, like a panel's
    atr = finders.same_bar_atr(frame)
    assert atr.index.equals(frame.index) and atr.iloc[-1] == atr.iloc[-1]  # last bar defined
    # Bar t's value uses bars up to t only, and is bar t's own (not t-1's): truncating
    # the history right after t leaves it unchanged.
    for t in (30, 55, 79):
        truncated = indicators.atr(frame.iloc[:t + 1].reset_index(drop=True), 14)
        assert atr.iloc[t] == pytest.approx(float(np.asarray(truncated)[-1]))


def test_an_unstated_default_never_contradicts_a_stated_bound():
    # "No more than 8% deep" / "at most 20 bars": the default floor (10%, 30 bars)
    # would make an empty range — it yields to the stated cap, disclosed.
    result = find_base_breakout_retest(
        spec(size=Size(normalisation="pct", max=8.0), duration=Duration(max_bars=20)),
        panel({"AAA": MATCH}))
    by_parameter = {r.parameter: r for r in result.rubric}
    assert ">= 4%" in by_parameter["base depth floor"].value
    assert "your 8% cap" in by_parameter["base depth floor"].detail
    assert ">= 10 bars" in by_parameter["base length floor"].value
    result = find_base_breakout_retest(spec(size=Size(normalisation="pct", min=50.0)),
                                       panel({"AAA": MATCH}))
    cap = next(r for r in result.rubric if r.parameter == "base depth cap")
    assert "<= 75%" in cap.value and "your 50% floor" in cap.detail


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
    (dict(duration=Duration(min_bars=40, max_bars=30)), "bounds are empty"),
    (dict(duration=Duration(min_bars=600)), "level search lookback"),
    (dict(duration=Duration(max_bars=1)), "at least 2 bars"),
    (dict(size=Size(normalisation="pct", min=99.5)), "no room"),
])
def test_refusals_name_the_problem(bad_spec, message):
    with pytest.raises(GroundingError, match=message):
        find_base_breakout_retest(spec(**bad_spec), panel({"AAA": MATCH}))


def test_missing_panel_column_and_unsorted_panel_are_refused():
    frame = panel({"AAA": MATCH})
    with pytest.raises(GroundingError, match="'low'"):
        find_base_breakout_retest(spec(), frame.drop(columns=["low"]))
    shuffled = frame.sample(frac=1.0, random_state=7).reset_index(drop=True)
    with pytest.raises(GroundingError, match="date-sorted"):
        find_base_breakout_retest(spec(), shuffled)

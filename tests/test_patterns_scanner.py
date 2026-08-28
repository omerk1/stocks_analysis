import numpy as np
import pandas as pd
import pytest

from src.data_processing import db
from src.market_common.models import Direction, Timeframe
from src.patterns.config import PatternConfig
from src.patterns.models import PatternMatch, PatternType
from src.patterns.scanner import dedupe_matches, detect, scan_bars


def _chain(*segments: tuple[float, float, int], start: str = "2020-01-01") -> pd.DataFrame:
    frames = []
    cursor = pd.Timestamp(start)
    for p0, p1, n in segments:
        idx = pd.bdate_range(cursor, periods=n)
        closes = np.linspace(p0, p1, n)
        frames.append(pd.DataFrame(
            {"open": closes, "high": closes + 0.3, "low": closes - 0.3, "close": closes, "volume": 1000.0},
            index=idx,
        ))
        cursor = idx[-1] + pd.Timedelta(days=1)
    return pd.concat(frames)


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, pivot_atr_mult=1.0, volume_sma_period=5, prior_trend_min_bars=5, prior_trend_min_pct=10.0,
        min_bars=0, double_top_typical_min_bars=1, double_top_typical_max_bars=200,
    )
    defaults.update(overrides)
    return PatternConfig(**defaults)


# Same shape as test_patterns_double_top_bottom's fixture, but pivots are
# recovered from real bars via market_common.pivots.detect_pivots rather
# than hand-built -- proves scan_bars' own pivot-extraction wiring, not
# just the detector's logic in isolation.
_DOUBLE_TOP_BARS = _chain((100.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 129.0, 5), (127.0, 100.0, 10))


def test_scan_bars_recovers_double_top_from_real_pivots():
    matches = scan_bars(_DOUBLE_TOP_BARS, "TST", Timeframe.DAILY, _config())

    tops = [m for m in matches if m.pattern_type == PatternType.DOUBLE_TOP]
    assert len(tops) == 1
    m = tops[0]
    assert m.key_levels["p1"] == pytest.approx(130.3)
    assert m.key_levels["neckline"] == pytest.approx(120.7)
    assert m.key_levels["p2"] == pytest.approx(129.3)


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    frame = _DOUBLE_TOP_BARS.reset_index().rename(columns={"index": "timestamp"})
    frame["is_partial"] = 0
    frame = frame.set_index("timestamp")
    db.upsert_bars(connection, "bars_1d", "TST", db.YFINANCE, frame)
    yield connection
    connection.close()


def test_detect_as_of_before_formation_end_excludes_the_pattern(conn):
    # The double top's p2 (bar 19) confirms 2020-01-29 (see
    # test_scan_bars_recovers_double_top_from_real_pivots for the same
    # fixture's pivot bar indices).
    matches, _report, skip = detect(conn, "TST", Timeframe.DAILY, _config(), as_of="2020-01-28")
    assert skip is None
    assert matches == []


def test_detect_as_of_after_formation_end_includes_the_pattern(conn):
    matches, _report, skip = detect(conn, "TST", Timeframe.DAILY, _config(), as_of="2020-01-29")
    assert skip is None
    tops = [m for m in matches if m.pattern_type == PatternType.DOUBLE_TOP]
    assert len(tops) == 1


def test_detect_skips_short_history(conn):
    config = _config(min_bars=10_000)
    matches, report, skip = detect(conn, "TST", Timeframe.DAILY, config)
    assert matches == []
    assert skip is not None
    assert report.rows_loaded == len(_DOUBLE_TOP_BARS)


def _dedupe_match(pattern_type, direction, first_bar, last_bar, confidence):
    from src.market_common.models import Pivot, PivotKind
    pivots = [
        Pivot(kind=PivotKind.HIGH, timestamp="2020-01-01", value=10.0, confirmed_at="2020-01-01",
              threshold_at_pivot=1.0, bar_index=first_bar),
        Pivot(kind=PivotKind.LOW, timestamp="2020-02-01", value=9.0, confirmed_at="2020-02-01",
              threshold_at_pivot=1.0, bar_index=last_bar),
    ]
    return PatternMatch(
        id=f"{pattern_type.value}-{first_bar}-{last_bar}", ticker="TST", timeframe=Timeframe.DAILY,
        pattern_type=pattern_type, direction=direction, pivots=pivots,
        confidence=confidence, formation_start="2020-01-01", formation_end="2020-02-01",
    )


def test_dedupe_keeps_only_the_best_of_several_left_rims_on_one_structure():
    # The real duplicate shape: one base, three plausible left rims, all
    # ending on the same terminal pivot (measured on real data as groups of
    # up to 6). Only the highest-confidence one should survive.
    matches = [
        _dedupe_match(PatternType.CUP_AND_HANDLE, Direction.BULLISH, 10, 100, 0.40),
        _dedupe_match(PatternType.CUP_AND_HANDLE, Direction.BULLISH, 20, 100, 0.70),
        _dedupe_match(PatternType.CUP_AND_HANDLE, Direction.BULLISH, 30, 100, 0.55),
    ]
    kept = dedupe_matches(matches)
    assert len(kept) == 1
    assert kept[0].confidence == 0.70


def test_dedupe_breaks_confidence_ties_toward_the_longer_formation():
    matches = [
        _dedupe_match(PatternType.CUP_AND_HANDLE, Direction.BULLISH, 60, 100, 0.50),
        _dedupe_match(PatternType.CUP_AND_HANDLE, Direction.BULLISH, 10, 100, 0.50),
    ]
    [kept] = dedupe_matches(matches)
    assert kept.pivots[0].bar_index == 10


def test_dedupe_never_merges_across_pattern_types():
    # §9's resolved overlap decision: the same swing points may legitimately
    # be several patterns at once, each with its own independent score.
    matches = [
        _dedupe_match(PatternType.SYMMETRIC_TRIANGLE, Direction.NEUTRAL, 10, 100, 0.60),
        _dedupe_match(PatternType.RISING_WEDGE, Direction.BEARISH, 10, 100, 0.40),
    ]
    assert len(dedupe_matches(matches)) == 2


def test_dedupe_keeps_distinct_structures_ending_on_different_pivots():
    matches = [
        _dedupe_match(PatternType.CUP_AND_HANDLE, Direction.BULLISH, 10, 100, 0.60),
        _dedupe_match(PatternType.CUP_AND_HANDLE, Direction.BULLISH, 10, 140, 0.30),
    ]
    assert len(dedupe_matches(matches)) == 2


def test_dedupe_preserves_input_order():
    matches = [
        _dedupe_match(PatternType.CUP_AND_HANDLE, Direction.BULLISH, 10, 200, 0.60),
        _dedupe_match(PatternType.VCP, Direction.BULLISH, 10, 100, 0.90),
    ]
    kept = dedupe_matches(matches)
    assert [m.pattern_type for m in kept] == [PatternType.CUP_AND_HANDLE, PatternType.VCP]


# --- Second dedup identity: same breakout_bar, sloped-trigger detectors --
#
# Sloped-trigger detectors (triangle/wedge/H&S) fit a trendline over the
# whole pivot window, not one fixed pivot -- so a window sliding by one
# pivot can resolve to the same real breakout while ending on a genuinely
# different terminal pivot, invisible to the terminal-pivot key above.
# Measured on real tickers (QUCY/REKR/MPU and others): these pairs share
# 4-5 of 6 pivots and the same breakout_bar.


def _dedupe_match_bo(pattern_type, direction, pivot_bars, breakout_bar, confidence):
    from src.market_common.models import Pivot, PivotKind
    pivots = [
        Pivot(kind=PivotKind.HIGH if i % 2 == 0 else PivotKind.LOW, timestamp="2020-01-01", value=10.0,
              confirmed_at="2020-01-01", threshold_at_pivot=1.0, bar_index=b)
        for i, b in enumerate(pivot_bars)
    ]
    return PatternMatch(
        id=f"{pattern_type.value}-{pivot_bars}-{breakout_bar}", ticker="TST", timeframe=Timeframe.DAILY,
        pattern_type=pattern_type, direction=direction, pivots=pivots, breakout_bar=breakout_bar,
        confidence=confidence, formation_start="2020-01-01", formation_end="2020-02-01",
    )


def test_dedupe_collapses_sliding_window_pair_sharing_a_breakout_bar():
    # Different terminal pivot (224 vs 225), same breakout_bar, 5 of 6
    # pivots shared -- the QUCY descending_triangle shape, verbatim.
    matches = [
        _dedupe_match_bo(PatternType.DESCENDING_TRIANGLE, Direction.BULLISH,
                         [82, 92, 154, 169, 221, 224], breakout_bar=238, confidence=0.732),
        _dedupe_match_bo(PatternType.DESCENDING_TRIANGLE, Direction.BULLISH,
                         [92, 154, 169, 221, 224, 225], breakout_bar=238, confidence=0.762),
    ]
    kept = dedupe_matches(matches)
    assert len(kept) == 1
    assert kept[0].confidence == 0.762


def test_dedupe_preserves_independent_matches_sharing_a_breakout_bar_by_coincidence():
    # Same pattern_type/direction/breakout_bar, but genuinely disjoint
    # pivot windows (the WOOF/APH double_top shape: two separate swings
    # that happen to trigger on the same calendar day). Overlap 1/5 = 0.2,
    # below the 0.5 gate -- must NOT be merged away.
    matches = [
        _dedupe_match_bo(PatternType.DOUBLE_TOP, Direction.BEARISH,
                         [45, 57, 74], breakout_bar=105, confidence=0.99),
        _dedupe_match_bo(PatternType.DOUBLE_TOP, Direction.BEARISH,
                         [74, 85, 88], breakout_bar=105, confidence=0.98),
    ]
    assert len(dedupe_matches(matches)) == 2


def test_dedupe_never_touches_a_match_that_never_broke_out():
    # breakout_bar=None means "never triggered" -- the second pass must
    # never fold it into a resolved match's group. Same pivots as the
    # resolved match (maximum possible overlap) is the adversarial case:
    # if overlap alone governed the merge, this is where it would happen.
    a = _dedupe_match_bo(PatternType.RISING_WEDGE, Direction.BEARISH,
                         [10, 20, 30, 40, 50, 61], breakout_bar=None, confidence=0.40)
    b = _dedupe_match_bo(PatternType.RISING_WEDGE, Direction.BEARISH,
                         [10, 20, 30, 40, 50, 60], breakout_bar=70, confidence=0.90)
    kept = dedupe_matches([a, b])
    assert len(kept) == 2
    assert {m.breakout_bar for m in kept} == {None, 70}


def test_dedupe_never_merges_across_different_breakout_bars():
    # Perfect pivot overlap (identical pivots) but different breakout_bar
    # values -- must NOT merge. The second pass partitions by exact
    # breakout_bar equality before it ever looks at overlap, so two
    # different real trading days can never collapse into one no matter
    # how similar their formations look.
    matches = [
        _dedupe_match_bo(PatternType.RISING_WEDGE, Direction.BEARISH,
                         [10, 20, 30, 40, 50, 61], breakout_bar=70, confidence=0.90),
        _dedupe_match_bo(PatternType.RISING_WEDGE, Direction.BEARISH,
                         [10, 20, 30, 40, 50, 60], breakout_bar=99, confidence=0.60),
    ]
    kept = dedupe_matches(matches)
    assert len(kept) == 2
    assert {m.breakout_bar for m in kept} == {70, 99}

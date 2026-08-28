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
        "left_rim": 140.0, "cup_extreme": 100.0, "right_rim": 140.0, "handle": 130.0,
        "neckline": 140.0, "neckline_bar": 64.0,
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


def test_rounding_bottom_confirmed_breakout_hits_target():
    # No handle pivot at all -- rim2 is the window's last pivot, the
    # "genuinely no second pullback" case §4.8 describes, not just an
    # invalid handle falling through.
    df = _cup_df(np.linspace(132.0, 200.0, 20))
    pivots = _cup_pivots(df)[:3]
    config = _config(rounding_typical_min_bars=1, rounding_typical_max_bars=200)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.ROUNDING_BOTTOM
    assert m.direction == Direction.BULLISH
    assert "handle" not in m.key_levels
    assert m.target_price == pytest.approx(180.0)
    assert m.stop_price == pytest.approx(100.0)
    assert m.breakout_bar == 72
    assert m.status == PatternStatus.HIT_TARGET


def test_rounding_top_mirrors_rounding_bottom():
    df = _inverse_cup_df(np.linspace(148.0, 80.0, 20))
    pivots = _inverse_cup_pivots(df)[:3]
    config = _config(rounding_typical_min_bars=1, rounding_typical_max_bars=200)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.ROUNDING_TOP
    assert m.direction == Direction.BEARISH
    assert m.target_price == pytest.approx(100.0)
    assert m.stop_price == pytest.approx(180.0)
    assert m.status == PatternStatus.HIT_TARGET


def _tilted_cup_df(right_rim: float, tail_closes: np.ndarray, start: str = "2020-01-01") -> pd.DataFrame:
    """A cup whose right rim lands at `right_rim` instead of back at the left
    rim's 140 -- a parabola plus a linear tilt, so the shape stays genuinely
    rounded (curvature, apex position and single-bar move all still pass) and
    the only thing under test is the rim divergence itself.

    Built into the *bars* rather than by overriding a pivot's price, because
    rim prices are read from the close now (see cup_and_handle._close_at): a
    pivot claiming 120 while its bar closes at 140 no longer describes a weak
    recovery, it just describes a wick.
    """
    uptrend = np.linspace(80.0, 140.0, 25)
    t = np.arange(41, dtype=float)
    tilt = (140.0 - right_rim) / 40.0
    cup = (0.1 * (t - 20) ** 2 + 100.0 - tilt * t)[1:]
    handle = np.linspace(right_rim - 2.0, right_rim - 10.0, 4)
    closes = np.concatenate([uptrend, cup, handle, tail_closes])
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes + 0.3, "low": closes - 0.3, "close": closes, "volume": 1000.0}, index=idx,
    )


def test_rim_divergence_gate_rejects_weak_recovery():
    # Right rim recovers only to 120 against a 140 left rim -- 14.3% apart,
    # past the 10% bound.
    df = _tilted_cup_df(120.0, np.linspace(122.0, 200.0, 20))
    pivots = _cup_pivots(df)
    pivots[2] = _pivot(64, float(df["close"].iloc[64]), PivotKind.HIGH, df)
    pivots[3] = _pivot(68, float(df["close"].iloc[68]), PivotKind.LOW, df)

    assert CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, _config()) == []


def test_rim_divergence_gate_is_what_rejects_it_and_nothing_else():
    # Same bars, rim bound widened past 14.3% -- the candidate comes back,
    # proving the rejection above is the rim gate and not some other gate
    # the tilted fixture happens to trip.
    df = _tilted_cup_df(120.0, np.linspace(122.0, 200.0, 20))
    pivots = _cup_pivots(df)
    pivots[2] = _pivot(64, float(df["close"].iloc[64]), PivotKind.HIGH, df)
    pivots[3] = _pivot(68, float(df["close"].iloc[68]), PivotKind.LOW, df)

    matches = CupAndHandleDetector().scan(
        df, pivots, "TST", Timeframe.DAILY, _config(cup_rim_divergence_max_pct=20.0)
    )
    assert len(matches) == 1


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


def test_handle_below_cup_midpoint_falls_through_to_rounding():
    # midpoint=(140+100)/2=120; a handle closing at 110 sits in the lower
    # half -- not a valid handle, so this falls through to a Rounding Bottom
    # match (every other gate still passes) instead of no match at all.
    # The 110 goes into the bars, not just the pivot: the handle price is
    # read from the close now (cup_and_handle._close_at).
    df = _cup_df(np.concatenate([[110.0], np.linspace(132.0, 200.0, 19)]))
    df.iloc[68, df.columns.get_loc("close")] = 110.0
    df.iloc[68, df.columns.get_loc("open")] = 110.0
    df.iloc[68, df.columns.get_loc("high")] = 110.3
    df.iloc[68, df.columns.get_loc("low")] = 109.7
    pivots = _cup_pivots(df)
    pivots[3] = _pivot(68, 110.0, PivotKind.LOW, df)
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].pattern_type == PatternType.ROUNDING_BOTTOM
    assert "handle" not in matches[0].key_levels


def test_handle_retrace_gate_falls_through_to_rounding_when_configured_tighter_than_actual():
    # The fixture's real handle retrace is 25% of the cup's advance --
    # disqualified as a handle here, so this falls through to Rounding.
    df = _cup_df(np.linspace(132.0, 200.0, 20))
    pivots = _cup_pivots(df)
    config = _config(cup_handle_max_retrace_pct=10.0)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].pattern_type == PatternType.ROUNDING_BOTTOM


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


def _scan(df, config=None):
    from src.market_common.pivots import detect_pivots
    from src.market_common import indicators
    config = config or _config()
    atr = indicators.atr(df, config.atr_period)
    pivots = detect_pivots(df["high"], df["low"], threshold_fn=lambda i: config.pivot_atr_mult * atr.iloc[i])
    return CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)


def test_rim_divergence_is_bounded_on_the_high_side_too():
    # The bug this replaced: the old one-sided gate only rejected a right
    # rim that fell *short* of the left rim, so for a cup an arbitrarily
    # higher right rim passed -- and mirrored onto the inverse variants that
    # became "arbitrarily far below," which drove measured-move targets
    # through zero. A right rim 40% above the left rim is not a cup rim.
    t = np.arange(41, dtype=float)
    uptrend = np.linspace(80.0, 140.0, 25)
    cup = (0.1 * (t - 20) ** 2 + 100.0)[1:]
    cup = cup + np.linspace(0.0, 56.0, len(cup))          # right rim ~196 vs left 140
    closes = np.concatenate([uptrend, cup, np.linspace(190.0, 185.0, 4), np.full(20, 185.0)])
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    df = pd.DataFrame({"open": closes, "high": closes + 0.3, "low": closes - 0.3,
                       "close": closes, "volume": 1000.0}, index=idx)
    assert [m for m in _scan(df) if m.pattern_type == PatternType.CUP_AND_HANDLE] == []


def test_no_cup_family_match_ever_gets_a_non_positive_target():
    # The observable symptom of the rim bug: 16.3% of bearish matches had a
    # target price at or below zero, unreachable by construction.
    for df in (_cup_df(np.full(20, 145.0)), _inverse_cup_df(np.full(20, 135.0))):
        for match in _scan(df):
            assert match.target_price > 0


def test_v_shaped_recovery_with_a_one_bar_cliff_is_rejected():
    # A near-vertical run-up then a single-bar collapse. Its quadratic R2
    # passes the roundedness threshold comfortably -- the single-bar-move
    # gate is what rejects it.
    uptrend = np.linspace(80.0, 140.0, 25)
    v_up = np.linspace(140.0, 200.0, 20)
    cliff = np.array([141.0])
    closes = np.concatenate([uptrend, v_up, cliff, np.full(20, 141.0)])
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    df = pd.DataFrame({"open": closes, "high": closes + 0.3, "low": closes - 0.3,
                       "close": closes, "volume": 1000.0}, index=idx)
    assert [m for m in _scan(df) if m.pattern_type in
            (PatternType.INVERSE_CUP_AND_HANDLE, PatternType.ROUNDING_TOP)] == []


def test_monotone_leg_between_rims_is_rejected_despite_high_r2():
    # A straight decline fits a parabola arm with R2 > 0.99, so the
    # roundedness threshold waves it through; the apex-position gate is what
    # catches it (the vertex lands outside the rim-to-rim window).
    config = _config()
    t = np.arange(41, dtype=float)
    fit_input = (0.1 * (t - 60) ** 2)                      # vertex well past the window end
    uptrend = np.linspace(80.0, 140.0, 25)
    closes = np.concatenate([uptrend, 140.0 - fit_input * 0.05, np.full(20, 100.0)])
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    df = pd.DataFrame({"open": closes, "high": closes + 0.3, "low": closes - 0.3,
                       "close": closes, "volume": 1000.0}, index=idx)
    for match in _scan(df, config):
        assert match.pattern_type not in (PatternType.CUP_AND_HANDLE, PatternType.ROUNDING_BOTTOM)


# --- Rounding's near-rim breakout gate -------------------------------------
#
# Rounding is the one pattern whose formation ends on the very pivot that
# supplies its trigger level (rim2), so without a gap the breakout scan
# starts one bar after the level was defined -- and since the level is
# rim2's CLOSE while rim2 itself is a wick, price can re-close through it
# within a bar or two without the swing high ever being touched. Measured
# over 1,100 tickers, that slice was >half of all rounding matches and
# carried the entire return deficit. Cup & Handle is structurally immune
# (its handle pushes formation end past rim2) and must stay ungated.


def test_rounding_ignores_a_break_too_close_to_the_right_rim():
    # Bar 69 (5 bars past rim2@64, inside the default 6-bar gate) closes
    # well above the 140 rim, then price falls back. The real breakout is
    # bar 75. The near-rim bar must be ignored, NOT taken as the breakout.
    tail = np.concatenate([
        np.array([145.0, 138.0, 136.0, 134.0, 136.0, 138.0]),  # bars 69-74
        np.linspace(142.8, 200.0, 14),                          # bars 75+
    ])
    df = _cup_df(tail)
    pivots = _cup_pivots(df)[:3]
    config = _config(rounding_typical_min_bars=1, rounding_typical_max_bars=200)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.ROUNDING_BOTTOM
    # 69 would be the breakout without the gate; 75 is the first break at
    # or beyond rim2 + 6.
    assert m.breakout_bar == 75


def test_cup_and_handle_still_takes_a_break_the_rounding_gate_would_suppress():
    # Control for the test above: the SAME near-rim break at bar 69, but
    # with a valid handle pivot so this is a Cup & Handle. The gate is
    # rounding-only, so bar 69 must still be the breakout here. This is
    # what proves the fix is scoped to the rounding branch rather than
    # applied to the shared _build_match path.
    tail = np.concatenate([
        np.array([145.0, 138.0, 136.0, 134.0, 136.0, 138.0]),
        np.linspace(142.8, 200.0, 14),
    ])
    df = _cup_df(tail)
    pivots = _cup_pivots(df)  # all four -- includes the handle @68
    config = _config()

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.CUP_AND_HANDLE
    assert m.breakout_bar == 69


def test_rounding_gate_boundary_accepts_a_break_exactly_at_the_gap():
    # Exactly rim2 + 6 is accepted (>=, not >). Bars 69-69+4 stay below the
    # rim so bar 70 is the first candidate break, at a gap of 6.
    tail = np.concatenate([
        np.array([138.0]),               # bar 69, gap 5, below the rim
        np.linspace(142.8, 200.0, 19),   # bar 70 onwards, gap 6+
    ])
    df = _cup_df(tail)
    pivots = _cup_pivots(df)[:3]
    config = _config(rounding_typical_min_bars=1, rounding_typical_max_bars=200)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert matches[0].breakout_bar == 70
    assert matches[0].breakout_bar - 64 == config.rounding_breakout_min_gap_bars


def test_rounding_gate_suppresses_the_breakout_test_only_not_invalidation():
    # A base that breaks below its own floor while we're waiting out the
    # gap is dead regardless of why we were waiting. Bar 69 is a suppressed
    # break; bar 70 collapses under the 100 cup floor. The suppression must
    # not rescue it into a later breakout.
    tail = np.concatenate([
        np.array([145.0, 95.0]),         # 69: suppressed break. 70: floor gone.
        np.linspace(142.8, 200.0, 18),
    ])
    df = _cup_df(tail)
    pivots = _cup_pivots(df)[:3]
    config = _config(rounding_typical_min_bars=1, rounding_typical_max_bars=200)

    matches = CupAndHandleDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.status == PatternStatus.INVALIDATED
    assert m.breakout_bar is None

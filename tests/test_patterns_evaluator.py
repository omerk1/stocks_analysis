import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.market_common.models import Direction, Timeframe
from src.signals.patterns.backtest import evaluator
from src.signals.patterns.backtest.evaluator import (
    PatternOutcome,
    compute_outcomes,
    forward_return_pct,
    had_throwback,
    run_backtest,
    summarize,
)
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.models import PatternMatch, PatternStatus, PatternType


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


def _match(pattern_type=PatternType.DOUBLE_TOP, direction=Direction.BEARISH,
           status=PatternStatus.HIT_TARGET, breakout_bar=10, entry_price=100.0,
           target_price=None, key_levels=None, trendlines=None) -> PatternMatch:
    return PatternMatch(
        id=f"m-{breakout_bar}-{status.value}", ticker="TST", timeframe=Timeframe.DAILY,
        pattern_type=pattern_type, direction=direction, pivots=[],
        status=status, breakout_bar=breakout_bar, entry_price=entry_price, target_price=target_price,
        key_levels=key_levels or {}, trendlines=trendlines or {},
    )


# Flat except a single known move so forward_return_pct's arithmetic is
# exact and easy to hand-verify: close is 100.0 through bar 10 (the
# breakout bar), then jumps to 90.0 for every later bar.
_STEP_BARS = pd.DataFrame({"close": [100.0] * 11 + [90.0] * 5})


def test_forward_return_pct_bullish_is_raw_price_return():
    match = _match(direction=Direction.BULLISH, breakout_bar=10, entry_price=100.0)
    assert forward_return_pct(_STEP_BARS, match, 3) == pytest.approx(-0.10)


def test_forward_return_pct_bearish_is_negated_so_a_price_drop_is_a_positive_return():
    match = _match(direction=Direction.BEARISH, breakout_bar=10, entry_price=100.0)
    assert forward_return_pct(_STEP_BARS, match, 3) == pytest.approx(0.10)


def test_forward_return_pct_none_when_horizon_exceeds_available_bars():
    match = _match(breakout_bar=10, entry_price=100.0)
    assert forward_return_pct(_STEP_BARS, match, 999) is None


def test_compute_outcomes_skips_matches_that_never_broke_out():
    never_broke = [
        _match(status=PatternStatus.PENDING, breakout_bar=None),
        _match(status=PatternStatus.INVALIDATED, breakout_bar=None),
        _match(status=PatternStatus.EXPIRED, breakout_bar=None),
    ]
    broke_out = _match(status=PatternStatus.HIT_TARGET, breakout_bar=10, entry_price=100.0)

    outcomes = compute_outcomes(never_broke + [broke_out], _STEP_BARS, horizons=(3,))
    assert len(outcomes) == 1
    assert outcomes[0].match_id == broke_out.id
    assert outcomes[0].forward_returns == {3: pytest.approx(0.10)}


# Bars from breakout_bar (10) onward only -- prior bars are irrelevant to
# _find_target_hit_bar/had_throwback, which only ever look forward from
# breakout_bar. Bearish match: entry_price=100.0, target_price=90.0.
def _bearish_bars(*closes_from_breakout: float) -> pd.DataFrame:
    closes = [100.0] * 11 + list(closes_from_breakout)  # index 10 == breakout_bar
    df = pd.DataFrame({"close": closes})
    df["high"] = df["close"] + 0.3
    df["low"] = df["close"] - 0.3
    return df


def test_compute_outcomes_throwback_true_when_price_closes_back_through_entry_before_target():
    # bar11=95 (past entry, no throwback yet), bar12=100 (closes back
    # through entry_price -- throwback), bar13=89 (low 88.7 <= target 90).
    bars = _bearish_bars(95.0, 100.0, 89.0)
    match = _match(direction=Direction.BEARISH, status=PatternStatus.HIT_TARGET,
                    breakout_bar=10, entry_price=100.0, target_price=90.0)

    [outcome] = compute_outcomes([match], bars, horizons=())
    assert outcome.target_hit_bar == 13
    assert outcome.throwback is True


def test_compute_outcomes_throwback_false_when_price_never_revisits_entry():
    # Monotonic fall straight to target -- never closes back >= entry_price.
    bars = _bearish_bars(95.0, 92.0, 89.0)
    match = _match(direction=Direction.BEARISH, status=PatternStatus.HIT_TARGET,
                    breakout_bar=10, entry_price=100.0, target_price=90.0)

    [outcome] = compute_outcomes([match], bars, horizons=())
    assert outcome.target_hit_bar == 13
    assert outcome.throwback is False


def test_compute_outcomes_target_hit_bar_and_throwback_none_when_not_hit_target():
    bars = _bearish_bars(95.0, 92.0, 89.0)
    match = _match(direction=Direction.BEARISH, status=PatternStatus.ACTIVE,
                    breakout_bar=10, entry_price=100.0, target_price=90.0)

    [outcome] = compute_outcomes([match], bars, horizons=())
    assert outcome.target_hit_bar is None
    assert outcome.throwback is None


def test_had_throwback_bullish_direction_checks_close_dropping_back_through_entry():
    # Bullish: entry_price=100.0. bar11=105 (clear of entry, no throwback),
    # bar12=99 (closes back through entry from above -- throwback), bar13
    # is just a filler bar so target_hit_bar=13 can include bar12 in the
    # (breakout_bar, target_hit_bar) exclusive-end scan window.
    bars = pd.DataFrame({"close": [100.0] * 11 + [105.0, 99.0, 99.0]})
    match = _match(direction=Direction.BULLISH, breakout_bar=10, entry_price=100.0)

    assert had_throwback(bars, match, target_hit_bar=13) is True
    assert had_throwback(bars, match, target_hit_bar=12) is False  # window ends before the throwback bar


def test_had_throwback_flat_pattern_uses_key_levels_neckline_not_entry_price():
    # neckline (100) sits above entry_price (95), as it must for a
    # confirmed bearish breakout -- bar11 (97) lands strictly between the
    # two, so the real neckline-based check and the entry_price fallback
    # disagree (97 < neckline, but 97 >= entry_price). A False result here
    # proves key_levels["neckline"] is what's actually being used.
    bars = pd.DataFrame({"close": [95.0] * 11 + [97.0]})
    match = _match(
        pattern_type=PatternType.DOUBLE_TOP, direction=Direction.BEARISH,
        breakout_bar=10, entry_price=95.0, key_levels={"neckline": 100.0},
    )
    assert had_throwback(bars, match, target_hit_bar=12) is False


def test_had_throwback_sloped_fixed_pattern_uses_trendline_not_entry_price():
    # neckline_at(i) = i + 90 -- at breakout (bar 10) it's 100, matching
    # entry_price, but by bar11 it's already risen to 101. bar11's close
    # of 100.5 is below neckline_at(11) (no throwback) but >= entry_price
    # (100) -- the two checks disagree, proving the sloped H&S trendline
    # is what's actually being used, not the frozen entry_price.
    bars = pd.DataFrame({"close": [100.0] * 11 + [100.5]})
    match = _match(
        pattern_type=PatternType.HEAD_AND_SHOULDERS, direction=Direction.BEARISH,
        breakout_bar=10, entry_price=100.0, trendlines={"neckline": (1.0, 90.0)},
    )
    assert had_throwback(bars, match, target_hit_bar=12) is False


def test_had_throwback_directional_pattern_picks_upper_trendline_for_bullish():
    # upper_at(11)=111, lower_at(11)=50 -- deliberately far apart so a
    # close of 105 gives opposite verdicts depending on which trendline
    # got picked (<=111 is a throwback, <=50 is not), proving "upper" is
    # actually selected for a BULLISH-resolved triangle/wedge/flag.
    bars = pd.DataFrame({"close": [100.0] * 11 + [105.0]})
    match = _match(
        pattern_type=PatternType.ASCENDING_TRIANGLE, direction=Direction.BULLISH,
        breakout_bar=10, entry_price=110.0,
        trendlines={"upper": (1.0, 100.0), "lower": (0.0, 50.0)},
    )
    assert had_throwback(bars, match, target_hit_bar=12) is True


def test_had_throwback_directional_pattern_picks_lower_trendline_for_bearish():
    # lower_at(11)=49, upper_at(11)=200 -- a close of 55 gives opposite
    # verdicts depending on which trendline got picked (>=49 is a
    # throwback, >=200 is not), proving "lower" is actually selected for
    # a BEARISH-resolved triangle/wedge/flag.
    bars = pd.DataFrame({"close": [100.0] * 11 + [55.0]})
    match = _match(
        pattern_type=PatternType.DESCENDING_TRIANGLE, direction=Direction.BEARISH,
        breakout_bar=10, entry_price=40.0,
        trendlines={"upper": (0.0, 200.0), "lower": (-1.0, 60.0)},
    )
    assert had_throwback(bars, match, target_hit_bar=12) is True


def test_had_throwback_falls_back_to_entry_price_when_trendline_missing():
    # Same bars/pattern_type as the sloped-fixed test above, but without
    # populating trendlines["neckline"] -- _reconstruct_trigger_at can't
    # find the data, so had_throwback should fall back to entry_price
    # (100.5 >= entry_price(100) -> True) rather than raise or silently
    # treat it as "no trigger level at all".
    bars = pd.DataFrame({"close": [100.0] * 11 + [100.5]})
    match = _match(
        pattern_type=PatternType.HEAD_AND_SHOULDERS, direction=Direction.BEARISH,
        breakout_bar=10, entry_price=100.0, trendlines={},
    )
    assert had_throwback(bars, match, target_hit_bar=12) is True


def test_summarize_computes_rates_and_mean_returns_per_pattern_type():
    outcomes = [
        PatternOutcome("a", "T", "double_top", "bearish", "hit_target", 10, {5: 0.10, 999: None},
                        target_hit_bar=15, throwback=True),
        PatternOutcome("b", "T", "double_top", "bearish", "invalidated_failed_breakout", 12, {5: -0.05, 999: None}),
        PatternOutcome("c", "T", "double_top", "bearish", "active", 14, {5: None, 999: None}),
        PatternOutcome("d", "T", "vcp", "bullish", "hit_target", 20, {5: 0.20, 999: None},
                        target_hit_bar=25, throwback=False),
    ]
    result = summarize(outcomes, horizons=(5, 999))

    assert result.loc["double_top", "n"] == 3
    assert result.loc["double_top", "hit_target_rate"] == pytest.approx(1 / 3)
    assert result.loc["double_top", "failed_breakout_rate"] == pytest.approx(1 / 3)
    assert result.loc["double_top", "still_open_rate"] == pytest.approx(1 / 3)
    assert result.loc["double_top", "throwback_rate"] == pytest.approx(1.0)  # 1 of 1 hit_target had a throwback
    assert result.loc["double_top", "mean_return_5b"] == pytest.approx((0.10 - 0.05) / 2)
    assert result.loc["double_top", "n_resolved_5b"] == 2
    assert result.loc["double_top", "mean_return_999b"] is None
    assert result.loc["double_top", "n_resolved_999b"] == 0

    assert result.loc["vcp", "n"] == 1
    assert result.loc["vcp", "hit_target_rate"] == pytest.approx(1.0)
    assert result.loc["vcp", "throwback_rate"] == pytest.approx(0.0)


def test_summarize_throwback_rate_none_when_no_matches_hit_target():
    outcomes = [
        PatternOutcome("a", "T", "double_top", "bearish", "invalidated_failed_breakout", 12, {}),
    ]
    result = summarize(outcomes, horizons=())
    assert result.loc["double_top", "throwback_rate"] is None


def test_summarize_throwback_rate_excludes_hit_target_outcomes_with_unresolved_throwback():
    # Regression: a HIT_TARGET outcome whose throwback couldn't be
    # determined (target_hit_bar/throwback both None -- the defensive
    # branch in _find_target_hit_bar) must be excluded from *both* sides
    # of the ratio. Counting it in the denominator (via n_hit_target)
    # while excluding it from the numerator would silently deflate
    # throwback_rate as if the unresolved case were "no throwback".
    outcomes = [
        PatternOutcome("a", "T", "double_top", "bearish", "hit_target", 10, {},
                        target_hit_bar=15, throwback=True),
        PatternOutcome("b", "T", "double_top", "bearish", "hit_target", 12, {},
                        target_hit_bar=None, throwback=None),
    ]
    result = summarize(outcomes, horizons=())
    assert result.loc["double_top", "n"] == 2
    assert result.loc["double_top", "hit_target_rate"] == pytest.approx(1.0)  # both count as hit_target
    assert result.loc["double_top", "throwback_rate"] == pytest.approx(1.0)  # but only 1 of 1 *resolved* cases


def test_summarize_empty_outcomes_returns_empty_dataframe():
    result = summarize([])
    assert result.empty


# Same fixture test_patterns_scanner.py's own double-top tests use --
# proven (there) to detect exactly one double_top that breaks out at bar
# 23 (entry 118.0) and hits its target by the end of the 30-bar frame.
_DOUBLE_TOP_BARS = _chain((100.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 129.0, 5), (127.0, 100.0, 10))


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, pivot_atr_mult=1.0, volume_sma_period=5, prior_trend_min_bars=5, prior_trend_min_pct=10.0,
        min_bars=0, double_top_typical_min_bars=1, double_top_typical_max_bars=200,
    )
    defaults.update(overrides)
    return PatternConfig(**defaults)


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


def test_run_backtest_end_to_end_against_real_double_top_fixture(conn):
    # bar 23 (breakout) + 5 == bar 28, within the 30-bar frame -- resolved.
    # bar 23 + 10 == bar 33, past the end -- right-censored (None).
    summary = run_backtest(conn, ["TST"], Timeframe.DAILY, _config(), horizons=(5, 10))

    assert "double_top" in summary.index
    row = summary.loc["double_top"]
    assert row["n"] == 1
    assert row["hit_target_rate"] == pytest.approx(1.0)
    assert row["n_resolved_5b"] == 1
    assert row["mean_return_5b"] == pytest.approx((118.0 - 103.0) / 118.0)  # bearish: price fall is a positive return
    assert row["n_resolved_10b"] == 0
    assert row["mean_return_10b"] is None


def test_run_backtest_skips_ticker_below_min_bars(conn):
    summary = run_backtest(conn, ["TST"], Timeframe.DAILY, _config(min_bars=10_000))
    assert summary.empty


def test_run_backtest_continues_past_a_ticker_that_raises(conn, monkeypatch, capsys):
    # Regression: one bad ticker used to abort the whole run (no
    # try/except around the per-ticker loop body), silently discarding
    # every other ticker's already-computed outcomes too -- confirmed to
    # crash with ValueError against the pre-fix code before adding this.
    real_load = evaluator.data_mod.load_and_validate

    def flaky_load(conn_, ticker, timeframe):
        if ticker == "BAD":
            raise ValueError("simulated data error")
        return real_load(conn_, ticker, timeframe)

    monkeypatch.setattr(evaluator.data_mod, "load_and_validate", flaky_load)

    summary = run_backtest(conn, ["BAD", "TST"], Timeframe.DAILY, _config())

    assert "double_top" in summary.index  # TST's outcome survived BAD's failure
    assert "BAD" in capsys.readouterr().out


def _ret_outcome(pattern_type: str, r: float) -> PatternOutcome:
    return PatternOutcome(
        match_id=f"m{r}", ticker="TST", pattern_type=pattern_type, direction="bullish",
        status=PatternStatus.HIT_TARGET.value, breakout_bar=1, forward_returns={5: r},
    )


def test_summarize_reports_median_and_winsorized_mean_beside_the_raw_mean():
    # The falling_wedge shape in miniature: 99 small losses and one enormous
    # winner. The raw mean is positive purely because of that one outcome;
    # the median and the winsorized mean both report the loss that a typical
    # instance actually delivered.
    outcomes = [_ret_outcome("falling_wedge", -0.02) for _ in range(99)]
    outcomes.append(_ret_outcome("falling_wedge", 30.0))
    row = summarize(outcomes, horizons=(5,)).loc["falling_wedge"]

    assert row["mean_return_5b"] > 0
    assert row["median_return_5b"] == pytest.approx(-0.02)
    assert row["wins_return_5b"] < 0
    # Winsorizing caps, it does not discard -- n_resolved stays the true
    # sample size, unlike a trimmed mean.
    assert row["n_resolved_5b"] == 100


def test_summarize_winsorized_mean_equals_plain_mean_without_outliers():
    outcomes = [_ret_outcome("vcp", r) for r in (0.01, 0.02, 0.03, 0.04, 0.05)]
    row = summarize(outcomes, horizons=(5,)).loc["vcp"]

    assert row["wins_return_5b"] == pytest.approx(row["mean_return_5b"], abs=1e-9)
    assert row["median_return_5b"] == pytest.approx(0.03)


def test_summarize_return_stats_all_none_for_an_unresolved_horizon():
    outcomes = [
        PatternOutcome(
            match_id="m1", ticker="TST", pattern_type="vcp", direction="bullish",
            status=PatternStatus.HIT_TARGET.value, breakout_bar=1, forward_returns={5: None},
        )
    ]
    row = summarize(outcomes, horizons=(5,)).loc["vcp"]

    assert row["mean_return_5b"] is None
    assert row["median_return_5b"] is None
    assert row["wins_return_5b"] is None
    assert row["n_resolved_5b"] == 0


def test_summarize_empty_frame_carries_the_new_return_columns():
    cols = summarize([], horizons=(10,)).columns
    for name in ("mean_return_10b", "median_return_10b", "wins_return_10b", "n_resolved_10b"):
        assert name in cols

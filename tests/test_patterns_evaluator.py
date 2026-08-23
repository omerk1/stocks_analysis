import numpy as np
import pandas as pd
import pytest

from src.data_processing import db
from src.market_common.models import Direction, Timeframe
from src.patterns.backtest.evaluator import (
    PatternOutcome,
    compute_outcomes,
    forward_return_pct,
    run_backtest,
    summarize,
)
from src.patterns.config import PatternConfig
from src.patterns.models import PatternMatch, PatternStatus, PatternType


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
           status=PatternStatus.HIT_TARGET, breakout_bar=10, entry_price=100.0) -> PatternMatch:
    return PatternMatch(
        id=f"m-{breakout_bar}-{status.value}", ticker="TST", timeframe=Timeframe.DAILY,
        pattern_type=pattern_type, direction=direction, pivots=[],
        status=status, breakout_bar=breakout_bar, entry_price=entry_price,
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


def test_summarize_computes_rates_and_mean_returns_per_pattern_type():
    outcomes = [
        PatternOutcome("a", "T", "double_top", "bearish", "hit_target", 10, {5: 0.10, 999: None}),
        PatternOutcome("b", "T", "double_top", "bearish", "invalidated_failed_breakout", 12, {5: -0.05, 999: None}),
        PatternOutcome("c", "T", "double_top", "bearish", "active", 14, {5: None, 999: None}),
        PatternOutcome("d", "T", "vcp", "bullish", "hit_target", 20, {5: 0.20, 999: None}),
    ]
    result = summarize(outcomes, horizons=(5, 999))

    assert result.loc["double_top", "n"] == 3
    assert result.loc["double_top", "hit_target_rate"] == pytest.approx(1 / 3)
    assert result.loc["double_top", "failed_breakout_rate"] == pytest.approx(1 / 3)
    assert result.loc["double_top", "still_open_rate"] == pytest.approx(1 / 3)
    assert result.loc["double_top", "mean_return_5b"] == pytest.approx((0.10 - 0.05) / 2)
    assert result.loc["double_top", "n_resolved_5b"] == 2
    assert result.loc["double_top", "mean_return_999b"] is None
    assert result.loc["double_top", "n_resolved_999b"] == 0

    assert result.loc["vcp", "n"] == 1
    assert result.loc["vcp", "hit_target_rate"] == pytest.approx(1.0)


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

import pandas as pd
import pytest

from src.data_processing import db
from src.divergences.config import DivergenceConfig
from src.divergences.detect import detect, detect_for_indicator
from src.divergences.models import Direction, IndicatorKind
from src.divergences.store import create_divergences_table, upsert_divergences
from src.market_common import derived_db
from src.market_common.models import Timeframe


def _bars(closes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    """Flat +/-0.5 wick around each close -- ATR stays small and predictable
    relative to the large, deliberate swings these fixtures use, so pivot
    confirmation isn't sensitive to exact ATR internals."""
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=idx,
    )


def _series(values: list[float], like: pd.DataFrame) -> pd.Series:
    return pd.Series(values, index=like.index)


def _config(**overrides) -> DivergenceConfig:
    # warmup_bars=0/atr_period=3/min_bars=0 by default here -- the repo's
    # own ATR/RSI warmup floors are overkill for these short, hand-built
    # fixtures; every test below sets warmup_bars=5 explicitly (matching
    # atr_period=3's own short NaN warmup) via the caller's overrides.
    cfg = DivergenceConfig(atr_period=3, min_bars=0, warmup_bars=5, min_pivot_span_bars=5)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


# Two clean HIGH price swings (120 then 130, both bar_index-aligned with an
# indicator HIGH at the same bar) -- the base fixture for tests 1, 3, 4, 5, 8.
_HIGH_CLOSES = [100, 101, 102, 103, 104, 105, 120, 115, 110, 105, 100, 95, 90, 100, 110, 120, 130, 125, 115, 105, 95, 90, 85, 80]
# RSI-like series with strictly DECREASING paired highs (80 -> 70) at the
# exact same bar_index as the price highs above (verified empirically:
# detect_pivots on this array confirms HIGH pivots at bar_index 1 and 11).
_DECREASING_RSI = [50, 52, 55, 58, 60, 65, 80, 75, 65, 55, 45, 35, 30, 40, 55, 65, 70, 60, 50, 40, 35, 30, 28, 25]


def test_two_highs_strictly_decreasing_rsi_yields_one_bearish_divergence():
    bars = _bars(_HIGH_CLOSES)
    rsi = _series(_DECREASING_RSI, bars)
    config = _config(indicators=["rsi"], rsi_reversal_points=5.0, pairing_window=3)

    divs = detect_for_indicator(bars, "rsi", rsi, config, "TST", Timeframe.DAILY)

    assert len(divs) == 1
    d = divs[0]
    assert d.direction == Direction.BEARISH
    assert d.indicator == IndicatorKind.RSI
    assert (d.p1_price, d.p2_price) == (120.0, 130.0)
    assert (d.i1_value, d.i2_value) == (80.0, 70.0)
    assert 0.0 < d.strength <= 1.0


def test_two_lows_strictly_increasing_rsi_yields_one_bullish_divergence():
    # Mirror of the HIGH fixture (200 - price, 100 - rsi) -- a monotonic
    # decreasing map turns every HIGH into a LOW and flips the RSI
    # direction, giving a lower-low price / higher-low RSI bullish setup.
    low_closes = [200 - c for c in _HIGH_CLOSES]
    low_rsi = [100 - v for v in _DECREASING_RSI]
    bars = _bars(low_closes)
    rsi = _series(low_rsi, bars)
    config = _config(indicators=["rsi"], rsi_reversal_points=5.0, pairing_window=3)

    divs = detect_for_indicator(bars, "rsi", rsi, config, "TST", Timeframe.DAILY)

    assert len(divs) == 1
    d = divs[0]
    assert d.direction == Direction.BULLISH
    assert (d.p1_price, d.p2_price) == (80.0, 70.0)
    assert (d.i1_value, d.i2_value) == (20.0, 30.0)


def test_unpaired_second_price_pivot_is_silently_ignored():
    # Indicator confirms a HIGH near the first price pivot but then just
    # keeps rising for the rest of the series (no second HIGH pivot ever
    # confirms) -- the second price pivot (bar_index 11) has no indicator
    # pivot within pairing_window at all, so the pair must be dropped, not
    # partially evaluated against a stale/missing match.
    no_second_peak_rsi = [50, 52, 55, 58, 60, 65, 80, 75, 65, 55, 45, 35, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85]
    bars = _bars(_HIGH_CLOSES)
    rsi = _series(no_second_peak_rsi, bars)
    config = _config(indicators=["rsi"], rsi_reversal_points=5.0, pairing_window=3)

    divs = detect_for_indicator(bars, "rsi", rsi, config, "TST", Timeframe.DAILY)

    assert divs == []


def test_indicator_moving_same_direction_as_price_yields_no_divergence():
    # Indicator's paired highs also rise (65 -> 75, same as price's
    # 120 -> 130) -- pairing succeeds on both sides, but the bearish
    # condition (indicator strictly DECREASING) is never met.
    same_direction_rsi = [50, 52, 55, 58, 60, 65, 60, 55, 45, 35, 25, 15, 10, 20, 35, 50, 75, 65, 55, 45, 35, 30, 28, 25]
    bars = _bars(_HIGH_CLOSES)
    rsi = _series(same_direction_rsi, bars)
    config = _config(indicators=["rsi"], rsi_reversal_points=5.0, pairing_window=3)

    divs = detect_for_indicator(bars, "rsi", rsi, config, "TST", Timeframe.DAILY)

    assert divs == []


def test_span_below_minimum_discards_an_otherwise_qualifying_pair():
    bars = _bars(_HIGH_CLOSES)
    rsi = _series(_DECREASING_RSI, bars)
    # The two price pivots (bar_index 1 and 11) are 10 bars apart -- a
    # min_pivot_span_bars above that discards the pair even though the
    # price/indicator pattern is identical to the passing test above.
    config = _config(indicators=["rsi"], rsi_reversal_points=5.0, pairing_window=3, min_pivot_span_bars=20)

    divs = detect_for_indicator(bars, "rsi", rsi, config, "TST", Timeframe.DAILY)

    assert divs == []


def test_chained_triple_high_pivots_produce_two_separate_divergence_rows():
    closes = [
        100, 101, 102, 103, 104, 105, 120, 115, 110, 105, 100, 95, 90, 100, 110, 120, 130,
        125, 115, 105, 95, 90, 85, 80, 90, 100, 110, 140, 130, 120, 110, 100, 95, 90, 85, 80,
    ]
    rsi_values = [
        50, 52, 55, 58, 60, 65, 80, 75, 65, 55, 45, 35, 30, 40, 55, 65, 70,
        60, 50, 40, 35, 30, 28, 25, 35, 45, 55, 65, 60, 50, 40, 35, 30, 28, 25, 20,
    ]
    bars = _bars(closes)
    rsi = _series(rsi_values, bars)
    config = _config(indicators=["rsi"], rsi_reversal_points=5.0, pairing_window=3)

    divs = detect_for_indicator(bars, "rsi", rsi, config, "TST", Timeframe.DAILY)

    bearish = [d for d in divs if d.direction == Direction.BEARISH]
    assert len(bearish) == 2
    pairs = {(d.p1_price, d.p2_price) for d in bearish}
    assert pairs == {(120.0, 130.0), (130.0, 140.0)}
    # Not merged into one row spanning all three pivots.
    assert len({d.id for d in bearish}) == 2


def test_macd_hist_divergence_via_rolling_std_threshold():
    # Same fixture as the RSI test above, but routed through the
    # rolling-std threshold path (indicator_name="macd_hist", not the flat
    # rsi_reversal_points) -- confirms pairing/evaluation is genuinely
    # indicator-agnostic, not secretly RSI-shaped.
    bars = _bars(_HIGH_CLOSES)
    macd_hist = _series(_DECREASING_RSI, bars)
    config = _config(indicators=["macd_hist"], std_window=5, std_reversal_mult=1.0, pairing_window=3)

    divs = detect_for_indicator(bars, "macd_hist", macd_hist, config, "TST", Timeframe.DAILY)

    assert len(divs) == 1
    d = divs[0]
    assert d.indicator == IndicatorKind.MACD_HIST
    assert d.direction == Direction.BEARISH
    assert (d.i1_value, d.i2_value) == (80.0, 70.0)


# ---- as_of / DB round-trip (real detect() + real talib indicators) ----

_ASOF_CLOSES = [
    100, 101, 102, 103, 104, 105, 120, 115, 110, 105, 100, 95, 90, 100, 110, 120, 130, 125, 115, 105, 95, 90, 85, 80,
    75, 70, 68, 66, 64, 62, 60, 58, 56, 54, 52, 50, 48, 46, 44, 42,
    50, 60, 70, 80, 90, 100, 110, 120, 135, 130, 120, 110, 100, 95, 90, 85, 80, 75, 70, 65,
]


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    idx = pd.bdate_range("2020-01-01", periods=len(_ASOF_CLOSES))
    frame = pd.DataFrame(
        {
            "timestamp": idx,
            "open": _ASOF_CLOSES,
            "high": [c + 0.5 for c in _ASOF_CLOSES],
            "low": [c - 0.5 for c in _ASOF_CLOSES],
            "close": _ASOF_CLOSES,
            "volume": [1000] * len(_ASOF_CLOSES),
            "is_partial": [0] * len(_ASOF_CLOSES),
        }
    ).set_index("timestamp")
    db.upsert_bars(connection, "bars_1d", "TST", db.YFINANCE, frame)
    yield connection
    connection.close()


def _asof_config() -> DivergenceConfig:
    return DivergenceConfig(
        indicators=["rsi"], warmup_bars=5, atr_period=3, rsi_period=3,
        min_bars=0, pairing_window=3, min_pivot_span_bars=5,
    )


def test_as_of_before_second_pivot_confirmation_excludes_the_divergence(conn):
    # Empirically verified against this exact fixture: the real-RSI
    # divergence's second price pivot appears 2020-01-23 and its (later)
    # confirmed_at is 2020-01-28.
    divs, _report, skip = detect(conn, "TST", Timeframe.DAILY, _asof_config(), as_of="2020-01-24")
    assert skip is None
    assert divs == []


def test_as_of_at_or_after_confirmation_includes_the_divergence(conn):
    divs, _report, skip = detect(conn, "TST", Timeframe.DAILY, _asof_config(), as_of="2020-01-28")
    assert skip is None
    assert len(divs) == 1
    assert divs[0].confirmed_at == "2020-01-28T00:00:00"


def test_min_bars_skips_short_series(conn):
    config = _asof_config()
    config.min_bars = 10_000
    divs, report, skip = detect(conn, "TST", Timeframe.DAILY, config)
    assert divs == []
    assert skip is not None
    assert report.rows_loaded == len(_ASOF_CLOSES)


# ---- store upsert idempotency ----


@pytest.fixture
def derived_conn():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    create_divergences_table(connection)
    yield connection
    connection.close()


def test_rerunning_detection_twice_does_not_duplicate_rows(derived_conn):
    bars = _bars(_HIGH_CLOSES)
    rsi = _series(_DECREASING_RSI, bars)
    config = _config(indicators=["rsi"], rsi_reversal_points=5.0, pairing_window=3)

    run1 = detect_for_indicator(bars, "rsi", rsi, config, "TST", Timeframe.DAILY)
    upsert_divergences(derived_conn, run1, "run-1")
    row_count_after_first = derived_conn.execute("SELECT COUNT(*) FROM divergences").fetchone()[0]
    original_id = run1[0].id

    # A second, independent detection run over identical input mints a
    # fresh uuid4 per row (same as detect_for_indicator always does) but
    # must land on the same natural key.
    run2 = detect_for_indicator(bars, "rsi", rsi, config, "TST", Timeframe.DAILY)
    assert run2[0].id != original_id
    upsert_divergences(derived_conn, run2, "run-2")
    row_count_after_second = derived_conn.execute("SELECT COUNT(*) FROM divergences").fetchone()[0]

    assert row_count_after_first == 1
    assert row_count_after_second == row_count_after_first

    stored_id, stored_run_id = derived_conn.execute(
        "SELECT id, run_id FROM divergences WHERE ticker = 'TST'"
    ).fetchone()
    # id is preserved from the first insert; only the mutable fields (here,
    # run_id) reflect the later run.
    assert stored_id == original_id
    assert stored_run_id == "run-2"

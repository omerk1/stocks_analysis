import pandas as pd
import pytest

from src.data_processing import db
from src.market_common.data import load_and_validate, load_bars, validate_bars
from src.market_common.models import Timeframe


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _bars(rows):
    """rows: list of (date_str, open, high, low, close, volume, is_partial)"""
    df = pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume", "is_partial"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def test_load_bars_daily_excludes_partial_rows(conn):
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.YFINANCE,
        _bars([
            ("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 0),
            ("2024-01-02", 100.5, 103.0, 100.0, 102.0, 1500, 1),  # partial -- excluded
        ]),
    )

    result = load_bars(conn, "AAPL", Timeframe.DAILY, as_of="2024-01-05")

    assert len(result) == 1
    assert result.iloc[0]["close"] == 100.5


def test_load_bars_daily_respects_as_of(conn):
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.YFINANCE,
        _bars([
            ("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 0),
            ("2024-01-02", 100.5, 103.0, 100.0, 102.0, 1500, 0),
            ("2024-01-03", 102.0, 104.0, 101.0, 103.0, 1200, 0),
        ]),
    )

    result = load_bars(conn, "AAPL", Timeframe.DAILY, as_of="2024-01-02")

    assert list(result.index.strftime("%Y-%m-%d")) == ["2024-01-01", "2024-01-02"]


def test_load_bars_ignores_other_sources(conn):
    db.upsert_bars(conn, "bars_1d", "AAPL", db.YFINANCE, _bars([("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 0)]))
    db.upsert_bars(conn, "bars_1d", "AAPL", db.POLYGON, _bars([("2024-01-01", 999.0, 999.0, 999.0, 999.0, 1, 0)]))

    result = load_bars(conn, "AAPL", Timeframe.DAILY, as_of="2024-01-05")

    assert len(result) == 1
    assert result.iloc[0]["close"] == 100.5


def test_load_bars_weekly_resamples_from_daily(conn):
    # A full Mon-Fri week -- plus one following day, so the week reads as
    # closed. Closure is judged against the *data's own* latest timestamp,
    # not wall-clock/as_of (see load_bars' docstring) -- data ending
    # exactly on the week's own Friday isn't enough by itself (closure
    # requires evidence *strictly after* that Friday), which is exactly
    # the real lookahead-safety mechanism this project verified against
    # real PAAS data (docs/sr_lines_design_notes.md).
    rows = [
        ("2024-01-01", 100.0, 105.0, 99.0, 101.0, 1000, 0),  # Mon
        ("2024-01-02", 101.0, 103.0, 98.0, 102.0, 1000, 0),
        ("2024-01-03", 102.0, 104.0, 100.0, 103.0, 1000, 0),
        ("2024-01-04", 103.0, 106.0, 101.0, 104.0, 1000, 0),
        ("2024-01-05", 104.0, 108.0, 101.0, 106.0, 1000, 0),  # Fri, week close
        ("2024-01-08", 111.0, 112.0, 109.0, 111.5, 500, 0),  # next Mon -- signals week closed
    ]
    db.upsert_bars(conn, "bars_1d", "AAPL", db.YFINANCE, _bars(rows))

    result = load_bars(conn, "AAPL", Timeframe.WEEKLY, as_of="2024-02-01")

    # Week 1 is closed (fully complete); week 2 (just the one Monday) is
    # not -- only week 1 comes back.
    assert len(result) == 1
    week = result.iloc[0]
    assert (week["open"], week["high"], week["low"], week["close"], week["volume"]) == (
        100.0, 108.0, 98.0, 106.0, 5000.0,
    )


def test_load_bars_start_window_applies_before_weekly_resample(conn):
    # Regression: windowing must happen on the *daily* bars before
    # resampling, not on the resulting weekly bars after -- otherwise a
    # week that should be entirely excluded could instead contribute a
    # malformed partial aggregate. `start` lands exactly on week 2's
    # Monday (a clean week-aligned boundary -- a `start` landing mid-week
    # would itself only see that week's remaining days at the daily-read
    # step, same partial-open behavior sr_lines always had at a window
    # boundary; unchanged, not what this test is checking).
    rows = [
        ("2024-01-01", 100.0, 105.0, 99.0, 101.0, 1000, 0),  # Mon, week 1
        ("2024-01-02", 101.0, 103.0, 98.0, 102.0, 1000, 0),
        ("2024-01-03", 102.0, 104.0, 100.0, 103.0, 1000, 0),
        ("2024-01-04", 103.0, 106.0, 101.0, 104.0, 1000, 0),
        ("2024-01-05", 104.0, 108.0, 101.0, 106.0, 1000, 0),  # Fri, week 1 close
        ("2024-01-08", 111.0, 112.0, 109.0, 111.5, 2000, 0),  # Mon, week 2 -- start lands here
        ("2024-01-09", 111.5, 113.0, 110.0, 112.0, 2000, 0),
        ("2024-01-10", 112.0, 114.0, 111.0, 113.0, 2000, 0),
        ("2024-01-11", 113.0, 115.0, 112.0, 114.0, 2000, 0),
        ("2024-01-12", 114.0, 116.0, 113.0, 115.0, 2000, 0),  # Fri, week 2 close
        ("2024-01-15", 115.0, 116.0, 114.0, 115.5, 500, 0),  # next Mon -- signals week 2 closed
    ]
    db.upsert_bars(conn, "bars_1d", "AAPL", db.YFINANCE, _bars(rows))

    result = load_bars(conn, "AAPL", Timeframe.WEEKLY, as_of="2024-02-01", start="2024-01-08")

    # Week 1 (Monday 2024-01-01) is entirely before `start` -- excluded.
    # Week 2's own real Monday open (111.0) is intact, not distorted.
    assert len(result) == 1
    assert result.index[0].strftime("%Y-%m-%d") == "2024-01-08"
    assert result.iloc[0]["open"] == 111.0


def test_validate_bars_drops_rows_failing_hard_ohlc_checks():
    bars = _bars([
        ("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 0),  # valid
        ("2024-01-02", 2575.0, 532.0, 532.0, 2380.0, 1000, 0),  # close/open outside high/low
        ("2024-01-03", 0.0, 0.0, 0.0, 0.5, 1000, 0),  # zero prices
        ("2024-01-04", 100.0, 101.0, 99.0, 100.0, -5, 0),  # negative volume
    ]).drop(columns=["is_partial"])

    clean, report = validate_bars(bars, "TEST")

    assert len(clean) == 1
    assert report.rows_loaded == 4
    assert report.rows_dropped == 3


def test_validate_bars_flags_suspicious_jumps_without_dropping():
    bars = _bars([
        ("2024-01-01", 100.0, 101.0, 99.0, 100.0, 1000, 0),
        ("2024-01-02", 100.0, 401.0, 99.0, 400.0, 1000, 0),  # 4x jump
        ("2024-01-03", 400.0, 401.0, 399.0, 400.0, 1000, 0),
    ]).drop(columns=["is_partial"])

    clean, report = validate_bars(bars, "TEST")

    assert len(clean) == 3
    assert "2024-01-02" in report.suspicious_jump_dates


def test_validate_bars_uses_given_threshold_not_a_hardcoded_default():
    rows = [("2024-01-01", 100.0, 101.0, 99.0, 100.0, 1000, 0)]
    for i in range(2, 21):
        rows.append((f"2024-01-{i:02d}", 0.0, 0.0, 0.0, 1.0, 1000, 0))  # 19 bad rows
    bars = _bars(rows).drop(columns=["is_partial"])

    _, lenient = validate_bars(bars, "TEST", corruption_warning_threshold=0.99)
    _, strict = validate_bars(bars, "TEST", corruption_warning_threshold=0.01)

    assert lenient.unreliable is False
    assert strict.unreliable is True


def test_load_and_validate_round_trip(conn):
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.YFINANCE,
        _bars([("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 0)]),
    )

    clean, report = load_and_validate(conn, "AAPL", Timeframe.DAILY, as_of="2024-01-05")

    assert len(clean) == 1
    assert report.rows_loaded == 1
    assert report.rows_dropped == 0

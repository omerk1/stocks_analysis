import pandas as pd
import pytest

from src.signals.sr_lines.config import SRConfig
from src.signals.sr_lines.data import validate_bars


def _bars(rows):
    """rows: list of (date_str, open, high, low, close, volume)"""
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def test_drops_rows_failing_hard_ohlc_checks():
    bars = _bars(
        [
            ("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000),  # valid
            ("2024-01-02", 2575.0, 532.0, 532.0, 2380.0, 1000),  # close/open outside high/low
            ("2024-01-03", 0.0, 0.0, 0.0, 0.5, 1000),  # zero prices
            ("2024-01-04", 100.0, 101.0, 99.0, 100.0, -5),  # negative volume
        ]
    )
    config = SRConfig()

    clean, report = validate_bars(bars, "TEST", config)

    assert len(clean) == 1
    assert report.rows_loaded == 4
    assert report.rows_dropped == 3
    assert report.drop_rate == pytest.approx(0.75)


def test_flags_suspicious_jumps_without_dropping():
    bars = _bars(
        [
            ("2024-01-01", 100.0, 101.0, 99.0, 100.0, 1000),
            ("2024-01-02", 100.0, 401.0, 99.0, 400.0, 1000),  # 4x jump -- outside [1/3, 3]
            ("2024-01-03", 400.0, 401.0, 399.0, 400.0, 1000),
        ]
    )
    config = SRConfig()

    clean, report = validate_bars(bars, "TEST", config)

    assert len(clean) == 3  # not dropped, just flagged
    assert "2024-01-02" in report.suspicious_jump_dates


def test_unreliable_flag_set_when_drop_rate_exceeds_threshold():
    rows = [("2024-01-01", 100.0, 101.0, 99.0, 100.0, 1000)]
    for i in range(2, 21):
        rows.append((f"2024-01-{i:02d}", 0.0, 0.0, 0.0, 1.0, 1000))  # 19 bad rows
    bars = _bars(rows)
    config = SRConfig(corruption_warning_threshold=0.10)

    _, report = validate_bars(bars, "BADTICKER", config)

    assert report.drop_rate > 0.10
    assert report.unreliable is True


def test_reliable_when_drop_rate_under_threshold():
    rows = [("2024-01-01", 100.0, 101.0, 99.0, 100.0, 1000)]
    for i in range(2, 21):
        rows.append((f"2024-01-{i:02d}", 100.0, 101.0, 99.0, 100.0, 1000))  # 19 good rows
    bars = _bars(rows)
    config = SRConfig(corruption_warning_threshold=0.10)

    _, report = validate_bars(bars, "GOODTICKER", config)

    assert report.unreliable is False


def test_asserts_single_source_when_source_column_present():
    bars = _bars(
        [
            ("2024-01-01", 100.0, 101.0, 99.0, 100.0, 1000),
            ("2024-01-02", 100.0, 101.0, 99.0, 100.0, 1000),
        ]
    )
    bars["source"] = ["polygon", "yfinance"]
    config = SRConfig()

    with pytest.raises(ValueError, match="exactly one source"):
        validate_bars(bars, "TEST", config)


def test_allows_single_consistent_source_column():
    bars = _bars(
        [
            ("2024-01-01", 100.0, 101.0, 99.0, 100.0, 1000),
            ("2024-01-02", 100.0, 101.0, 99.0, 100.0, 1000),
        ]
    )
    bars["source"] = "yfinance"
    config = SRConfig()

    clean, report = validate_bars(bars, "TEST", config)

    assert len(clean) == 2
    assert "source" not in clean.columns

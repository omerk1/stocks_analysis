from unittest.mock import MagicMock

import pandas as pd

from src.data_processing.validate_sources import compare_daily_bars


def _closes(dates_and_closes):
    df = pd.DataFrame(
        {"close": [c for _, c in dates_and_closes]},
        index=pd.to_datetime([d for d, _ in dates_and_closes]),
    )
    df.index.name = "timestamp"
    return df


def test_no_discrepancies_within_tolerance():
    polygon_client = MagicMock()
    yfinance_client = MagicMock()
    polygon_client.get_daily_bars.return_value = _closes([("2024-01-01", 100.0), ("2024-01-02", 101.0)])
    yfinance_client.get_daily_bars.return_value = _closes([("2024-01-01", 100.05), ("2024-01-02", 100.99)])

    result = compare_daily_bars(
        "AAPL", "2024-01-01", "2024-01-02",
        tolerance=0.01, polygon_client=polygon_client, yfinance_client=yfinance_client,
    )

    assert result.empty


def test_flags_dates_beyond_tolerance():
    polygon_client = MagicMock()
    yfinance_client = MagicMock()
    polygon_client.get_daily_bars.return_value = _closes([("2024-01-01", 100.0), ("2024-01-02", 101.0)])
    yfinance_client.get_daily_bars.return_value = _closes([("2024-01-01", 100.0), ("2024-01-02", 150.0)])

    result = compare_daily_bars(
        "AAPL", "2024-01-01", "2024-01-02",
        tolerance=0.01, polygon_client=polygon_client, yfinance_client=yfinance_client,
    )

    assert len(result) == 1
    assert result.index[0] == pd.Timestamp("2024-01-02")


def test_only_compares_dates_present_in_both_sources():
    polygon_client = MagicMock()
    yfinance_client = MagicMock()
    polygon_client.get_daily_bars.return_value = _closes(
        [("2024-01-01", 100.0), ("2024-01-02", 101.0)]
    )
    yfinance_client.get_daily_bars.return_value = _closes([("2024-01-01", 100.0)])

    result = compare_daily_bars(
        "AAPL", "2024-01-01", "2024-01-02",
        tolerance=0.01, polygon_client=polygon_client, yfinance_client=yfinance_client,
    )

    assert result.empty  # 01-02 missing from yfinance side, not flagged as a mismatch

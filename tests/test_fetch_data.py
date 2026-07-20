from unittest.mock import MagicMock

import pandas as pd

from src.data_processing.fetch_data import fetch_ticker


def _bars(dates_and_closes):
    df = pd.DataFrame(
        {
            "date": [pd.Timestamp(d) for d, _ in dates_and_closes],
            "open": [c for _, c in dates_and_closes],
            "high": [c for _, c in dates_and_closes],
            "low": [c for _, c in dates_and_closes],
            "close": [c for _, c in dates_and_closes],
            "volume": [1000] * len(dates_and_closes),
            "vwap": [c for _, c in dates_and_closes],
            "transactions": [10] * len(dates_and_closes),
        }
    ).set_index("date")
    return df


def test_fetch_ticker_writes_new_file(tmp_path):
    client = MagicMock()
    client.get_daily_bars.return_value = _bars([("2024-01-01", 100.0), ("2024-01-02", 101.0)])

    path = fetch_ticker(client, "AAPL", "2024-01-01", "2024-01-02", tmp_path)

    result = pd.read_csv(path, index_col="date", parse_dates=["date"])
    assert len(result) == 2


def test_fetch_ticker_merges_and_dedupes(tmp_path):
    existing = _bars([("2024-01-01", 100.0), ("2024-01-02", 101.0)])
    existing.to_csv(tmp_path / "AAPL.csv")

    client = MagicMock()
    # Overlapping date (01-02, updated close) plus one new date (01-03)
    client.get_daily_bars.return_value = _bars([("2024-01-02", 999.0), ("2024-01-03", 102.0)])

    path = fetch_ticker(client, "AAPL", "2024-01-02", "2024-01-03", tmp_path)

    result = pd.read_csv(path, index_col="date", parse_dates=["date"])
    assert len(result) == 3
    assert result.loc[pd.Timestamp("2024-01-02"), "close"] == 999.0

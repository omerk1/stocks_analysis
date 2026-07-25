from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.data_processing import db
from src.data_processing.ticker_universe import refresh_ticker_universe


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _tickers_df(rows):
    return pd.DataFrame(rows, columns=["ticker", "name", "type", "active", "delisted_utc"])


def test_refresh_pulls_both_active_and_inactive(conn):
    client = MagicMock()

    def list_common_stock_tickers(active):
        if active:
            return _tickers_df([("AAPL", "Apple Inc.", "CS", True, None)])
        return _tickers_df([("AABA", "Altaba Inc.", "CS", False, "2019-10-07T04:00:00Z")])

    client.list_common_stock_tickers.side_effect = list_common_stock_tickers

    refresh_ticker_universe(client, conn)

    result = db.read_tickers(conn)
    assert set(result["ticker"]) == {"AAPL", "AABA"}
    assert client.list_common_stock_tickers.call_count == 2

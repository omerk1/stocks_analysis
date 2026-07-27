import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data_processing import db
from src.data_processing.index_membership import (
    NASDAQ100,
    SP500,
    fetch_nasdaq100_membership,
    fetch_sp500_membership,
    refresh_index_membership,
)


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


@patch("src.data_processing.index_membership.pd.read_csv")
def test_fetch_sp500_membership_shapes_columns(mock_read_csv):
    mock_read_csv.return_value = pd.DataFrame(
        [
            ("AAPL", "1996-01-02", None, "extra_column_ignored"),
            ("AABA", "1999-12-08", "2017-06-19", "extra_column_ignored"),
        ],
        columns=["ticker", "start_date", "end_date", "junk"],
    )

    df = fetch_sp500_membership()

    assert list(df.columns) == ["ticker", "start_date", "end_date"]
    assert len(df) == 2


def _change(effective_date, additions=frozenset(), removals=frozenset()):
    return MagicMock(effective_date=effective_date, additions=additions, removals=removals)


@patch("src.data_processing.index_membership._n100_tickers_as_of")
@patch("src.data_processing.index_membership._n100_changes")
def test_fetch_nasdaq100_membership_reconstructs_intervals_from_tickers_as_of(
    mock_changes, mock_tickers_as_of
):
    # Only effective_date is used to pick sampling points -- additions/removals
    # on the mock changes are irrelevant here since tickers_as_of is the
    # ground truth, not the changes themselves (see module docstring for why).
    baseline = datetime.date(2020, 1, 1)
    mock_changes.BASELINE_DATE = baseline
    mock_changes.changes_since.return_value = [_change(datetime.date(2020, 6, 1))]
    mock_changes.changes_before.return_value = [_change(datetime.date(2016, 1, 1))]

    snapshots = {
        datetime.date(2015, 1, 1): {"AAPL"},
        datetime.date(2016, 1, 1): {"AAPL", "MSFT"},
        datetime.date(2020, 1, 1): {"AAPL", "MSFT"},
        datetime.date(2020, 6, 1): {"AAPL"},  # MSFT dropped out here
    }
    mock_tickers_as_of.side_effect = lambda y, m, d: snapshots[datetime.date(y, m, d)]

    df = fetch_nasdaq100_membership()

    aapl = df[df["ticker"] == "AAPL"].iloc[0]
    assert aapl["start_date"] == datetime.date(2015, 1, 1)
    assert aapl["end_date"] is None  # still current

    msft = df[df["ticker"] == "MSFT"].iloc[0]
    assert msft["start_date"] == datetime.date(2016, 1, 1)
    assert msft["end_date"] == datetime.date(2020, 5, 31)  # day before it dropped out


@patch("src.data_processing.index_membership.fetch_nasdaq100_membership")
@patch("src.data_processing.index_membership.fetch_sp500_membership")
def test_refresh_index_membership_replaces_both_indices(mock_sp500, mock_nasdaq100, conn):
    mock_sp500.return_value = pd.DataFrame(
        [("AAPL", "1996-01-02", None)], columns=["ticker", "start_date", "end_date"]
    )
    mock_nasdaq100.return_value = pd.DataFrame(
        [("MSFT", "2000-01-01", None)], columns=["ticker", "start_date", "end_date"]
    )

    refresh_index_membership(conn)

    assert set(db.read_index_membership(conn, SP500)["ticker"]) == {"AAPL"}
    assert set(db.read_index_membership(conn, NASDAQ100)["ticker"]) == {"MSFT"}

import datetime
import io
from unittest.mock import MagicMock, patch

import openpyxl
import pandas as pd
import pytest

from src.foundation.data_processing import etf_holdings
from src.foundation.data_processing.etf_holdings import HoldingsFileError

COLUMNS = ["Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector", "Shares Held", "Local Currency"]
NOW = datetime.datetime(2026, 11, 19, 18, 0, tzinfo=datetime.timezone.utc)


def _equities(n):
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return [[f"CO {i}", letters[i // 26 % 26] + letters[i % 26] + "X", f"ID{i}", "S", 0.1, "-", 1000 + i, "USD"]
            for i in range(n)]


def _xlsx(lines, fund="SPY", as_of="As of 18-Nov-2026", columns=COLUMNS):
    """A file laid out like State Street's: four header rows, the column names,
    the holdings, a blank row, then disclaimer text."""
    book = openpyxl.Workbook()
    sheet = book.active
    for row in (["Fund Name:", "SPDR S&P 500 ETF Trust"], ["Ticker Symbol:", fund], ["Holdings:", as_of], [],
                columns, *lines, [], ["Distributor: ... disclaimer text"]):
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _file(n=500, extra=()):
    return _xlsx([*_equities(n), *extra])


CASH = ["US DOLLAR", "-", "CASH_USD", "-", 0.12, "-", 9_000_000, "USD"]
CVR = ["CONTRA HOLOGIC INCORPO", "2602335D", "436CVR021", "-", 0.00001, "-", 2_578_626, "USD"]
CLASS_B = ["BERKSHIRE HATHAWAY INC CL B", "BRK.B", "084670702", "2073390", 1.7, "-", 100, "USD"]


def test_parse_reads_the_as_of_date_and_every_line():
    as_of, holdings = etf_holdings.parse(_file(500, [CASH]))
    assert as_of == datetime.date(2026, 11, 18)
    assert len(holdings) == 501
    assert "Distributor: ... disclaimer text" not in set(holdings["Name"])


def test_members_drop_cash_and_lines_without_a_ticker_symbol_and_keep_class_suffixes():
    _, holdings = etf_holdings.parse(_file(500, [CASH, CVR, CLASS_B]))
    picked = etf_holdings.members(holdings)
    assert len(picked) == 501
    assert "BRK.B" in set(picked["ticker"])
    assert not {"-", "2602335D"} & set(picked["ticker"])
    assert list(picked.columns) == ["ticker", "name", "identifier", "weight", "shares_held"]


@pytest.mark.parametrize("content, message", [
    (_xlsx(_equities(500), fund="IVV"), "not the SPY holdings file"),
    (_xlsx(_equities(500), as_of="18-Nov-2026"), "no as-of date"),
    (_xlsx(_equities(500), columns=["Name", "Symbol", *COLUMNS[2:]]), "unexpected columns"),
])
def test_parse_refuses_a_file_laid_out_differently(content, message):
    with pytest.raises(HoldingsFileError, match=message):
        etf_holdings.parse(content)


def test_a_ticker_twice_is_refused():
    lines = _equities(500)
    _, holdings = etf_holdings.parse(_xlsx([*lines, lines[0]]))
    with pytest.raises(HoldingsFileError, match="appears twice"):
        etf_holdings.members(holdings)


@pytest.mark.parametrize("n", [100, 600])
def test_a_member_count_far_from_the_index_is_refused_and_nothing_is_written(tmp_path, n):
    with pytest.raises(HoldingsFileError, match="members on 2026-11-18"):
        etf_holdings.record(_file(n), tmp_path, now=NOW)
    assert list(tmp_path.iterdir()) == []


def test_record_keeps_the_raw_file_the_members_and_a_log_row(tmp_path):
    content = _file(500, [CASH])
    status, path = etf_holdings.record(content, tmp_path, now=NOW)
    assert (status, path) == ("new", tmp_path / "2026-11-18.xlsx")
    assert path.read_bytes() == content
    assert len(pd.read_csv(tmp_path / "2026-11-18.csv")) == 500
    log = pd.read_csv(tmp_path / "fetch_log.csv")
    assert log.columns.tolist() == etf_holdings.LOG_COLUMNS
    assert log.iloc[0][["fund", "as_of", "n_members", "status"]].tolist() == ["SPY", "2026-11-18", 500, "new"]
    assert log.iloc[0]["fetched_at"] == "2026-11-19T18:00:00+00:00"


def test_the_same_file_again_is_skipped_and_logged(tmp_path):
    content = _file()
    etf_holdings.record(content, tmp_path, now=NOW)
    status, path = etf_holdings.record(content, tmp_path, now=NOW)
    assert (status, path) == ("same", tmp_path / "2026-11-18.xlsx")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-18.csv", "2026-11-18.xlsx", "fetch_log.csv"]
    assert pd.read_csv(tmp_path / "fetch_log.csv")["status"].tolist() == ["new", "same"]


def test_a_different_file_for_the_same_date_never_overwrites_the_first(tmp_path):
    first, second = _file(500), _file(501)
    etf_holdings.record(first, tmp_path, now=NOW)
    status, path = etf_holdings.record(second, tmp_path, now=NOW)
    assert status == "changed"
    assert (tmp_path / "2026-11-18.xlsx").read_bytes() == first
    assert path.read_bytes() == second and path.name.startswith("2026-11-18.")
    assert len(pd.read_csv(path.with_suffix(".csv"))) == 501


@patch("src.foundation.data_processing.etf_holdings.requests.get")
def test_fetch_refuses_a_page_that_isnt_a_spreadsheet(mock_get):
    mock_get.return_value = MagicMock(content=b"<!DOCTYPE html>", headers={"content-type": "text/html"})
    with pytest.raises(HoldingsFileError, match="isn't a spreadsheet"):
        etf_holdings.fetch()


@patch("src.foundation.data_processing.etf_holdings.requests.get")
def test_fetch_returns_the_spreadsheet_bytes(mock_get):
    mock_get.return_value = MagicMock(content=_file())
    assert etf_holdings.fetch().startswith(b"PK")

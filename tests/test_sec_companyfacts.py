import json
import zipfile

import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing import sec_companyfacts as sec
from src.foundation.data_processing.bulk_sec_shares_ingest import backfill_sec_shares


def _fact(end, val, accn, filed, form="10-Q"):
    return {"end": end, "val": val, "accn": accn, "filed": filed, "form": form}


def _company(cover=(), balance=()):
    facts = {}
    if cover:
        facts.setdefault("dei", {})["EntityCommonStockSharesOutstanding"] = {"units": {"shares": list(cover)}}
    if balance:
        facts.setdefault("us-gaap", {})["CommonStockSharesOutstanding"] = {"units": {"shares": list(balance)}}
    return {"cik": 1, "facts": facts}


def test_cover_page_count_is_keyed_by_filing_date():
    s = sec.share_counts(_company(cover=[_fact("2020-04-20", 100, "a1", "2020-05-01")]))
    assert s.to_dict() == {pd.Timestamp("2020-05-01"): 100.0}


def test_cover_page_preferred_over_balance_sheet_in_the_same_filing():
    s = sec.share_counts(_company(
        cover=[_fact("2020-04-20", 105, "a1", "2020-05-01")],
        balance=[_fact("2020-03-31", 100, "a1", "2020-05-01")],
    ))
    assert s.tolist() == [105.0]


def test_balance_sheet_fallback_uses_the_filings_own_latest_period_not_prior_ones():
    # A 10-K repeats last year's balance-sheet count; only the current one counts.
    s = sec.share_counts(_company(balance=[
        _fact("2019-12-31", 90, "k1", "2020-02-20", "10-K"),
        _fact("2018-12-31", 80, "k1", "2020-02-20", "10-K"),
    ]))
    assert s.to_dict() == {pd.Timestamp("2020-02-20"): 90.0}


def test_stale_restatements_are_dropped():
    # An amendment filed in 2022 restating a 2019 period isn't a 2022 count.
    s = sec.share_counts(_company(cover=[
        _fact("2019-10-01", 50, "a1", "2019-10-10"),
        _fact("2019-10-01", 50, "a2", "2022-03-01", "10-K/A"),
    ]))
    assert list(s.index) == [pd.Timestamp("2019-10-10")]


def test_non_positive_and_future_dated_facts_are_ignored():
    s = sec.share_counts(_company(cover=[
        _fact("2020-04-20", 0, "a1", "2020-05-01"),
        _fact("2020-06-01", 10, "a2", "2020-05-01"),  # period ends after filing
    ]))
    assert s.empty


def test_two_filings_on_one_day_keep_the_later_period():
    s = sec.share_counts(_company(cover=[
        _fact("2020-03-01", 10, "a1", "2020-05-01"),
        _fact("2020-04-20", 12, "a2", "2020-05-01"),
    ]))
    assert s.tolist() == [12.0]


def test_empty_company_gives_empty_series():
    s = sec.share_counts({"facts": {}})
    assert s.empty and s.name == "shares_outstanding"


def test_cik_map_reads_sec_spelling():
    import json as _json
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp()) / "company_tickers.json"
    d.write_text(_json.dumps({"0": {"cik_str": 1067983, "ticker": "BRK-B", "title": "B"},
                              "1": {"cik_str": 320193, "ticker": "AAPL", "title": "A"}}))
    assert sec.load_cik_map(d) == {"BRK-B": 1067983, "AAPL": 320193}
    assert sec.to_sec_ticker("brk.b") == "BRK-B"


def test_isolated_spike_is_dropped_but_a_real_step_change_is_kept():
    idx = pd.to_datetime(["2020-01-01", "2020-04-01", "2020-07-01", "2020-10-01", "2021-01-01"])
    spiked = pd.Series([100.0, 100_000.0, 101.0, 102.0, 103.0], index=idx)
    assert sec.drop_isolated_spikes(spiked).tolist() == [100.0, 101.0, 102.0, 103.0]
    reverse_split = pd.Series([100.0, 101.0, 1.0, 1.01, 1.02], index=idx)  # 1-for-100, stays
    assert sec.drop_isolated_spikes(reverse_split).tolist() == reverse_split.tolist()


def test_agreement_matches_points_within_tolerance_only():
    sec_s = pd.Series([100.0, 200.0, 300.0], index=pd.to_datetime(["2020-01-01", "2020-06-01", "2021-01-01"]))
    ref = pd.Series([100.0, 400.0], index=pd.to_datetime(["2020-01-05", "2020-06-08"]))
    n, ratio = sec.agreement(sec_s, ref, tolerance_days=10)
    assert n == 2 and ratio == pytest.approx(0.75)
    assert sec.agreement(sec_s, pd.Series(dtype=float)) == (0, None)


@pytest.fixture
def conn():
    c = db.get_connection(":memory:")
    db.create_tables(c)
    yield c
    c.close()


def _zip(tmp_path, companies: dict[int, dict]):
    path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for cik, body in companies.items():
            zf.writestr(f"CIK{cik:010d}.json", json.dumps(body))
    return zipfile.ZipFile(path)


def _quarterly(start, n, value):
    dates = pd.date_range(start, periods=n, freq="QS")
    return [_fact((d - pd.Timedelta(days=5)).strftime("%Y-%m-%d"), value, f"q{i}", d.strftime("%Y-%m-%d"))
            for i, d in enumerate(dates)]


def _yf(conn, ticker, start, n, value):
    dates = pd.date_range(start, periods=n, freq="QS") + pd.Timedelta(days=2)
    db.upsert_shares_outstanding(conn, ticker, db.YFINANCE, pd.Series([value] * n, index=dates))


def test_backfill_keeps_agreeing_companies_and_rejects_scale_or_class_mismatches(conn, tmp_path):
    zf = _zip(tmp_path, {
        1: _company(cover=_quarterly("2012-01-01", 20, 100.0)),         # agrees with yfinance
        2: _company(cover=_quarterly("2012-01-01", 20, 100_000.0)),     # 1000x scale error
        3: _company(cover=_quarterly("2012-01-01", 20, 100.0)),         # no yfinance overlap, unique CIK
        4: _company(cover=_quarterly("2012-01-01", 20, 50.0)),          # no overlap, CIK shared by two tickers
        5: {"facts": {}},
    })
    for t in ("AAA", "SCALE"):
        _yf(conn, t, "2015-01-01", 8, 100.0)
    cik_map = {"AAA": 1, "SCALE": 2, "SOLO": 3, "CLS-A": 4, "CLS-B": 4, "EMPTY": 5, "GONE": 6}
    # A stale sec_edgar row for AAA must be replaced; its yfinance rows must stay.
    db.upsert_shares_outstanding(conn, "AAA", db.SEC_EDGAR, pd.Series([1.0], index=pd.to_datetime(["2010-01-01"])))

    tally = backfill_sec_shares(conn, zf, cik_map, ["AAA", "SCALE", "SOLO", "CLS.A", "CLS.B", "EMPTY", "GONE", "NOPE"])

    assert tally["stored"] == 2 and tally["points"] == 40
    assert tally["disagrees_with_yfinance"] == 1
    assert tally["ambiguous_class"] == 2
    assert tally["no_share_facts"] == 1 and tally["not_in_zip"] == 1 and tally["no_cik"] == 1
    aaa = db.read_shares_outstanding(conn, "AAA", db.SEC_EDGAR)
    assert len(aaa) == 20 and aaa["date"].min() == "2012-01-01"
    assert len(db.read_shares_outstanding(conn, "AAA", db.YFINANCE)) == 8
    assert db.read_shares_outstanding(conn, "SCALE", db.SEC_EDGAR).empty

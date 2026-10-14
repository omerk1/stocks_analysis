import json
import zipfile

import pandas as pd
import pytest

from src.foundation.data_processing import bulk_sec_earnings_ingest as ingest
from src.foundation.data_processing import db
from src.foundation.data_processing import sec_earnings as se

SESSIONS = pd.bdate_range("2020-01-01", "2020-12-31")


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _filing(accession, form, filed, accepted, items="", report=""):
    return {"accessionNumber": accession, "form": form, "items": items, "filingDate": filed,
            "acceptanceDateTime": accepted, "reportDate": report}


def _columns(filings):
    return {c: [f[c] for f in filings] for c in se._COLUMNS}


def _zip(tmp_path, companies, overflow=None):
    """{cik: [filing, ...]} -> submissions.zip; `overflow` {cik: [...]} goes to a -submissions-001 file."""
    path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for cik, filings in companies.items():
            files = []
            if overflow and cik in overflow:
                name = f"CIK{cik:010d}-submissions-001.json"
                zf.writestr(name, json.dumps(_columns(overflow[cik])))
                files.append({"name": name})
            zf.writestr(f"CIK{cik:010d}.json", json.dumps({"filings": {"recent": _columns(filings), "files": files}}))
    return path


# A quarter of a bank-like filer: release 8-K, same-day supplement, mid-quarter
# presentation, then the 10-Q.
Q1 = [
    _filing("a1", "8-K", "2020-04-15", "2020-04-15T10:45:00.000Z", "2.02,9.01", "2020-04-15"),  # 06:45 ET
    _filing("a2", "8-K", "2020-04-15", "2020-04-15T18:00:00.000Z", "2.02,9.01", "2020-04-15"),
    _filing("a3", "10-Q", "2020-05-05", "2020-05-05T20:00:00.000Z", "", "2020-03-31"),
    _filing("a4", "8-K", "2020-06-10", "2020-06-10T14:00:00.000Z", "2.02,7.01", "2020-06-10"),  # conference
]


def test_company_filings_reads_overflow_files_too(tmp_path):
    old = [_filing("o1", "10-K", "2019-02-20", "2019-02-20T21:00:00.000Z", "", "2018-12-31")]
    with zipfile.ZipFile(_zip(tmp_path, {7: Q1}, overflow={7: old})) as zf:
        filings = se.company_filings(zf, set(zf.namelist()), 7)
        assert se.company_filings(zf, set(zf.namelist()), 8).empty

    assert set(filings["accession"]) == {"a1", "a2", "a3", "a4", "o1"}
    assert str(filings["accepted_at"].dt.tz) == "UTC"


def test_announcement_is_the_first_earnings_8k_between_period_end_and_the_report(tmp_path):
    filings = Q1 + [
        _filing("b1", "8-K/A", "2020-07-20", "2020-07-20T12:00:00.000Z", "2.02", "2020-07-20"),  # amendment
        _filing("b2", "8-K", "2020-07-21", "2020-07-21T12:00:00.000Z", "5.02", "2020-07-21"),  # not item 2.02
        _filing("b3", "10-Q", "2020-08-04", "2020-08-04T20:00:00.000Z", "", "2020-06-30"),
        _filing("b4", "10-Q/A", "2020-08-20", "2020-08-20T20:00:00.000Z", "", "2020-06-30"),
        _filing("c1", "10-K", "2004-03-01", "2004-03-01T20:00:00.000Z", "", "2003-12-31"),  # before item 2.02
    ]
    with zipfile.ZipFile(_zip(tmp_path, {7: filings})) as zf:
        result = se.announcements(se.company_filings(zf, set(zf.namelist()), 7)).set_index("period_end")

    assert list(result.index) == [pd.Timestamp("2020-03-31"), pd.Timestamp("2020-06-30")]
    q1, q2 = result.iloc[0], result.iloc[1]
    assert (q1["accession"], q1["source"], q1["extra_filings"]) == ("a1", "8-K", 1)  # a4 is after the 10-Q
    assert (q2["accession"], q2["source"], q2["report_form"]) == ("b3", "10-Q", "10-Q")  # fallback to the report


def test_item_match_is_exact_not_a_substring():
    assert se.has_earnings_item(pd.Series(["2.02,9.01", "12.02", "2.021", " 2.02", ""])).tolist() == [
        True, False, False, True, False]


def test_timing_and_reaction_date_in_new_york_time():
    accepted = pd.Series(pd.to_datetime([
        "2020-07-30T20:30:00Z",  # Thu 16:30 EDT -> after close, Fri
        "2020-01-30T21:30:00Z",  # Thu 16:30 EST -> after close, Fri
        "2020-01-30T13:00:00Z",  # Thu 08:00 EST -> before open, same day
        "2020-07-30T17:00:00Z",  # Thu 13:00 EDT -> during session, same day
        "2020-07-31T21:00:00Z",  # Fri after close -> Mon
        "2020-08-01T14:00:00Z",  # Sat -> Mon
        "2020-12-31T22:00:00Z",  # past the calendar -> NaT
    ], utc=True))

    result = se.classify_timing(accepted, SESSIONS)

    assert result["timing"].tolist() == ["after_close", "after_close", "before_open", "during_session",
                                         "after_close", "non_session_day", "after_close"]
    assert result["reaction_date"].tolist()[:6] == [pd.Timestamp(d) for d in (
        "2020-07-31", "2020-01-31", "2020-01-30", "2020-07-30", "2020-08-03", "2020-08-03")]
    assert pd.isna(result["reaction_date"].iloc[6])


def _rename(conn, old, status, cik, verified, new=None, valid=(None, None)):
    db.upsert_ticker_rename(conn, {"old_ticker": old, "new_ticker": new, "status": status, "cik": cik,
                                   "cik_verified": verified, "valid_from": valid[0], "valid_to": valid[1]})


def test_resolve_prefers_verified_decisions_over_the_current_ticker_file(conn):
    _rename(conn, "FB", "matched", 1, 1, new="META", valid=("2013-12-23", "2022-06-09"))
    _rename(conn, "GONE", "no_current_ticker", 2, 1, valid=("2010-01-01", "2015-06-30"))
    _rename(conn, "YHOO", "name_mismatch", 3, 0)
    db.upsert_symbol_reuse(conn, {"ticker": "BBT", "status": "reused", "polygon_cik": 4, "cik_verified": 1,
                                  "valid_from": "1997-12-04", "valid_to": "2019-12-09"})
    db.upsert_symbol_reuse(conn, {"ticker": "BEAM", "status": "no_listing", "holder_cik": 5})
    db.upsert_symbol_reuse(conn, {"ticker": "CPB", "status": "same_cik_name_differs", "polygon_cik": 6})
    cik_map = {"META": 1, "BBT": 99, "BEAM": 5, "CPB": 6, "BRK-B": 7}

    cik_map["META"] = 11  # today's file disagrees: the verified rename must still win, in either order
    members = ["META", "FB", "GONE", "YHOO", "BBT", "BEAM", "CPB", "BRK.B", "NONE"]

    resolved, skipped = ingest.resolve(conn, members, cik_map)

    assert ingest.resolve(conn, members[::-1], cik_map)[0] == resolved
    assert resolved == {
        "META": (1, "ticker_renames", None, None),
        "GONE": (2, "ticker_renames", "2010-01-01", "2015-06-30"),
        "BBT": (4, "symbol_reuse", "1997-12-04", "2019-12-09"),
        "CPB": (6, "sec_ticker_file", None, None),
        "BRK.B": (7, "sec_ticker_file", None, None),
    }
    assert skipped == {"unverified_cik": 1, "no_cik": 2}  # YHOO's CIK failed its name check; BEAM, NONE have none


def test_ingest_keeps_rows_inside_the_window_follows_predecessors_and_replaces(conn, tmp_path, monkeypatch):
    q3 = [_filing("d1", "8-K", "2020-10-20", "2020-10-20T20:05:00.000Z", "2.02", "2020-10-20"),
          _filing("d2", "10-Q", "2020-11-02", "2020-11-02T20:00:00.000Z", "", "2020-09-30")]
    # the predecessor keeps filing as a subsidiary: its Q3 report must not replace the successor's
    subsidiary_q3 = [_filing("e1", "10-Q", "2020-11-05", "2020-11-05T20:00:00.000Z", "", "2020-09-30")]
    monkeypatch.setitem(se.PREDECESSOR_CIKS, 8, (7,))
    with zipfile.ZipFile(_zip(tmp_path, {7: Q1 + subsidiary_q3, 8: q3})) as zf:
        tally = ingest.ingest(conn, zf, {"NEW": (8, "sec_ticker_file", None, None),
                                         "OLD": (7, "ticker_renames", "2020-06-01", "2020-12-31"),
                                         "NOFILE": (9, "sec_ticker_file", None, None)}, SESSIONS)
        stored = db.read_earnings_announcements(conn)
        ingest.ingest(conn, zf, {"NEW": (8, "sec_ticker_file", None, None)}, SESSIONS)
        rerun = db.read_earnings_announcements(conn, "NEW")

    assert tally == {"stored": 2, "no_announcements": 1, "rows": 3}  # OLD: only its Q3 report is inside its window
    assert stored.loc[stored["ticker"] == "OLD", "accession"].tolist() == ["e1"]
    new = stored[stored["ticker"] == "NEW"]
    assert new["period_end"].tolist() == ["2020-03-31", "2020-09-30"]
    assert new["accession"].tolist() == ["a1", "d1"]
    assert new["cik"].tolist() == [8, 8] and new["filer_cik"].tolist() == [7, 8]  # a1 is the predecessor's filing
    assert new["timing"].tolist() == ["before_open", "after_close"]
    assert new["reaction_date"].tolist() == ["2020-04-15", "2020-10-21"]
    assert new["accepted_at"].iloc[0] == "2020-04-15T10:45:00+00:00"
    assert rerun.drop(columns="ticker").equals(new.drop(columns="ticker").reset_index(drop=True))


def test_ingest_refuses_an_empty_calendar_and_the_gap_check_handles_an_empty_table(conn, tmp_path):
    with zipfile.ZipFile(_zip(tmp_path, {7: Q1})) as zf, pytest.raises(ValueError, match="calendar"):
        ingest.ingest(conn, zf, {"X": (7, "sec_ticker_file", None, None)}, pd.DatetimeIndex([]))
    assert ingest.reaction_gaps(conn).empty

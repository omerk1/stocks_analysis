import json
import zipfile

import pandas as pd
import pytest

from src.foundation.data_processing import bulk_sec_fundamentals_ingest as ingest
from src.foundation.data_processing import db
from src.foundation.data_processing import sec_earnings as se
from src.foundation.data_processing import sec_fundamentals as sf

SESSIONS = pd.bdate_range("2019-01-01", "2021-12-31")

# accession -> (form, filing date, acceptance time UTC)
FILINGS = {
    "q1": ("10-Q", "2020-04-30", "2020-04-30T20:30:00.000Z"),  # 16:30 New York: after the close
    "q2": ("10-Q", "2020-07-30", "2020-07-30T12:00:00.000Z"),  # 08:00: before the open
    "q3": ("10-Q", "2020-10-29", "2020-10-29T20:30:00.000Z"),
    "k": ("10-K", "2021-02-20", "2021-02-20T15:00:00.000Z"),  # a Saturday
    "q1b": ("10-Q", "2021-04-29", "2021-04-29T20:30:00.000Z"),
}


def _fact(accession, value, end, start=None):
    form, filed, _ = FILINGS.get(accession, ("10-Q", "2020-05-01", None))
    fact = {"end": end, "val": value, "accn": accession, "form": form, "filed": filed}
    return fact | ({"start": start} if start else {})


def _company(tags, unit="USD"):
    """{tag: [fact, ...]} -> a company-facts JSON; EPS tags get the per-share unit."""
    return {"facts": {"us-gaap": {
        tag: {"units": {("USD/shares" if tag.startswith("EarningsPerShare") else unit): facts}}
        for tag, facts in tags.items()}}}


def _accepted(*accessions):
    return pd.Series({a: pd.Timestamp(FILINGS[a][2]) for a in accessions})


# fiscal year 2020, cash flow reported year-to-date only (as almost every filer does)
YTD = [_fact("q1", 10, "2020-03-31", "2020-01-01"), _fact("q2", 25, "2020-06-30", "2020-01-01"),
       _fact("q3", 45, "2020-09-30", "2020-01-01"), _fact("k", 70, "2020-12-31", "2020-01-01")]


def test_quarters_are_derived_from_year_to_date_values_available_with_the_later_one():
    mistyped = _fact("k", 70, "2020-12-31", "2020-10-01")  # the full year under a fourth quarter's dates
    facts = sf.company_facts(_company({"NetCashProvidedByUsedInOperatingActivities": YTD + [mistyped]}))
    out = sf.fundamentals(facts, _accepted("q1", "q2", "q3", "k")).set_index(["period_type", "period_end"])

    quarters = out.loc["quarter"]
    assert quarters["value"].tolist() == [10, 15, 20, 25]
    assert quarters["derived"].tolist() == [0, 1, 1, 1]
    assert quarters["accession"].tolist() == ["q1", "q2", "q3", "k"]
    assert quarters["period_start"].tolist() == [pd.Timestamp(d) for d in (
        "2020-01-01", "2020-04-01", "2020-07-01", "2020-10-01")]
    assert out.loc[("year", pd.Timestamp("2020-12-31")), "value"] == 70
    assert "cumulative" not in out.index.get_level_values("period_type")  # six/nine months aren't stored


def test_reported_quarter_beats_derived_and_per_share_values_are_never_derived():
    q4 = _fact("k", 26, "2020-12-31", "2020-10-01")  # the 10-K's own fourth-quarter figure
    eps = [_fact("q1", 1.0, "2020-03-31", "2020-01-01"), _fact("q2", 2.1, "2020-06-30", "2020-01-01")]
    facts = sf.company_facts(_company({"Revenues": YTD + [q4], "EarningsPerShareDiluted": eps}))
    out = sf.fundamentals(facts, _accepted("q1", "q2", "q3", "k"))

    revenue = out[(out["concept"] == "revenue") & (out["period_type"] == "quarter")]
    assert revenue[["value", "derived"]].values.tolist()[-1] == [26, 0]
    assert out.loc[out["concept"] == "eps_diluted", "period_end"].tolist() == [pd.Timestamp("2020-03-31")]


def test_first_reported_value_wins_over_restatements_and_ties_go_to_tag_order_or_largest_revenue():
    tags = {
        # Q1 2020 first reported in q1, restated in next year's q1b
        "Revenues": [_fact("q1", 100, "2020-03-31", "2020-01-01"), _fact("q1b", 90, "2020-03-31", "2020-01-01"),
                     _fact("q1b", 30, "2020-12-31", "2020-10-01")],  # a partial figure under the preferred tag
        "SalesRevenueGoodsNet": [_fact("q1", 60, "2020-03-31", "2020-01-01")],
        "SalesRevenueNet": [_fact("q1", 200, "2019-12-31", "2019-10-01"),  # reported earlier: the first report
                            _fact("q1b", 300, "2020-12-31", "2020-10-01")],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [_fact("q1b", 210, "2019-12-31", "2019-10-01")],
        # other concepts follow tag order, not size
        "NetIncomeLoss": [_fact("q1", 8, "2020-03-31", "2020-01-01")],
        "ProfitLoss": [_fact("q1", 9, "2020-03-31", "2020-01-01"),
                       _fact("q1", 7, "2020-06-30", "2020-04-01")],  # ends after q1 was filed: a mistyped date
    }
    out = sf.fundamentals(sf.company_facts(_company(tags)), _accepted("q1", "q1b"))
    revenue = out[out["concept"] == "revenue"].set_index("period_end")

    assert revenue.loc[pd.Timestamp("2020-03-31"), ["value", "tag"]].tolist() == [100, "Revenues"]
    assert revenue.loc[pd.Timestamp("2019-12-31"), ["value", "tag"]].tolist() == [200, "SalesRevenueNet"]
    assert revenue.loc[pd.Timestamp("2020-12-31"), ["value", "tag"]].tolist() == [300, "SalesRevenueNet"]
    assert out.loc[out["concept"] == "net_income", ["period_end", "value", "tag"]].values.tolist() == [
        [pd.Timestamp("2020-03-31"), 8, "NetIncomeLoss"]]


def test_only_periodic_reports_usd_and_known_filings_count():
    tags = {"Revenues": [_fact("q1", 100, "2020-03-31", "2020-01-01"),
                         _fact("q1", 1, "2020-03-31") | {"start": "2020-01-01", "form": "8-K"},
                         _fact("unknown", 5, "2020-06-30", "2020-04-01")],
            "StockholdersEquity": [_fact("q1", 500, "2020-03-31")]}
    out = sf.fundamentals(sf.company_facts(_company(tags)), _accepted("q1"))
    assert out[["concept", "period_type", "value"]].values.tolist() == [
        ["equity", "instant", 500], ["revenue", "quarter", 100]]
    assert sf.company_facts(_company(tags, unit="EUR")).empty  # a filer reporting in euros
    assert sf.fundamentals(sf.company_facts(None), _accepted("q1")).empty


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _zips(tmp_path, facts_by_cik, filings_by_cik):
    facts_path, sub_path = tmp_path / "companyfacts.zip", tmp_path / "submissions.zip"
    with zipfile.ZipFile(facts_path, "w") as zf:
        for cik, company in facts_by_cik.items():
            zf.writestr(f"CIK{cik:010d}.json", json.dumps(company))
    with zipfile.ZipFile(sub_path, "w") as zf:
        for cik, accessions in filings_by_cik.items():
            recent = {"accessionNumber": accessions, "form": [FILINGS[a][0] for a in accessions],
                      "items": ["" for _ in accessions], "filingDate": [FILINGS[a][1] for a in accessions],
                      "acceptanceDateTime": [FILINGS[a][2] for a in accessions],
                      "reportDate": ["" for _ in accessions]}
            zf.writestr(f"CIK{cik:010d}.json", json.dumps({"filings": {"recent": recent, "files": []}}))
    return zipfile.ZipFile(facts_path), zipfile.ZipFile(sub_path)


def test_ingest_takes_predecessor_reports_before_the_successor_keeps_the_window_and_replaces(
        conn, tmp_path, monkeypatch):
    successor = _company({"Revenues": [_fact("q3", 45, "2020-09-30", "2020-07-01"),
                                       _fact("q3", 11, "2020-03-31", "2020-01-01")]})  # a restated comparative
    predecessor = _company({"Revenues": [_fact("q1", 10, "2020-03-31", "2020-01-01"),
                                         _fact("q3", 44, "2020-09-30", "2020-07-01")],  # a subsidiary's own report
                            "StockholdersEquity": [_fact("q2", 500, "2020-06-30")]})
    monkeypatch.setitem(se.PREDECESSOR_CIKS, 8, (7,))
    facts_zf, sub_zf = _zips(tmp_path, {8: successor, 7: predecessor}, {8: ["q3"], 7: ["q1", "q2", "q3"]})
    with facts_zf, sub_zf:
        tally = ingest.ingest(conn, facts_zf, sub_zf, {"NEW": (8, "sec_ticker_file", None, None),
                                                       "OLD": (7, "ticker_renames", "2020-06-01", "2020-12-31"),
                                                       "NONE": (9, "sec_ticker_file", None, None)}, SESSIONS)
        stored = db.read_fundamentals(conn)
        ingest.ingest(conn, facts_zf, sub_zf, {"NEW": (8, "sec_ticker_file", None, None)}, SESSIONS)
        rerun = db.read_fundamentals(conn, "NEW")

    assert (tally["stored"], tally["no_values"], tally["rows"]) == (2, 1, 5)
    new = stored[stored["ticker"] == "NEW"]
    assert new[["concept", "period_end", "value", "filer_cik"]].values.tolist() == [
        ["equity", "2020-06-30", 500, 7],
        ["revenue", "2020-03-31", 10, 7],  # the predecessor's first report, not the successor's comparative
        ["revenue", "2020-09-30", 45, 8]]  # the predecessor's report from the successor's time on is ignored
    assert new["available_date"].tolist() == ["2020-07-30", "2020-05-01", "2020-10-30"]  # before open / after close
    assert new["cik"].unique().tolist() == [8]
    old = stored[stored["ticker"] == "OLD"]  # only what was accepted inside its window
    assert old["accession"].tolist() == ["q2", "q3"]
    assert rerun.drop(columns="ticker").equals(new.drop(columns="ticker").reset_index(drop=True))


def test_checks_add_up_quarters_and_measure_coverage(conn, tmp_path):
    facts_zf, sub_zf = _zips(tmp_path, {7: _company({"Revenues": YTD})}, {7: ["q1", "q2", "q3", "k"]})
    with facts_zf, sub_zf:
        ingest.ingest(conn, facts_zf, sub_zf, {"X": (7, "sec_ticker_file", None, None)}, SESSIONS)
    for period_end in ("2020-03-31", "2020-06-30", "2021-03-31"):
        conn.execute("INSERT INTO earnings_announcements VALUES ('X', ?, 7, 'sec_ticker_file', 7, '10-Q', "
                     "'2020-05-01', 'a', '8-K', '2020-04-28T20:00:00+00:00', 'after_close', '2020-04-29', 0)",
                     (period_end,))

    assert ingest.quarters_vs_year(conn).loc["revenue", ["four_quarters", "adds_up"]].tolist() == [1, 1.0]
    table = ingest.coverage(conn)
    assert table.loc["2020", ["periods", "revenue"]].tolist() == [2, 1.0]
    assert table.loc["2021", "revenue"] == 0.0

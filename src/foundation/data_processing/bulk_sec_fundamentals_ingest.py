"""python -m src.foundation.data_processing.bulk_sec_fundamentals_ingest [--indices sp500,nasdaq100] [--check]

Fills `fundamentals`: for every all-time member of `--indices`, the
first-reported revenue, earnings, cash flow and balance-sheet values per
quarter and fiscal year (see `sec_fundamentals` for what is kept and why).
Entirely local: reads `companyfacts.zip`, `submissions.zip` (acceptance times)
and `company_tickers.json` from `<raw data dir>/sec`.

Tickers are tied to CIKs exactly as for the earnings dates
(`bulk_sec_earnings_ingest.resolve`, same precedence and validity windows),
and a predecessor CIK (`sec_earnings.PREDECESSOR_CIKS`) fills each concept's
periods before the earliest one found under the current CIK. A ticker with a
validity window keeps only values accepted inside it.

Each resolved ticker's rows are deleted and rewritten in one transaction;
stored tickers the run didn't resolve are listed, not deleted. `--check`
prints coverage against the earnings announcement periods, how often four
quarters add up to the fiscal year, and how long after the announcement the
values become available.
"""

from __future__ import annotations

import argparse
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.data_processing import bulk_sec_earnings_ingest as earnings
from src.foundation.data_processing import db
from src.foundation.data_processing import sec_companyfacts as sec
from src.foundation.data_processing import sec_earnings as se
from src.foundation.data_processing import sec_fundamentals as sf
from src.foundation.utils.config_loader import load_config

ADDITIVE = [c for c, (_, _, additive, _) in sf.CONCEPTS.items() if additive]


def ticker_rows(parsed, cik: int, cik_source: str, valid_from, valid_to, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """The rows to store for one ticker: its CIK's values, then each
    predecessor's for the periods before the earliest one found so far, per
    concept and period type. `parsed(cik)` gives a CIK's `sf.fundamentals`."""
    key = ["concept", "period_type"]
    parts = []
    for c in (cik, *se.PREDECESSOR_CIKS.get(cik, ())):
        found = parsed(c).assign(filer_cik=c)
        if parts:
            so_far = pd.concat(parts).groupby(key, as_index=False)["period_end"].min()
            found = found.merge(so_far.rename(columns={"period_end": "earliest"}), on=key, how="left")
            found = found[found["earliest"].isna() | (found["period_end"] < found["earliest"])].drop(
                columns="earliest")
        if len(found):
            parts.append(found)
    if not parts:
        return pd.DataFrame()
    rows = pd.concat(parts, ignore_index=True)
    rows = rows[earnings.inside_window(rows["accepted_at"], valid_from, valid_to)].reset_index(drop=True)
    available = se.classify_timing(rows["accepted_at"], sessions)["reaction_date"]
    return rows.assign(available_date=available, cik=cik, cik_source=cik_source)


def ingest(conn: sqlite3.Connection, facts_zf: zipfile.ZipFile, submissions_zf: zipfile.ZipFile, resolved: dict,
           sessions: pd.DatetimeIndex) -> Counter:
    """Rows are per price ticker, so share classes of one company repeat its
    values: count companies by cik, not by ticker."""
    if len(sessions) == 0:
        raise ValueError(f"No session calendar: {earnings.CALENDAR_TICKER} has no bars")
    facts_available, submissions_available = set(facts_zf.namelist()), set(submissions_zf.namelist())
    cache: dict[int, pd.DataFrame] = {}
    tally: Counter = Counter()

    def parsed(cik: int) -> pd.DataFrame:
        if cik not in cache:
            company = sec.read_company(facts_zf, cik) if f"CIK{cik:010d}.json" in facts_available else None
            facts = sf.company_facts(company)
            accepted = sf.accepted_times(se.company_filings(submissions_zf, submissions_available, cik))
            known = facts["accession"].map(accepted).notna().sum() if len(facts) and len(accepted) else 0
            tally["facts_without_filing"] += len(facts) - int(known)
            cache[cik] = sf.fundamentals(facts, accepted)
        return cache[cik]

    for ticker, (cik, cik_source, valid_from, valid_to) in sorted(resolved.items()):
        rows = ticker_rows(parsed, cik, cik_source, valid_from, valid_to, sessions)
        db.replace_fundamentals(conn, ticker, rows)
        tally["stored" if len(rows) else "no_values"] += 1
        tally["rows"] += len(rows)
    return tally


def _company_rows(conn: sqlite3.Connection, start: str, end: str) -> pd.DataFrame:
    """One row per (cik, concept, period_type, period_end): share classes once."""
    rows = pd.read_sql_query(
        "SELECT cik, concept, period_type, period_start, period_end, value, derived, available_date "
        "FROM fundamentals WHERE period_end BETWEEN ? AND ?", conn, params=[start, end])
    return rows.drop_duplicates(["cik", "concept", "period_type", "period_end"])


def coverage(conn: sqlite3.Connection, start: str = "2010-01-01", end: str = "2021-12-31") -> pd.DataFrame:
    """Share of earnings announcement periods (company, period end) with a
    quarterly value per concept (instant: a balance-sheet value), by year,
    and the share of quarters that were derived."""
    periods = pd.read_sql_query(
        "SELECT DISTINCT cik, period_end FROM earnings_announcements WHERE period_end BETWEEN ? AND ?",
        conn, params=[start, end])
    rows = _company_rows(conn, start, end)
    rows = rows[rows["period_type"] != "year"]
    hit = periods.merge(rows, on=["cik", "period_end"], how="left")
    have = hit.pivot_table(index=["cik", "period_end"], columns="concept", values="value", aggfunc="size")
    have = periods.set_index(["cik", "period_end"]).join(have).notna()
    have = have.drop(columns=[c for c in have.columns if c not in sf.CONCEPTS])
    table = have.groupby(have.index.get_level_values("period_end").str[:4]).mean().round(3)
    table.insert(0, "periods", have.groupby(have.index.get_level_values("period_end").str[:4]).size())
    quarters = rows[rows["period_type"] == "quarter"]
    table.loc["derived share", :] = quarters.groupby("concept")["derived"].mean().round(3)
    return table.rename_axis("year")


def quarters_vs_year(conn: sqlite3.Connection, start: str = "2010-01-01", end: str = "2021-12-31",
                     tolerance: float = 0.01) -> pd.DataFrame:
    """For additive concepts: fiscal years whose four quarters are all stored,
    and the share where they add up to the year's value within `tolerance`."""
    rows = _company_rows(conn, start, end)
    rows = rows[rows["concept"].isin(ADDITIVE)]
    years = rows[rows["period_type"] == "year"]
    quarters = rows[rows["period_type"] == "quarter"]
    out = []
    for concept, ys in years.groupby("concept"):
        qs = quarters[quarters["concept"] == concept]
        joined = ys.merge(qs, on="cik", suffixes=("", "_q"))
        inside = (joined["period_end_q"] > joined["period_start"]) & (joined["period_end_q"] <= joined["period_end"])
        summed = joined[inside].groupby(["cik", "period_end"]).agg(n=("value_q", "size"), total=("value_q", "sum"))
        full = ys.set_index(["cik", "period_end"]).join(summed, how="inner").query("n == 4")
        ok = (full["total"] - full["value"]).abs() <= tolerance * full["value"].abs()
        out.append({"concept": concept, "years": len(ys), "four_quarters": len(full),
                    "adds_up": round(float(ok.mean()), 3) if len(full) else np.nan})
    return pd.DataFrame(out).set_index("concept")


def lag_after_announcement(conn: sqlite3.Connection, start: str = "2010-01-01",
                           end: str = "2021-12-31") -> pd.DataFrame:
    """Sessions between the earnings reaction date and the day net income
    becomes available, by announcement source: the 10-Q/10-K usually follows
    the press release by days or weeks, never precedes it."""
    ann = pd.read_sql_query(
        "SELECT DISTINCT cik, period_end, source, reaction_date FROM earnings_announcements "
        "WHERE period_end BETWEEN ? AND ? AND reaction_date IS NOT NULL", conn, params=[start, end])
    ni = _company_rows(conn, start, end).query("concept == 'net_income' and period_type == 'quarter'")
    both = ann.merge(ni, on=["cik", "period_end"]).dropna(subset=["available_date"])
    days = (pd.to_datetime(both["available_date"]) - pd.to_datetime(both["reaction_date"])).dt.days
    return days.groupby(both["source"]).describe(percentiles=[0.1, 0.5, 0.9])[
        ["count", "min", "10%", "50%", "90%"]].assign(before=(days < 0).groupby(both["source"]).mean().round(4))


def main():
    parser = argparse.ArgumentParser(description="Reported financials from SEC EDGAR's bulk company facts")
    parser.add_argument("--indices", default=earnings.DEFAULT_INDICES,
                        help="Comma-separated index names (all-time members)")
    parser.add_argument("--check", action="store_true", help="Only print the checks")
    args = parser.parse_args()

    config = load_config()
    sec_dir = Path(config.data_paths.raw) / "sec"
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)
    if not args.check:
        paths = [sec_dir / name for name in ("companyfacts.zip", "submissions.zip", "company_tickers.json")]
        for p in paths:
            if not p.exists():
                raise SystemExit(f"Missing {p} -- download it from sec.gov's EDGAR bulk data page first.")
        tickers = db.read_universe_tickers(conn, args.indices)
        resolved, skipped = earnings.resolve(conn, tickers, sec.load_cik_map(paths[2]))
        sessions = db.read_bars(conn, "bars_1d", earnings.CALENDAR_TICKER, db.YFINANCE_SPLIT_ONLY).index
        with zipfile.ZipFile(paths[0]) as facts_zf, zipfile.ZipFile(paths[1]) as submissions_zf:
            tally = ingest(conn, facts_zf, submissions_zf, resolved, sessions)
        print(f"{len(tickers)} members -> {len(resolved)} price tickers: stored {tally['stored']} "
              f"({tally['rows']} rows), none found {tally['no_values']}; skipped -- CIK failed its name check "
              f"{skipped['unverified_cik']}, no CIK {skipped['no_cik']}; facts whose filing isn't in the "
              f"filing index (dropped): {tally['facts_without_filing']}")
        stored = pd.read_sql_query("SELECT DISTINCT ticker FROM fundamentals", conn)["ticker"]
        stale = sorted(set(stored) - set(resolved))
        if stale:
            print(f"{len(stale)} stored tickers not resolved this run (rows kept; delete them by hand if the "
                  f"decision changed): {', '.join(stale[:20])}")
    pd.set_option("display.width", 250)
    print(coverage(conn).to_string())
    print(quarters_vs_year(conn).to_string())
    print(lag_after_announcement(conn).to_string())
    conn.close()


if __name__ == "__main__":
    main()

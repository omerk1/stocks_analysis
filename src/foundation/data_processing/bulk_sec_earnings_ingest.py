"""python -m src.foundation.data_processing.bulk_sec_earnings_ingest [--indices sp500,nasdaq100] [--check]

Fills `earnings_announcements`: for every all-time member of `--indices`, one
row per reporting period with the day its results became public (see
`sec_earnings` for how an announcement is picked and timed). Entirely local:
reads `submissions.zip` and `company_tickers.json` from `<raw data dir>/sec`.

Tying a member's ticker to a CIK, most specific first:
1. `ticker_renames` with a verified CIK: a renamed member (FB) is stored under
   its price symbol (META), whole history; a delisted one under its own
   symbol, only inside its verified window -- outside it the symbol may be
   another company's.
2. `symbol_reuse` `reused` with a verified CIK: the member's own CIK, inside
   its window. Unverified CIKs and `no_listing`/`no_holder` rows are skipped:
   SEC's ticker file would give the symbol's current holder.
3. SEC's ticker file (today's symbols), whole history.

Each ticker's rows are deleted and rewritten in one transaction, so a rerun
against a newer download never leaves stale rows. `--check` prints coverage
and the reaction-gap check from what's stored, without re-ingesting.
"""

from __future__ import annotations

import argparse
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.data_processing import db
from src.foundation.data_processing import sec_companyfacts as sec
from src.foundation.data_processing import sec_earnings as se
from src.foundation.utils.config_loader import load_config

DEFAULT_INDICES = "sp500,nasdaq100"
CALENDAR_TICKER = "SPY"


def resolve(conn: sqlite3.Connection, tickers: list[str], cik_map: dict[str, int]) -> tuple[dict, Counter]:
    """{price ticker: (cik, cik_source, valid_from, valid_to)} for `tickers`,
    and a tally of members that couldn't be tied to a CIK."""
    renames = db.read_ticker_renames(conn, matched_only=False).set_index("old_ticker")
    reuse = db.read_symbol_reuse(conn).set_index("ticker")
    out, skipped = {}, Counter()
    for t in tickers:
        if t in renames.index:
            r = renames.loc[t]
            if r["cik_verified"] != 1 or pd.isna(r["cik"]):
                skipped["unverified_cik"] += 1
            elif r["status"] == "matched":
                out[r["new_ticker"]] = (int(r["cik"]), "ticker_renames", None, None)
            else:
                out[t] = (int(r["cik"]), "ticker_renames", r["valid_from"], r["valid_to"])
        elif t in reuse.index and reuse.loc[t, "status"] not in ("same_company", "same_cik_name_differs"):
            r = reuse.loc[t]
            if r["status"] == "reused" and r["cik_verified"] == 1 and pd.notna(r["polygon_cik"]):
                out[t] = (int(r["polygon_cik"]), "symbol_reuse", r["valid_from"], r["valid_to"])
            else:
                skipped["unverified_cik"] += 1
        elif sec.to_sec_ticker(t) in cik_map:
            out.setdefault(t, (cik_map[sec.to_sec_ticker(t)], "sec_ticker_file", None, None))
        else:
            skipped["no_cik"] += 1
    return out, skipped


def ticker_rows(zf: zipfile.ZipFile, available: set[str], cik: int, cik_source: str, valid_from, valid_to,
                sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """The rows to store for one ticker: its CIK's, then each predecessor's
    for the periods before the earliest one found so far."""
    parts, earliest = [], None
    for c in (cik, *se.PREDECESSOR_CIKS.get(cik, ())):
        found = se.announcements(se.company_filings(zf, available, c))
        if earliest is not None:
            found = found[found["period_end"] < earliest]
        if len(found):
            earliest = found["period_end"].min()
        parts.append(found)
    rows = pd.concat(parts, ignore_index=True).sort_values("period_end").dropna(subset=["accepted_at"])
    accepted_day = rows["accepted_at"].dt.tz_convert(se.MARKET_TZ).dt.tz_localize(None).dt.normalize()
    keep = pd.Series(True, index=rows.index)
    if valid_from is not None:
        keep &= accepted_day >= pd.Timestamp(valid_from)
    if valid_to is not None:
        keep &= accepted_day <= pd.Timestamp(valid_to)
    rows = rows[keep].reset_index(drop=True)
    return pd.concat([rows, se.classify_timing(rows["accepted_at"], sessions)], axis=1).assign(
        cik=cik, cik_source=cik_source)


def ingest(conn: sqlite3.Connection, zf: zipfile.ZipFile, resolved: dict, sessions: pd.DatetimeIndex) -> Counter:
    available = set(zf.namelist())
    tally: Counter = Counter()
    for ticker, (cik, cik_source, valid_from, valid_to) in sorted(resolved.items()):
        rows = ticker_rows(zf, available, cik, cik_source, valid_from, valid_to, sessions)
        db.replace_earnings_announcements(conn, ticker, rows)
        tally["stored" if len(rows) else "no_announcements"] += 1
        tally["rows"] += len(rows)
    return tally


def reaction_gaps(conn: sqlite3.Connection, start: str = "2009-01-01", end: str = "2021-12-31") -> pd.DataFrame:
    """Median |open / previous close - 1| on the session before, on, and after
    each stored reaction date, by source and timing. If reaction dates are
    right, the gap peaks on day 0. Bars on the traded (split-only) basis."""
    ann = pd.read_sql_query(
        "SELECT ticker, reaction_date, source, timing FROM earnings_announcements "
        "WHERE reaction_date BETWEEN ? AND ?", conn, params=[start, end])
    out = []
    for ticker, group in ann.groupby("ticker"):
        bars = pd.read_sql_query(
            "SELECT substr(timestamp, 1, 10) AS date, open, close FROM bars_1d WHERE ticker = ? AND source IN (?, ?) "
            "ORDER BY timestamp", conn, params=[ticker, db.YFINANCE_SPLIT_ONLY, db.TIINGO_SPLIT_ONLY])
        bars = bars.drop_duplicates("date").reset_index(drop=True)
        if len(bars) < 2:
            continue
        gap = (bars["open"] / bars["close"].shift(1) - 1).abs().to_numpy()
        pos = pd.Index(bars["date"]).get_indexer(group["reaction_date"])
        ok = (pos >= 2) & (pos + 1 < len(bars))  # all three days have a gap
        out.append(pd.DataFrame({"source": group["source"].to_numpy()[ok], "timing": group["timing"].to_numpy()[ok],
                                 **{offset: gap[pos[ok] + offset] for offset in (-1, 0, 1)}}))
    gaps = pd.concat(out, ignore_index=True).dropna()
    by = gaps.groupby(["source", "timing"])
    table = by[[-1, 0, 1]].median().mul(100).round(2)
    table["n"] = by.size()
    # share of events whose biggest gap of the three days is on the reaction date
    table["peak_on_day0"] = (gaps[[-1, 0, 1]].idxmax(axis=1) == 0).groupby([gaps["source"], gaps["timing"]]).mean().round(3)
    return table


def coverage(conn: sqlite3.Connection, start: str = "2010-01-01", end: str = "2021-12-31") -> pd.DataFrame:
    """Per year: tickers with rows, announcements per ticker, share from 8-Ks."""
    ann = pd.read_sql_query(
        "SELECT ticker, period_end, source FROM earnings_announcements WHERE period_end BETWEEN ? AND ?",
        conn, params=[start, end])
    ann["year"] = ann["period_end"].str[:4]
    return ann.groupby("year").agg(
        tickers=("ticker", "nunique"), rows=("ticker", "size"),
        per_ticker=("ticker", lambda s: round(len(s) / s.nunique(), 2)),
        from_8k=("source", lambda s: round(float(np.mean(s == "8-K")), 3)))


def main():
    parser = argparse.ArgumentParser(description="Earnings announcement dates from SEC EDGAR's bulk submissions")
    parser.add_argument("--indices", default=DEFAULT_INDICES, help="Comma-separated index names (all-time members)")
    parser.add_argument("--check", action="store_true", help="Only print coverage and the gap check")
    args = parser.parse_args()

    config = load_config()
    sec_dir = Path(config.data_paths.raw) / "sec"
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)
    if not args.check:
        zip_path, tickers_path = sec_dir / "submissions.zip", sec_dir / "company_tickers.json"
        for p in (zip_path, tickers_path):
            if not p.exists():
                raise SystemExit(f"Missing {p} -- download it from sec.gov's EDGAR bulk data page first.")
        tickers = db.read_universe_tickers(conn, args.indices)
        resolved, skipped = resolve(conn, tickers, sec.load_cik_map(tickers_path))
        sessions = db.read_bars(conn, "bars_1d", CALENDAR_TICKER, db.YFINANCE_SPLIT_ONLY).index
        with zipfile.ZipFile(zip_path) as zf:
            tally = ingest(conn, zf, resolved, sessions)
        print(f"{len(tickers)} members -> {len(resolved)} price tickers: stored {tally['stored']} "
              f"({tally['rows']} rows), none found {tally['no_announcements']}; skipped -- "
              f"unverified CIK {skipped['unverified_cik']}, no SEC ticker match {skipped['no_cik']}")
    pd.set_option("display.width", 200)
    print(coverage(conn).to_string())
    print(reaction_gaps(conn).to_string())
    conn.close()


if __name__ == "__main__":
    main()

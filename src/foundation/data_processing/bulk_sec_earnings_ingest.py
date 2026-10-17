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

Each resolved ticker's rows are deleted and rewritten in one transaction, so
a rerun against a newer download never leaves stale rows for it; stored
tickers the run didn't resolve are listed, not deleted. `--check` prints coverage
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
    and a tally of members that couldn't be tied to a CIK: `unverified_cik`
    (a CIK whose name check failed) or `no_cik` (none found at all), plus
    `shadowed` (a price symbol two members tie to different CIKs).

    When two members land on one price ticker (FB and META), the more
    specific source wins, whatever the order of `tickers`."""
    renames = db.read_ticker_renames(conn, matched_only=False).set_index("old_ticker")
    reuse = db.read_symbol_reuse(conn).set_index("ticker")
    out, skipped = {}, Counter()

    def put(ticker, entry):
        if ticker in out and out[ticker][0] != entry[0]:
            skipped["shadowed"] += 1  # two companies for one price symbol; the more specific source wins
        if ticker not in out or _PRECEDENCE[entry[1]] < _PRECEDENCE[out[ticker][1]]:
            out[ticker] = entry

    for t in tickers:
        if t in renames.index:
            r = renames.loc[t]
            if pd.isna(r["cik"]):
                skipped["no_cik"] += 1
            elif r["cik_verified"] != 1:
                skipped["unverified_cik"] += 1
            elif r["status"] == "matched":
                put(r["new_ticker"], (int(r["cik"]), "ticker_renames", None, None))
            else:
                put(t, (int(r["cik"]), "ticker_renames", r["valid_from"], r["valid_to"]))
        elif t in reuse.index and reuse.loc[t, "status"] not in ("same_company", "same_cik_name_differs"):
            r = reuse.loc[t]
            if r["status"] != "reused" or pd.isna(r["polygon_cik"]):
                skipped["no_cik"] += 1
            elif r["cik_verified"] != 1:
                skipped["unverified_cik"] += 1
            else:
                put(t, (int(r["polygon_cik"]), "symbol_reuse", r["valid_from"], r["valid_to"]))
        elif sec.to_sec_ticker(t) in cik_map:
            put(t, (cik_map[sec.to_sec_ticker(t)], "sec_ticker_file", None, None))
        else:
            skipped["no_cik"] += 1
    return out, skipped


_PRECEDENCE = {"ticker_renames": 0, "symbol_reuse": 1, "sec_ticker_file": 2}


def ticker_rows(parsed, cik: int, cik_source: str, valid_from, valid_to, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """The rows to store for one ticker: its CIK's, then each predecessor's
    for the periods before the earliest one found so far. `parsed(cik)` gives
    a CIK's announcements; `filer_cik` is the CIK whose filing each row is."""
    parts, earliest = [], None
    for c in (cik, *se.PREDECESSOR_CIKS.get(cik, ())):
        found = parsed(c).assign(filer_cik=c)
        if earliest is not None:
            found = found[found["period_end"] < earliest]
        if len(found):
            earliest = found["period_end"].min()
        parts.append(found)
    rows = pd.concat(parts, ignore_index=True).sort_values("period_end").dropna(subset=["accepted_at"])
    rows = rows[inside_window(rows["accepted_at"], valid_from, valid_to)].reset_index(drop=True)
    return pd.concat([rows, se.classify_timing(rows["accepted_at"], sessions)], axis=1).assign(
        cik=cik, cik_source=cik_source)


def inside_window(accepted_at: pd.Series, valid_from, valid_to) -> pd.Series:
    """Accepted (New York day) inside a ticker's [valid_from, valid_to]; None is open-ended."""
    accepted_day = accepted_at.dt.tz_convert(se.MARKET_TZ).dt.tz_localize(None).dt.normalize()
    keep = pd.Series(True, index=accepted_at.index)
    if valid_from is not None:
        keep &= accepted_day >= pd.Timestamp(valid_from)
    if valid_to is not None:
        keep &= accepted_day <= pd.Timestamp(valid_to)
    return keep


def ingest(conn: sqlite3.Connection, zf: zipfile.ZipFile, resolved: dict, sessions: pd.DatetimeIndex) -> Counter:
    """Rows are per price ticker, so share classes of one company (GOOG and
    GOOGL) each get the company's announcements: count events by
    (cik, period_end), not by row."""
    if len(sessions) == 0:
        raise ValueError(f"No session calendar: {CALENDAR_TICKER} has no bars")
    available = set(zf.namelist())
    cache: dict[int, pd.DataFrame] = {}

    def parsed(cik: int) -> pd.DataFrame:
        if cik not in cache:
            cache[cik] = se.announcements(se.company_filings(zf, available, cik))
        return cache[cik]

    tally: Counter = Counter()
    for ticker, (cik, cik_source, valid_from, valid_to) in sorted(resolved.items()):
        rows = ticker_rows(parsed, cik, cik_source, valid_from, valid_to, sessions)
        db.replace_earnings_announcements(conn, ticker, rows)
        tally["stored" if len(rows) else "no_announcements"] += 1
        tally["rows"] += len(rows)
    return tally


def reaction_gaps(conn: sqlite3.Connection, start: str = "2009-01-01", end: str = "2021-12-31") -> pd.DataFrame:
    """Median |open / previous close - 1| on the session before, on, and after
    each stored reaction date, by source and timing. If reaction dates are
    right, the gap peaks on day 0. Bars on the traded (split-only) basis, from
    whichever source has more of them for the ticker (never mixed); one event
    per company period, so share classes aren't counted twice."""
    ann = pd.read_sql_query(
        "SELECT ticker, cik, period_end, reaction_date, source, timing FROM earnings_announcements "
        "WHERE reaction_date BETWEEN ? AND ? ORDER BY ticker", conn, params=[start, end])
    out = []
    for ticker, group in ann.groupby("ticker"):
        bars = max((db.read_bars(conn, "bars_1d", ticker, s) for s in (db.YFINANCE_SPLIT_ONLY, db.TIINGO_SPLIT_ONLY)),
                   key=len)
        if len(bars) < 3:
            continue
        gap = (bars["open"] / bars["close"].shift(1) - 1).abs().to_numpy()
        pos = bars.index.normalize().get_indexer(pd.to_datetime(group["reaction_date"]))
        ok = (pos >= 2) & (pos + 1 < len(bars))  # all three days have a gap
        out.append(pd.DataFrame({"ticker": ticker, "cik": group["cik"].to_numpy()[ok],
                                 "period_end": group["period_end"].to_numpy()[ok],
                                 "source": group["source"].to_numpy()[ok], "timing": group["timing"].to_numpy()[ok],
                                 **{offset: gap[pos[ok] + offset] for offset in (-1, 0, 1)}}))
    if not out:
        return pd.DataFrame()
    gaps = pd.concat(out, ignore_index=True).dropna().drop_duplicates(["cik", "period_end"])
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
              f"CIK failed its name check {skipped['unverified_cik']}, no CIK {skipped['no_cik']}; "
              f"{skipped['shadowed']} members tie a price symbol to a second company (more specific source kept)")
        stale = sorted(set(db.read_earnings_announcements(conn)["ticker"]) - set(resolved))
        if stale:
            print(f"{len(stale)} stored tickers not resolved this run (rows kept; --indices narrower, or a "
                  f"decision changed -- delete them by hand if so): {', '.join(stale[:20])}")
    pd.set_option("display.width", 200)
    print(coverage(conn).to_string())
    print(reaction_gaps(conn).to_string())
    conn.close()


if __name__ == "__main__":
    main()

"""python -m src.foundation.data_processing.bulk_tiingo_ingest [--since 2009-01-01] [--limit N] [--refresh]

Daily bars from Tiingo for index members that have no prices anywhere else:
the members `ticker_renames.py` checked and could not map to a current symbol
(delisted, acquired, or a symbol it couldn't verify). Without their history
every point-in-time universe is survivors-only. Stored on both price bases,
under sources `tiingo` (splits + dividends) and `tiingo_split_only`, keyed by
the membership symbol.

A listing is stored only when it's the same company, checked, not assumed --
the same rule as `ticker_renames.py`, because symbols get reused (EMC is an
ETF today; BBT on Tiingo is Beacon Financial, not BB&T):
1. Tiingo's public ticker list (free, no request budget): the symbol's
   *latest* listing -- the only one the API serves -- must be a stock whose
   date range overlaps the membership window. Otherwise `symbol_reused` (an
   older listing overlaps but isn't reachable) or `not_in_tiingo`.
2. Tiingo's metadata name must match the membership-era name Polygon gave
   `ticker_renames` (`old_name`), by the same token-Jaccard test
   (`ticker_renames.names_match`). No reference name -> `no_reference_name`.
3. The bars must cover at least `MIN_COVERAGE` of the market's trading days
   inside the membership window (clipped to `--since`), else `low_coverage`.

The full Tiingo history of an accepted listing is stored, not just the
membership window, so lookback features have their warmup. Every decision is
saved to `tiingo_listings` right after it's made: an interrupted run resumes,
and only `stored` rows have bars. Two requests per checked symbol at 50/hour.
"""

from __future__ import annotations

import argparse
import re
import sqlite3

import pandas as pd
import requests
from dotenv import load_dotenv

from src.foundation.data_processing import db
from src.foundation.data_processing import ticker_renames as tr
from src.foundation.data_processing.tiingo_client import TiingoClient, supported_tickers, to_bars, to_splits
from src.foundation.market_common.vendor_overrides import PREFER_TIINGO
from src.foundation.utils.config_loader import load_config

MIN_COVERAGE = tr.MIN_COVERAGE
SPLITS_JOB = "tiingo_splits"
PREFERRED_START = "1970-01-01"  # Tiingo answers from the listing's first bar
_NO_PRICES = pd.DataFrame({"splitFactor": pd.Series(dtype=float)})


def targets(conn: sqlite3.Connection, since: str) -> pd.DataFrame:
    """Members `ticker_renames` couldn't map, whose window reaches past
    `since` and that still have no yfinance bars. Columns: ticker, ref_name,
    valid_from, valid_to."""
    return pd.read_sql_query(
        """
        SELECT old_ticker AS ticker, old_name AS ref_name, valid_from, valid_to
        FROM ticker_renames r
        WHERE status != 'matched' AND valid_to >= ?
          AND NOT EXISTS (SELECT 1 FROM bars_1d b WHERE b.ticker = r.old_ticker AND b.source = ?)
        ORDER BY old_ticker
        """,
        conn, params=[since, db.YFINANCE],
    )


def tiingo_symbol(ticker: str) -> str:
    """Tiingo spells share classes with '-' (BRK-B); this repo with '.'."""
    return ticker.replace(".", "-")


def check_listing(listings: pd.DataFrame, symbol: str, start: str, end: str) -> tuple[str | None, dict]:
    """Step 1, from the public ticker list. Returns (rejection status or None,
    the latest listing's fields)."""
    rows = listings[listings["ticker"].str.upper() == symbol.upper()].fillna({"startDate": "", "endDate": ""})
    if rows.empty:
        return "not_in_tiingo", {}
    latest = rows.sort_values(["endDate", "startDate"]).iloc[-1]
    info = {"tiingo_start": latest["startDate"], "tiingo_end": latest["endDate"]}
    overlaps = (rows["startDate"] <= end) & (rows["endDate"] >= start)
    if latest["assetType"] == "Stock" and latest["startDate"] <= end and latest["endDate"] >= start:
        return None, info
    if overlaps.any():
        older = rows[overlaps].iloc[0]
        return "symbol_reused", {**info, "detail": f"older listing {older['startDate']}..{older['endDate']} not served"}
    return "not_in_tiingo", {**info, "detail": "no listing overlaps the membership window"}


# Listing noise Polygon's ADR names carry and Tiingo's don't ("Arm Holdings plc
# American Depositary Shares" vs "Arm Holdings plc.").
_ADR_NOISE = re.compile(r"\bAMERICAN DEPOSIT[AO]RY (SHARES?|RECEIPTS?)\b|\bADS\b|\bADRS?\b", re.IGNORECASE)


# Reviewed by hand (2026-10-05): the same company under a later or misspelled
# name. Each holds only for this exact Tiingo name, so a symbol Tiingo later
# hands to someone else fails the check again.
REVIEWED_SAME_COMPANY = {
    "K": "Kellanova",  # Kellogg, renamed 2023
    "JNY": "The Jones Group Inc",  # Jones Apparel Group, renamed 2010
    "GMCR": "Green Mountain Coffee Roasters Inc",  # renamed Keurig Green Mountain 2014
    "ODP": "ODP Corporation (The)",  # Office Depot's 2020 holding-company reorg
    "MYL": "Mylan N.V.",  # Mylan Inc's 2015 inversion, shares exchanged 1:1
    "SOV": "Santander Holdings USA Inc",  # bars end 2009-01-29, before Santander's takeover
    "DISCK": "Warner Bros. Discovery Inc - Series C",  # Discovery Series C, renamed 2022
    "ROH": "ROHM HAAS CO",  # Polygon spells it "ROHM AND HASS"
    "SIAL": "SigmaAldrich Corp",
    "SHPG": "Shire PLC ADR",  # Polygon: "Shire pic"
    "CTRX": "Catamaran Corp USA",
    "CVC": "Cablevision Systems Corp",
    "HAR": "Harman International Industries IncDE",
}


def same_company(tiingo_name: str | None, ref_name: str, ticker: str | None = None) -> bool:
    """`ticker_renames.names_match`, after dropping ADR wording, plus two
    fallbacks: the identity tokens agree once spaces are ignored ("Avalon Bay
    Communities" vs "Avalonbay Communities Inc"), or the pair was reviewed by
    hand (`REVIEWED_SAME_COMPANY`)."""
    if not tiingo_name:
        return False
    if ticker is not None and REVIEWED_SAME_COMPANY.get(ticker) == tiingo_name:
        return True
    tiingo_name, ref_name = _ADR_NOISE.sub(" ", tiingo_name), _ADR_NOISE.sub(" ", ref_name)
    if tr.names_match(tiingo_name, [ref_name]):
        return True
    return _compact(tiingo_name) == _compact(ref_name) != ""


def _compact(name: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", name.upper()).replace("&", " AND ")
    tokens = (tr._NAME_ABBREVIATIONS.get(t, t) for t in re.split(r"[^A-Z0-9]+", text))
    return "".join(t for t in tokens if t and t not in tr._NAME_NOISE)


def coverage(conn: sqlite3.Connection, bars: pd.DataFrame, start: str, end: str) -> float:
    """Share of the market's trading days in [start, end] with a bar."""
    market = conn.execute(
        "SELECT DISTINCT substr(timestamp, 1, 10) FROM bars_1d WHERE ticker = ? AND source = ? "
        "AND timestamp >= ? AND timestamp <= ?",
        [tr.CALENDAR_TICKER, tr.PRICE_SOURCE, start, f"{end}T23:59:59"],
    ).fetchall()
    days = {r[0] for r in market}
    if not days:
        return 0.0
    have = set(bars.index.strftime("%Y-%m-%d"))
    return len(days & have) / len(days)


def decide(conn: sqlite3.Connection, client: TiingoClient, listings: pd.DataFrame, target, since: str) -> dict:
    """Check one target and, if it passes, store its bars. Returns the
    `tiingo_listings` row."""
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    start, end = max(target.valid_from, since), min(target.valid_to, today)
    row = {"ticker": target.ticker, "ref_name": target.ref_name,
           "valid_from": target.valid_from, "valid_to": target.valid_to}
    if pd.isna(target.ref_name) or not target.ref_name:
        return {**row, "status": "no_reference_name"}
    symbol = tiingo_symbol(target.ticker)
    rejected, info = check_listing(listings, symbol, start, end)
    row.update(info)
    if rejected:
        return {**row, "status": rejected}

    meta = client.metadata(symbol)
    if meta is None:
        return {**row, "status": "not_in_tiingo", "detail": "metadata 404"}
    row["tiingo_name"] = meta.get("name")
    if not same_company(meta.get("name"), target.ref_name, target.ticker):
        return {**row, "status": "name_mismatch"}

    prices = client.daily_prices(symbol, meta.get("startDate") or info["tiingo_start"],
                                 meta.get("endDate") or info["tiingo_end"])
    if prices is None or prices.empty:
        return {**row, "status": "no_prices"}
    total_return = to_bars(prices, split_only=False)
    cov = coverage(conn, total_return, start, end)
    row.update(coverage=round(cov, 4), n_bars=len(total_return))
    if cov < MIN_COVERAGE:
        return {**row, "status": "low_coverage"}
    db.upsert_bars(conn, "bars_1d", target.ticker, db.TIINGO, total_return)
    db.upsert_bars(conn, "bars_1d", target.ticker, db.TIINGO_SPLIT_ONLY, to_bars(prices, split_only=True))
    db.upsert_splits(conn, target.ticker, db.TIINGO, to_splits(prices))
    db.record_job_result(conn, SPLITS_JOB, target.ticker, "success")
    return {**row, "status": "stored"}


def backfill_splits(conn: sqlite3.Connection, client: TiingoClient, limit: int | None = None) -> None:
    """Split history for `stored` listings ingested before splits were kept
    (one price request each). Resumable through `fetch_jobs` (`SPLITS_JOB`):
    most tickers have no splits, so the splits table alone can't say which
    were done. Bars aren't rewritten."""
    stored = db.read_tiingo_listings(conn)
    todo = db.pending_keys(conn, SPLITS_JOB, sorted(stored.loc[stored["status"] == "stored", "ticker"]))
    for ticker in todo[:limit]:
        row = stored.set_index("ticker").loc[ticker]
        try:
            prices = client.daily_prices(tiingo_symbol(ticker), row["tiingo_start"], row["tiingo_end"])
        except requests.RequestException as e:
            db.record_job_result(conn, SPLITS_JOB, ticker, "failed", str(e))
            print(f"{ticker}: request failed, retry later ({e})", flush=True)
            continue
        splits = to_splits(prices) if prices is not None and not prices.empty else to_splits(_NO_PRICES)
        db.upsert_splits(conn, ticker, db.TIINGO, splits)
        db.record_job_result(conn, SPLITS_JOB, ticker, "success")
        print(f"{ticker}: {len(splits)} split(s)", flush=True)


def store_preferred(conn: sqlite3.Connection, client: TiingoClient, tickers: list[str] | None = None) -> None:
    """Full Tiingo history, both bases plus splits, for the tickers the
    modeling modules read from Tiingo even though yfinance has them
    (`vendor_overrides.PREFER_TIINGO`, all of them by default). One request
    each; rerun with every bar refresh, since stored bars stop at the fetch
    date. A failed ticker keeps whatever it had and is reported."""
    for ticker in tickers if tickers is not None else sorted(PREFER_TIINGO):
        try:
            prices = client.daily_prices(tiingo_symbol(ticker), PREFERRED_START, pd.Timestamp.today().strftime("%Y-%m-%d"))
        except requests.RequestException as e:
            print(f"{ticker}: request failed, kept existing bars ({e})", flush=True)
            continue
        if prices is None or prices.empty:
            print(f"{ticker}: no prices from Tiingo, kept existing bars", flush=True)
            continue
        db.upsert_bars(conn, "bars_1d", ticker, db.TIINGO, to_bars(prices, split_only=False))
        db.upsert_bars(conn, "bars_1d", ticker, db.TIINGO_SPLIT_ONLY, to_bars(prices, split_only=True))
        db.upsert_splits(conn, ticker, db.TIINGO, to_splits(prices))
        print(f"{ticker}: {len(prices)} bars", flush=True)


def run(conn: sqlite3.Connection, client: TiingoClient, listings: pd.DataFrame, since: str,
        refresh: bool = False, limit: int | None = None, retry_statuses: list[str] | None = None) -> pd.DataFrame:
    """Decide every target not already decided (all of them with `refresh`;
    also those whose stored status is in `retry_statuses`), saving each
    outcome before the next request."""
    todo = targets(conn, since)
    if not refresh:
        decided = db.read_tiingo_listings(conn)
        done = set(decided.loc[~decided["status"].isin(retry_statuses or []), "ticker"])
        todo = todo[~todo["ticker"].isin(done)]
    if limit is not None:
        todo = todo.head(limit)
    for target in todo.itertuples(index=False):
        try:
            outcome = decide(conn, client, listings, target, since)
        except requests.RequestException as e:
            # Not a decision: left unrecorded so the next run retries it.
            print(f"{target.ticker}: request failed, retry later ({e})", flush=True)
            continue
        db.upsert_tiingo_listing(conn, outcome)
        print(f"{target.ticker}: {outcome['status']} {outcome.get('tiingo_name') or ''}", flush=True)
    return db.read_tiingo_listings(conn)


def main():
    parser = argparse.ArgumentParser(description="Tiingo daily bars for delisted index members")
    parser.add_argument("--since", default="2009-01-01", help="Only members with membership after this date")
    parser.add_argument("--limit", type=int, help="Check at most this many targets (a trial run)")
    parser.add_argument("--refresh", action="store_true", help="Re-decide tickers already in tiingo_listings")
    parser.add_argument("--store-preferred", action="store_true",
                        help="Only fetch the vendor_overrides.PREFER_TIINGO tickers (one request each)")
    parser.add_argument("--backfill-splits", action="store_true",
                        help="Only fetch split histories for already-stored listings (one request each)")
    parser.add_argument("--retry-status", help="Comma-separated stored statuses to re-decide (e.g. name_mismatch)")
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)
    if args.store_preferred:
        store_preferred(conn, TiingoClient())
        conn.close()
        return
    if args.backfill_splits:
        backfill_splits(conn, TiingoClient(), args.limit)
        conn.close()
        return
    table = run(conn, TiingoClient(), supported_tickers(), args.since, args.refresh, args.limit,
                args.retry_status.split(",") if args.retry_status else None)
    print(table["status"].value_counts().to_string())
    conn.close()


if __name__ == "__main__":
    main()

"""python -m src.foundation.data_processing.ticker_renames [--indices sp500,nasdaq100] [--since 2009-01-01] [--refresh]

Maps index members whose symbol later changed (ABC -> COR, FB -> META) to the
symbol their price history now lives under. The membership datasets record the
symbol in use at the time; yfinance serves the whole history under today's
symbol, so without this map those members look like they have no prices at all
and silently drop out of every point-in-time universe.

A mapping is accepted only when it's the same company, checked, not guessed:
1. Polygon: which company traded under the old symbol on a date inside its
   membership (`PolygonClient.ticker_as_of`) -- its CIK. The date guards against
   reused symbols.
2. SEC `company_tickers.json` (`data/raw/sec/`): today's symbols for that CIK.
3. Exactly one of them has `bars_1d` history, and that history covers at least
   `MIN_COVERAGE` of the old symbol's membership trading days (clipped to
   `--since`), measured against SPY's trading days.

Everything else is stored with its reason (`status`) and left unmapped: a merger
that created a new CIK (MYL -> VTRS), a real delisting, an ambiguous share class.
Those are the review list, not guesses.

Consumers apply the map with `price_ticker_map` (breadth does; the completed MA
study deliberately does not, to stay reproducible).
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.foundation.data_processing import db
from src.foundation.data_processing import sec_companyfacts as sec
from src.foundation.data_processing.polygon_client import PolygonClient
from src.foundation.utils.config_loader import load_config

MIN_COVERAGE = 0.9
PRICE_SOURCE = db.YFINANCE
CALENDAR_TICKER = "SPY"


def candidates(conn: sqlite3.Connection, indices: list[str], since: str) -> pd.DataFrame:
    """Members of `indices` with membership after `since` and no `bars_1d`
    rows at all. One row per ticker: its membership window (earliest start,
    latest end, clipped to `since`)."""
    placeholders = ",".join("?" for _ in indices)
    query = f"""
        SELECT ticker, MIN(start_date) AS start_date, MAX(COALESCE(end_date, '9999-12-31')) AS end_date
        FROM index_membership m
        WHERE index_name IN ({placeholders})
          AND NOT EXISTS (SELECT 1 FROM bars_1d b WHERE b.ticker = m.ticker AND b.source = ?)
        GROUP BY ticker
        HAVING MAX(COALESCE(end_date, '9999-12-31')) >= ?
    """
    df = pd.read_sql_query(query, conn, params=[*indices, PRICE_SOURCE, since])
    df["start_date"] = df["start_date"].where(df["start_date"] >= since, since)
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    df["end_date"] = df["end_date"].where(df["end_date"] <= today, today)
    return df.sort_values("ticker").reset_index(drop=True)


def lookup_date(start: str, end: str) -> str:
    """Midpoint of the membership window: safely inside it, away from the
    rename/delisting edge where Polygon's as-of lookup is least reliable."""
    return (pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2).strftime("%Y-%m-%d")


def coverage(conn: sqlite3.Connection, ticker: str, start: str, end: str) -> float:
    """Share of the market's trading days in [start, end] on which `ticker`
    has a `bars_1d` row."""
    query = """
        SELECT COUNT(DISTINCT substr(timestamp, 1, 10)) FROM bars_1d
        WHERE ticker = ? AND source = ? AND timestamp >= ? AND timestamp <= ?
    """
    window = [start, f"{end}T23:59:59"]
    market = conn.execute(query, [CALENDAR_TICKER, PRICE_SOURCE, *window]).fetchone()[0]
    if not market:
        return 0.0
    have = conn.execute(query, [ticker, PRICE_SOURCE, *window]).fetchone()[0]
    return have / market


def tickers_by_cik(cik_map: dict[str, int]) -> dict[int, list[str]]:
    """Invert SEC's ticker -> CIK map, back into this project's spelling
    (share classes with '.', as `tickers`/`bars_1d` store them)."""
    result: dict[int, list[str]] = {}
    for sec_ticker, cik in cik_map.items():
        result.setdefault(cik, []).append(sec_ticker.replace("-", "."))
    return result


def resolve(
    conn: sqlite3.Connection, old_ticker: str, start: str, end: str,
    listing: dict | None, by_cik: dict[int, list[str]],
) -> dict:
    """Decide one old ticker, given Polygon's as-of `listing` for it."""
    row = {"old_ticker": old_ticker, "lookup_date": lookup_date(start, end)}
    if listing is None:
        return {**row, "status": "no_listing"}
    row["old_name"] = listing.get("name")
    if not listing.get("cik"):
        return {**row, "status": "no_cik"}
    cik = int(listing["cik"])
    row["cik"] = cik
    current = [t for t in by_cik.get(cik, []) if t != old_ticker]
    scored = {t: coverage(conn, t, start, end) for t in current}
    priced = {t: c for t, c in scored.items() if c > 0}
    if not priced:
        return {**row, "status": "no_current_ticker", "detail": ",".join(current) or None}
    if len(priced) > 1:
        return {**row, "status": "ambiguous", "detail": ",".join(f"{t}:{c:.2f}" for t, c in sorted(priced.items()))}
    new_ticker, cov = next(iter(priced.items()))
    row.update(new_ticker=new_ticker, coverage=round(cov, 4))
    return {**row, "status": "matched" if cov >= MIN_COVERAGE else "low_coverage"}


def price_ticker_map(conn: sqlite3.Connection) -> dict[str, str]:
    """old symbol -> symbol its prices live under, for matched renames only."""
    renames = db.read_ticker_renames(conn)
    return dict(zip(renames["old_ticker"], renames["new_ticker"]))


def run(
    conn: sqlite3.Connection, client: PolygonClient, cik_map: dict[str, int],
    indices: list[str], since: str, refresh: bool = False,
) -> pd.DataFrame:
    """Look up every candidate not already decided (all of them with
    `refresh`), store each outcome, and return the full table."""
    by_cik = tickers_by_cik(cik_map)
    done = set() if refresh else set(db.read_ticker_renames(conn, matched_only=False)["old_ticker"])
    todo = candidates(conn, indices, since)
    todo = todo[~todo["ticker"].isin(done)]
    for row in todo.itertuples(index=False):
        listing = client.ticker_as_of(row.ticker, lookup_date(row.start_date, row.end_date))
        outcome = resolve(conn, row.ticker, row.start_date, row.end_date, listing, by_cik)
        db.upsert_ticker_rename(conn, outcome)
        print(f"{row.ticker}: {outcome['status']} {outcome.get('new_ticker') or ''}")
    return db.read_ticker_renames(conn, matched_only=False)


def main():
    parser = argparse.ArgumentParser(description="Map renamed index members to the symbol their prices live under")
    parser.add_argument("--indices", default="sp500,nasdaq100")
    parser.add_argument("--since", default="2009-01-01", help="Only members with membership after this date")
    parser.add_argument("--refresh", action="store_true", help="Re-decide tickers already in the table")
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)
    cik_map = sec.load_cik_map(Path(config.data_paths.raw) / "sec" / "company_tickers.json")
    table = run(conn, PolygonClient(), cik_map, args.indices.split(","), args.since, args.refresh)
    print(table["status"].value_counts().to_string())
    conn.close()


if __name__ == "__main__":
    main()

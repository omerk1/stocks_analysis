"""python -m src.foundation.data_processing.symbol_reuse [--indices sp500,nasdaq100] [--since 2009-01-01] [--refresh]

Former index members whose symbol now belongs to another company, while
yfinance serves *that* company's history under it. BBT was BB&T in the S&P 500
until 2019 (then Truist, TFC); the symbol was later taken by Beacon Financial,
and yfinance's BBT bars, 2000 onward, are Beacon's (backlog: survivorship
research). `ticker_renames.py` only looks at members with no prices at all, so
it never saw these.

Each candidate -- a member of `--indices` whose latest membership block ended
after `--since`, that has yfinance bars and isn't in `ticker_renames` -- is
decided, not guessed:
1. Polygon: the company that traded under the symbol at the block's midpoint
   (`PolygonClient.ticker_as_of`), its name and CIK.
2. SEC `company_tickers.json`: the symbol's current holder (CIK), whose
   history yfinance serves.
3. **same_company** if the membership-era name matches the holder's current
   or former SEC name (`submissions.zip`) -- the same company, renamed or not.
   Otherwise **reused**: the bars under this symbol aren't the member's --
   unless Polygon's CIK *is* the holder's and only the spelling differs
   (`same_cik_name_differs`). `no_listing` (Polygon has nothing at that date)
   and `no_holder` (the symbol isn't in SEC's current list) are left for review too.

A reused symbol only matters if the holder's bars overlap the membership
window: one reused by a 2020s IPO has no bars in the old member's years.
`reused` is a name test, so a successor that now files under a new CIK and a
different name (a holding-company reorganisation, a merger successor) shows
up as reused too: every row goes through review before it becomes a dispute.

`cik_verified` says whether Polygon's CIK matched the membership-era name
(as in `ticker_renames`). Each decision is saved as it's made; reruns skip
decided tickers. The `reused` rows with bars inside the window are reviewed and added to
`market_common/price_disputes.csv` as whole-history yfinance disputes, which
drops their labels. One Polygon request per candidate (5/min).
"""

from __future__ import annotations

import argparse
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.foundation.data_processing import db
from src.foundation.data_processing import sec_companyfacts as sec
from src.foundation.data_processing import ticker_renames as tr
from src.foundation.data_processing.polygon_client import PolygonClient
from src.foundation.utils.config_loader import load_config


def candidates(conn: sqlite3.Connection, indices: list[str], since: str) -> pd.DataFrame:
    """One row per former member with yfinance bars that isn't a matched rename
    (whose prices live under its new symbol): its latest membership block
    (`valid_from`/`valid_to`) when that ended after `since`. Current members
    are left out -- a current member's symbol is its own. Only the latest
    block is checked; an earlier block of a symbol held by another company
    since isn't (29 such blocks after 2009 were spot-checked on 2026-10-07:
    none overlaps another company's bars)."""
    placeholders = ",".join("?" for _ in indices)
    rows = pd.read_sql_query(
        f"""
        SELECT ticker, start_date, COALESCE(end_date, '9999-12-31') AS end_date
        FROM index_membership m
        WHERE index_name IN ({placeholders})
          AND ticker NOT IN (SELECT old_ticker FROM ticker_renames WHERE status = 'matched')
          AND EXISTS (SELECT 1 FROM bars_1d b WHERE b.ticker = m.ticker AND b.source = ?)
        """,
        conn, params=[*indices, db.YFINANCE],
    )
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    out = []
    for ticker, group in rows.groupby("ticker"):
        if (group["end_date"] == "9999-12-31").any():
            continue  # a current member
        start, end = tr.latest_block(group)
        if end < since:
            continue
        # Checked inside [since, today], as `ticker_renames.candidates` does: a
        # block often starts at the dataset's 1996 floor, before the member used
        # the symbol, and a midpoint there asks Polygon about the wrong company.
        out.append((ticker, start, end, max(start, since), min(end, today)))
    columns = ["ticker", "valid_from", "valid_to", "start_date", "end_date"]
    return pd.DataFrame(out, columns=columns).sort_values("ticker", ignore_index=True)


def decide(row, listing: dict | None, holder_cik: int | None, names: dict[int, list[str]]) -> dict:
    """The outcome for one candidate, given Polygon's as-of `listing`, the
    symbol's current holder CIK, and SEC current/former names per CIK."""
    out = {"ticker": row.ticker, "valid_from": row.valid_from, "valid_to": row.valid_to,
           "lookup_date": tr.lookup_date(row.start_date, row.end_date), "holder_cik": holder_cik}
    if holder_cik is not None:
        out["holder_name"] = (names.get(holder_cik) or [None])[0]
    if listing is None or not listing.get("name"):
        return {**out, "status": "no_listing"}
    out["polygon_name"] = listing.get("name")
    if listing.get("cik"):
        cik = int(listing["cik"])
        out["polygon_cik"] = cik
        out["cik_verified"] = int(tr.names_match(listing.get("name"), names.get(cik, [])))
    if holder_cik is None:
        return {**out, "status": "no_holder"}
    if tr.names_match(listing.get("name"), names.get(holder_cik, [])):
        return {**out, "status": "same_company"}
    if out.get("polygon_cik") == holder_cik:
        # Same CIK, names that don't tokenise alike ("Signet Jewlers", "Car Max"):
        # almost always the same company, but Polygon's CIK can be wrong, so review.
        return {**out, "status": "same_cik_name_differs"}
    return {**out, "status": "reused"}


def _stored_listings(conn: sqlite3.Connection) -> dict[str, dict]:
    """Polygon answers already in `symbol_reuse`, by ticker, with the date they
    were asked for -- reused when that date hasn't changed, so re-deciding
    doesn't repeat ~30 minutes of rate-limited lookups."""
    stored = {}
    for r in db.read_symbol_reuse(conn).itertuples(index=False):
        listing = None
        if pd.notna(r.polygon_name):
            listing = {"name": r.polygon_name, "cik": None if pd.isna(r.polygon_cik) else str(int(r.polygon_cik))}
        stored[r.ticker] = {"as_of": r.lookup_date, "listing": listing}
    return stored


def run(conn: sqlite3.Connection, client: PolygonClient, cik_map: dict[str, int], submissions_zip: str | Path,
        indices: list[str], since: str, refresh: bool = False, relookup: bool = False) -> pd.DataFrame:
    """Decide candidates not decided yet (all with `refresh`), saving each as
    it's made. Polygon is asked only when no answer is stored for the same
    lookup date, or for all with `relookup`."""
    todo = candidates(conn, indices, since)
    stored = {} if relookup else _stored_listings(conn)
    if not refresh:
        todo = todo[~todo["ticker"].isin(set(db.read_symbol_reuse(conn)["ticker"]))]
    with zipfile.ZipFile(submissions_zip) as zf:
        available = set(zf.namelist())
        for row in todo.itertuples(index=False):
            as_of = tr.lookup_date(row.start_date, row.end_date)
            known = stored.get(row.ticker)
            listing = known["listing"] if known and known["as_of"] == as_of else client.ticker_as_of(row.ticker, as_of)
            holder_cik = cik_map.get(row.ticker.replace(".", "-"))
            ciks = {c for c in (holder_cik, int(listing["cik"]) if listing and listing.get("cik") else None) if c}
            names = {c: tr.company_names(zf, available, c) for c in ciks}
            outcome = decide(row, listing, holder_cik, names)
            db.upsert_symbol_reuse(conn, outcome)
            print(f"{row.ticker}: {outcome['status']} ({outcome.get('polygon_name')} -> {outcome.get('holder_name')})",
                  flush=True)
    return db.read_symbol_reuse(conn)


def main():
    parser = argparse.ArgumentParser(description="Former index members whose symbol's prices are another company's")
    parser.add_argument("--indices", default="sp500,nasdaq100")
    parser.add_argument("--since", default="2009-01-01", help="Only members whose membership ended after this date")
    parser.add_argument("--refresh", action="store_true", help="Re-decide tickers already in the table")
    parser.add_argument("--relookup", action="store_true",
                        help="Ask Polygon again even where a stored answer has the same lookup date (slow: 5/min)")
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)
    sec_dir = Path(config.data_paths.raw) / "sec"
    table = run(conn, PolygonClient(), sec.load_cik_map(sec_dir / "company_tickers.json"),
                sec_dir / "submissions.zip", args.indices.split(","), args.since, args.refresh, args.relookup)
    print(table["status"].value_counts().to_string())
    conn.close()


if __name__ == "__main__":
    main()

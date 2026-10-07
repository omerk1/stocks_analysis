"""python -m src.foundation.data_processing.ticker_renames [--indices sp500,nasdaq100] [--since 2009-01-01] [--refresh]

Maps index members whose symbol later changed (ABC -> COR, FB -> META) to the
symbol their price history now lives under. The membership datasets record the
symbol in use at the time; yfinance serves the whole history under today's
symbol, so without this map those members look like they have no prices at all
and silently drop out of every point-in-time universe.

A mapping is accepted only when it's the same company, checked, not guessed:
1. Polygon: which company traded under the old symbol on a date inside its
   membership (`PolygonClient.ticker_as_of`) -- its name and CIK. The date guards
   against reused symbols.
2. **Name check.** Polygon's CIK is wrong for some old delisted symbols (it gave
   Monster Worldwide Morgan Stanley's CIK, L-3 JetBlue's, Level 3 Expeditors'),
   so the old name must match the CIK's current or a **former** name in SEC's
   `submissions.zip` (`data/raw/sec/`). Former names are what let real renames
   through (Facebook, Inc. is a former name of Meta's CIK).
3. SEC `company_tickers.json`: today's symbols for that CIK.
4. Exactly one of them has `bars_1d` history, and that history covers at least
   `MIN_COVERAGE` of the old symbol's membership trading days (clipped to
   `--since`), measured against SPY's trading days. Coverage alone proves nothing
   about identity -- a wrong company has prices too -- which is why step 2 exists.

Everything else is stored with its reason (`status`) and left unmapped: a merger
that created a new CIK (MYL -> VTRS), a real delisting, an ambiguous share class.
Those are the review list, not guesses.

Each mapping holds only inside its verified window (`valid_from`/`valid_to`, the
symbol's latest continuous membership block): an earlier block under the same
symbol may be another company. Consumers apply it with `apply_renames` on
membership rows (breadth does; the completed MA study deliberately does not, to
stay reproducible). Each decision is saved right after its lookup, so an
interrupted run keeps its progress.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.foundation.data_processing import db
from src.foundation.data_processing import sec_companyfacts as sec
from src.foundation.data_processing.polygon_client import PolygonClient
from src.foundation.utils.config_loader import load_config

MIN_COVERAGE = 0.9
NAME_MATCH = 0.6  # token Jaccard between normalised names

# Words that carry no identity: legal forms, share-class and listing noise.
_NAME_NOISE = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "PLC",
    "NV", "SA", "AG", "LLC", "LP", "HOLDINGS", "HOLDING", "HLDGS", "GROUP", "THE", "NEW",
    "COM", "STK", "CL", "CLASS", "A", "B", "C", "ORD", "SHS", "SHARES", "COMMON", "STOCK",
    "DE", "MD", "OH", "IN", "VGB", "EURO", "PUBLIC", "ORDINARY", "TRUST", "CP", "OF", "AND",
}

# Abbreviations Polygon's historical names use where SEC spells words out
# ("DEVELOPERS DIVERSIFIED RLTY CP" vs "Developers Diversified Realty Corp").
_NAME_ABBREVIATIONS = {
    "RLTY": "REALTY", "INTL": "INTERNATIONAL", "SYS": "SYSTEMS", "MKT": "MARKET",
    "MKTS": "MARKETS", "RES": "RESOURCES", "NAT": "NATURAL", "NATL": "NATIONAL",
    "MTN": "MOUNTAIN", "SERVS": "SERVICES", "SVCS": "SERVICES", "IND": "INDUSTRIES",
    "INDS": "INDUSTRIES", "COS": "COMPANIES", "FINL": "FINANCIAL", "MGMT": "MANAGEMENT",
    "COMMUN": "COMMUNICATIONS", "COMMUNS": "COMMUNICATIONS", "TECH": "TECHNOLOGY",
    "TECHS": "TECHNOLOGIES", "PPTYS": "PROPERTIES", "PROPS": "PROPERTIES",
}
PRICE_SOURCE = db.YFINANCE
CALENDAR_TICKER = "SPY"


def candidates(conn: sqlite3.Connection, indices: list[str], since: str) -> pd.DataFrame:
    """Members of `indices` with no `bars_1d` rows at all, one row per ticker:
    its **latest** continuous membership block that reaches past `since`.

    A block merges membership intervals (across `indices`) that overlap or
    touch, so the same holder's S&P 500 and Nasdaq-100 rows form one block. A
    symbol that left and later came back has separate blocks, and only the
    latest is checked: an earlier block may belong to a different company
    (symbols get reused). Columns: `valid_from`/`valid_to` (the block, which is
    where a verified mapping applies) and `start_date`/`end_date` (the block
    clipped to [since, today], which is what gets checked)."""
    placeholders = ",".join("?" for _ in indices)
    query = f"""
        SELECT ticker, start_date, COALESCE(end_date, '9999-12-31') AS end_date
        FROM index_membership m
        WHERE index_name IN ({placeholders})
          AND NOT EXISTS (SELECT 1 FROM bars_1d b WHERE b.ticker = m.ticker AND b.source = ?)
    """
    rows = pd.read_sql_query(query, conn, params=[*indices, PRICE_SOURCE])
    columns = ["ticker", "valid_from", "valid_to", "start_date", "end_date"]
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    out = []
    for ticker, group in rows.groupby("ticker"):
        block = _latest_block(group)
        if block[1] < since:
            continue
        out.append((ticker, block[0], block[1], max(block[0], since), min(block[1], today)))
    return pd.DataFrame(out, columns=columns).sort_values("ticker").reset_index(drop=True)


def _latest_block(intervals: pd.DataFrame) -> tuple[str, str]:
    """(start, end) of the latest run of overlapping or touching intervals."""
    spans = sorted(zip(intervals["start_date"], intervals["end_date"]))
    start, end = spans[0]
    for s, e in spans[1:]:
        if s <= (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"):
            end = max(end, e)
        else:
            start, end = s, e
    return start, end


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
    listing: dict | None, by_cik: dict[int, list[str]], company_names: dict[int, list[str]],
    window: dict | None = None,
) -> dict:
    """Decide one old ticker, given Polygon's as-of `listing` for it and the
    SEC current/former names per CIK."""
    row = {"old_ticker": old_ticker, "lookup_date": lookup_date(start, end), **(window or {})}
    if listing is None:
        return {**row, "status": "no_listing"}
    row["old_name"] = listing.get("name")
    if not listing.get("cik"):
        return {**row, "status": "no_cik"}
    cik = int(listing["cik"])
    row["cik"] = cik
    sec_names = company_names.get(cik, [])
    if not names_match(listing.get("name"), sec_names):
        return {**row, "status": "name_mismatch", "cik_verified": 0,
                "detail": "; ".join(sec_names[:4]) or "CIK not in submissions.zip"}
    row["cik_verified"] = 1
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


def normalize_name(name: str | None) -> frozenset[str]:
    """Identity tokens of a company name: upper-cased, parentheticals and
    punctuation dropped, common abbreviations expanded, legal-form/share-class
    words removed."""
    if not name:
        return frozenset()
    text = re.sub(r"\([^)]*\)", " ", name.upper()).replace("&", " AND ")
    tokens = (_NAME_ABBREVIATIONS.get(t, t) for t in re.split(r"[^A-Z0-9]+", text))
    return frozenset(t for t in tokens if t and t not in _NAME_NOISE)


def names_match(old_name: str | None, candidates: list[str]) -> bool:
    """True if `old_name` matches any of `candidates` (a CIK's current and
    former names) by token Jaccard >= NAME_MATCH."""
    old = normalize_name(old_name)
    if not old:
        return False
    for name in candidates:
        other = normalize_name(name)
        if other and len(old & other) / len(old | other) >= NAME_MATCH:
            return True
    return False


def load_company_names(submissions_zip: str | Path, ciks: set[int]) -> dict[int, list[str]]:
    """Current plus former names for each CIK in `ciks`, from SEC's bulk
    `submissions.zip` (one `CIK##########.json` per filer, with `name` and
    `formerNames`). A CIK missing from the archive maps to []."""
    with zipfile.ZipFile(submissions_zip) as zf:
        available = set(zf.namelist())
        return {cik: _company_names(zf, available, cik) for cik in ciks}


# Statuses decided after the name check passed: the CIK is the old company's.
VERIFIED_STATUSES = ("matched", "low_coverage", "ambiguous", "no_current_ticker")


def backfill_cik_verified(conn: sqlite3.Connection) -> int:
    """Set `cik_verified` on rows decided before the flag existed, from their
    status (the check itself already ran). Returns rows updated."""
    placeholders = ",".join("?" * len(VERIFIED_STATUSES))
    cur = conn.execute(
        f"""UPDATE ticker_renames SET cik_verified = CASE
                WHEN cik IS NULL THEN NULL
                WHEN status IN ({placeholders}) THEN 1
                WHEN status = 'name_mismatch' THEN 0 END
            WHERE cik_verified IS NULL AND cik IS NOT NULL""",
        VERIFIED_STATUSES,
    )
    conn.commit()
    return cur.rowcount


def price_ticker_map(conn: sqlite3.Connection) -> dict[str, str]:
    """old symbol -> symbol its prices live under, for matched renames only.
    Ignores the validity window -- use `apply_renames` on membership rows."""
    renames = db.read_ticker_renames(conn)
    return dict(zip(renames["old_ticker"], renames["new_ticker"]))


def apply_renames(conn: sqlite3.Connection, membership: pd.DataFrame) -> pd.DataFrame:
    """`membership` with each renamed symbol replaced by its price symbol, but
    only on rows whose interval overlaps the verified window [valid_from,
    valid_to]. Earlier rows under a reused symbol may be a different company
    and stay as they are."""
    renames = db.read_ticker_renames(conn)
    out = membership.copy()
    if renames.empty or out.empty:
        return out
    start = pd.to_datetime(out["start_date"])
    end = pd.to_datetime(out["end_date"]).fillna(pd.Timestamp.max)
    for r in renames.itertuples(index=False):
        if pd.isna(r.valid_from) or pd.isna(r.valid_to):
            continue  # decided before windows were stored; re-run to record one
        hit = (out["ticker"] == r.old_ticker) & (start <= pd.Timestamp(r.valid_to)) & (end >= pd.Timestamp(r.valid_from))
        out.loc[hit, "ticker"] = r.new_ticker
    return out


def _stored_listings(conn: sqlite3.Connection) -> dict[str, dict | None]:
    """Polygon answers already recorded in `ticker_renames`, so a re-decision
    doesn't repeat an hour of rate-limited lookups. `no_listing` rows map to None."""
    table = db.read_ticker_renames(conn, matched_only=False)
    listings: dict[str, dict | None] = {}
    for row in table.itertuples(index=False):
        if row.status == "no_listing":
            listings[row.old_ticker] = {"as_of": row.lookup_date, "missing": True}
        elif pd.notna(row.old_name) or pd.notna(row.cik):
            cik = None if pd.isna(row.cik) else str(int(row.cik))
            listings[row.old_ticker] = {"name": row.old_name, "cik": cik, "as_of": row.lookup_date}
    return listings


def run(
    conn: sqlite3.Connection, client: PolygonClient, cik_map: dict[str, int],
    submissions_zip: str | Path, indices: list[str], since: str,
    refresh: bool = False, relookup: bool = False,
) -> pd.DataFrame:
    """Decide every candidate not already decided (all of them with `refresh`),
    store each outcome, and return the full table. Polygon is only called for
    tickers with no stored listing, or for all of them with `relookup`."""
    backfill_cik_verified(conn)
    by_cik = tickers_by_cik(cik_map)
    stored = {} if relookup else _stored_listings(conn)
    done = set() if refresh else set(db.read_ticker_renames(conn, matched_only=False)["old_ticker"])
    todo = candidates(conn, indices, since)
    todo = todo[~todo["ticker"].isin(done)]
    with zipfile.ZipFile(submissions_zip) as zf:
        available = set(zf.namelist())
        for row in todo.itertuples(index=False):
            listing = _listing_for(client, stored.get(row.ticker), row)
            names = {}
            if listing and listing.get("cik"):
                cik = int(listing["cik"])
                names[cik] = _company_names(zf, available, cik)
            outcome = resolve(conn, row.ticker, row.start_date, row.end_date, listing, by_cik, names,
                              window={"valid_from": row.valid_from, "valid_to": row.valid_to})
            # Saved before the next lookup, so an interrupted run keeps its progress.
            db.upsert_ticker_rename(conn, outcome)
            print(f"{row.ticker}: {outcome['status']} {outcome.get('new_ticker') or ''}")
    return db.read_ticker_renames(conn, matched_only=False)


def _listing_for(client: PolygonClient, stored: dict | None, row) -> dict | None:
    """The stored Polygon answer if it was looked up inside this ticker's
    current window, otherwise a fresh lookup at the window's midpoint."""
    if stored is not None and stored.get("as_of") and row.start_date <= stored["as_of"] <= row.end_date:
        return None if stored.get("missing") else stored
    return client.ticker_as_of(row.ticker, lookup_date(row.start_date, row.end_date))


def _company_names(zf: zipfile.ZipFile, available: set[str], cik: int) -> list[str]:
    member = f"CIK{cik:010d}.json"
    if member not in available:
        return []
    data = json.loads(zf.read(member))
    names = [data.get("name")] + [f.get("name") for f in data.get("formerNames") or []]
    return [n for n in names if n]


def main():
    parser = argparse.ArgumentParser(description="Map renamed index members to the symbol their prices live under")
    parser.add_argument("--indices", default="sp500,nasdaq100")
    parser.add_argument("--since", default="2009-01-01", help="Only members with membership after this date")
    parser.add_argument("--refresh", action="store_true", help="Re-decide tickers already in the table")
    parser.add_argument("--backfill-cik-verified", action="store_true",
                        help="Only set cik_verified on rows decided before the flag existed (no API calls)")
    parser.add_argument("--relookup", action="store_true",
                        help="Ask Polygon again instead of reusing stored listings (slow: 5 requests/min)")
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)
    if args.backfill_cik_verified:
        print(f"cik_verified set on {backfill_cik_verified(conn)} rows")
        conn.close()
        return
    sec_dir = Path(config.data_paths.raw) / "sec"
    submissions = sec_dir / "submissions.zip"
    if not submissions.exists():
        raise SystemExit(
            f"Missing {submissions} -- download it by hand from sec.gov's EDGAR bulk data page. "
            "Renames aren't decided without the former-name check."
        )
    cik_map = sec.load_cik_map(sec_dir / "company_tickers.json")
    table = run(conn, PolygonClient(), cik_map, submissions, args.indices.split(","), args.since,
                args.refresh, args.relookup)
    print(table["status"].value_counts().to_string())
    conn.close()


if __name__ == "__main__":
    main()

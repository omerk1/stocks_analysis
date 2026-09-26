"""python -m src.foundation.data_processing.bulk_sec_shares_ingest [--sec-dir data/raw/sec] [--indices sp500,...]

Backfills `shares_outstanding` (source=`sec_edgar`) from SEC EDGAR's bulk
company-facts file -- share counts back to ~2009-2011, where yfinance's
history mostly starts in 2015. Entirely local: reads `companyfacts.zip` and
`company_tickers.json`, both downloaded by hand from sec.gov's EDGAR bulk
data page into `--sec-dir`. See `sec_companyfacts` for what is extracted
and why (filing-date keyed). A company is stored only if its counts agree
with yfinance's where the two overlap (see `backfill_sec_shares`).

Each ticker's `sec_edgar` rows are replaced wholesale, in one transaction,
so a rerun against a newer download (or after a parsing change) never
leaves stale points behind. Other sources' rows are never touched. No
`fetch_jobs` resumability: a full run is local and takes minutes.
"""

from __future__ import annotations

import argparse
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.data_processing import sec_companyfacts as sec
from src.foundation.utils.config_loader import load_config


# Acceptance band for the median SEC/yfinance ratio where both have data,
# and the minimum overlap for that check to count. Scale errors are >=1000x
# and class mix-ups typically >=1.5x, so +-25% separates them from real
# timing differences between the two sources' filing dates.
AGREEMENT_BAND = (0.8, 1.25)
MIN_OVERLAP = 3


def backfill_sec_shares(
    conn: sqlite3.Connection, zf: zipfile.ZipFile, cik_map: dict[str, int], tickers: list[str],
) -> Counter:
    """Returns a tally of outcomes: stored / no_cik / not_in_zip /
    no_share_facts / disagrees_with_yfinance / ambiguous_class.

    A company whose counts overlap yfinance's is kept only if they agree
    (median ratio inside AGREEMENT_BAND) -- this catches both scale errors
    and share-class mix-ups without guessing which tickers are classes.
    With no usable overlap there's nothing to check against, so it's kept
    only when no other ticker in `tickers` maps to the same company.
    """
    shared_ciks = {
        cik for cik, n in Counter(cik_map.get(sec.to_sec_ticker(t)) for t in tickers).items()
        if cik is not None and n > 1
    }
    tally: Counter = Counter()
    for ticker in tickers:
        cik = cik_map.get(sec.to_sec_ticker(ticker))
        if cik is None:
            tally["no_cik"] += 1
            continue
        company = sec.read_company(zf, cik)
        if company is None:
            tally["not_in_zip"] += 1
            continue
        counts = sec.drop_isolated_spikes(sec.share_counts(company))
        if counts.empty:
            tally["no_share_facts"] += 1
            continue
        reference = db.read_shares_outstanding(conn, ticker, db.YFINANCE)
        n_overlap, ratio = sec.agreement(
            counts, pd.Series(reference["shares_outstanding"].to_numpy(), index=pd.to_datetime(reference["date"]))
        )
        if n_overlap >= MIN_OVERLAP:
            if not (AGREEMENT_BAND[0] <= ratio <= AGREEMENT_BAND[1]):
                tally["disagrees_with_yfinance"] += 1
                continue
        elif cik in shared_ciks:
            tally["ambiguous_class"] += 1
            continue
        conn.execute(
            "DELETE FROM shares_outstanding WHERE ticker = ? AND source = ?", (ticker, db.SEC_EDGAR)
        )
        db.upsert_shares_outstanding(conn, ticker, db.SEC_EDGAR, counts)  # commits delete + insert together
        tally["stored"] += 1
        tally["points"] += len(counts)
    return tally


def main():
    parser = argparse.ArgumentParser(description="Backfill shares outstanding from SEC EDGAR's bulk company facts")
    parser.add_argument("--sec-dir", default=None, help="Folder holding companyfacts.zip and company_tickers.json "
                        "(default: <raw data dir>/sec)")
    parser.add_argument("--indices", default=None, help="Comma-separated index names to limit the universe to "
                        "(default: every active common stock)")
    args = parser.parse_args()

    config = load_config()
    sec_dir = Path(args.sec_dir) if args.sec_dir else Path(config.data_paths.raw) / "sec"
    zip_path, tickers_path = sec_dir / "companyfacts.zip", sec_dir / "company_tickers.json"
    for p in (zip_path, tickers_path):
        if not p.exists():
            raise SystemExit(f"Missing {p} -- download it from sec.gov's EDGAR bulk data page first.")

    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)
    tickers = db.read_universe_tickers(conn, args.indices)
    cik_map = sec.load_cik_map(tickers_path)

    with zipfile.ZipFile(zip_path) as zf:
        tally = backfill_sec_shares(conn, zf, cik_map, tickers)
    conn.close()

    print(f"{len(tickers)} tickers: stored {tally['stored']} ({tally['points']} points); skipped -- "
          f"disagrees with yfinance {tally['disagrees_with_yfinance']}, "
          f"ambiguous share class {tally['ambiguous_class']}, no SEC ticker match {tally['no_cik']}, "
          f"no company file {tally['not_in_zip']}, no share-count facts {tally['no_share_facts']}")


if __name__ == "__main__":
    main()

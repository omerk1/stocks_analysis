"""The probe's fixed sample: ~50 earnings press releases, stratified by year,
sector and size (`docs/fundamentals/plan.md`, step 5).

The frame is every `earnings_announcements` row (Done #137) whose announcement is
an item 2.02 8-K (`source` = '8-K', not the 10-Q/10-K fallback) accepted in
2010-2021, New York time. Nothing accepted after 2021-12-31 is ever in it.

Each row gets its sector (`ticker_sector`, today's classification, not
point-in-time; good enough to spread a sample) and its market cap at the last
close on or before the period end (`market_cap.reconcile_market_cap`: split-only
closes times the as-filed share count, rescaled by the splits since; undoing that
rescaling reads split dates after 2021, corporate-action metadata, never a price
or a release). Large is >= $10B, mid $2-10B; smaller and unknown caps are left out.

The draw: years and sectors are each shuffled with the seed, and slot i (0..n-1)
is the cell (year i mod 12, sector i mod 11, size alternating every 12 slots). As
12 and 11 are coprime, the first 132 slots are all distinct cells, every year gets
n/12 slots (half large, half mid) and every sector n/11. One release is drawn per
cell, at most one per company, so effective N is the number of releases and of
companies at once. A cell with no candidate takes the other size; with none at
all it is skipped and reported.

    python -m src.llm.guidance.sample            # writes the committed sample.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.data_processing import db, market_cap
from src.foundation.utils.config_loader import load_config

SEED = 20261018
N_RELEASES = 50
FIRST_YEAR, LAST_YEAR = 2010, 2021
LAST_DAY = pd.Timestamp("2021-12-31")  # holdout lock: nothing after it is read
MARKET_TZ = "America/New_York"
LARGE_CAP, MID_CAP = 10e9, 2e9
SIZES = ("large", "mid")
PRICE_SOURCE = db.YFINANCE_SPLIT_ONLY
PROBE_DIR = Path(__file__).resolve().parent / "probe"
SAMPLE_PATH = PROBE_DIR / "sample.csv"


def size_bucket(cap: float) -> str | None:
    if not np.isfinite(cap) or cap < MID_CAP:
        return None
    return "large" if cap >= LARGE_CAP else "mid"


def load_frame(conn) -> pd.DataFrame:
    """Every item 2.02 8-K announcement of 2010-2021 with its sector and size."""
    ann = pd.read_sql_query(
        "SELECT ticker, cik, filer_cik, period_end, report_form, accession, accepted_at "
        "FROM earnings_announcements WHERE source = '8-K'", conn)
    accepted = pd.to_datetime(ann["accepted_at"], utc=True).dt.tz_convert(MARKET_TZ)
    ann["year"] = accepted.dt.year
    ann = ann[ann["year"].between(FIRST_YEAR, LAST_YEAR)].copy()
    ann["filer_cik"] = ann["filer_cik"].fillna(ann["cik"]).astype(int)
    sectors = db.read_ticker_sector(conn)[["ticker", "sector"]]
    sectors = sectors[sectors["sector"].fillna("").str.strip() != ""]
    ann = ann.merge(sectors, on="ticker", how="inner")
    ann["market_cap"] = period_end_caps(conn, ann)
    ann["size"] = ann["market_cap"].map(size_bucket)
    return ann.dropna(subset=["size"]).reset_index(drop=True)


def period_end_caps(conn, ann: pd.DataFrame) -> pd.Series:
    """Market cap at the last close on or before each row's period end."""
    tickers = sorted(ann["ticker"].unique())
    placeholders = ",".join("?" for _ in tickers)
    bars = pd.read_sql_query(
        f"SELECT ticker, timestamp, close FROM bars_1d WHERE source = ? AND ticker IN ({placeholders}) "
        "AND timestamp >= ? AND timestamp <= ?", conn,
        params=[PRICE_SOURCE, *tickers, f"{FIRST_YEAR - 1}-06-01", f"{LAST_DAY.date()}T23:59:59"],
        parse_dates=["timestamp"])
    shares = market_cap.load_shares_outstanding(conn, tickers)
    shares = shares[shares["date"] <= LAST_DAY]
    splits = market_cap.load_splits(conn, tickers)
    caps = pd.Series(np.nan, index=ann.index)
    for ticker, rows in ann.groupby("ticker"):
        prices = bars.loc[bars["ticker"] == ticker].set_index("timestamp")["close"]
        s = shares.loc[shares["ticker"] == ticker].set_index("date")["shares_outstanding"]
        if prices.empty or s.empty:
            continue
        cap = market_cap.reconcile_market_cap(prices, s, splits[splits["ticker"] == ticker])["market_cap"]
        cap = cap.dropna()
        if cap.empty:
            continue
        ends = pd.to_datetime(rows["period_end"])
        caps.loc[rows.index] = cap.reindex(cap.index.union(ends)).ffill().reindex(ends).to_numpy()
    return caps


def draw(frame: pd.DataFrame, n: int = N_RELEASES, seed: int = SEED) -> tuple[pd.DataFrame, list[str]]:
    """The stratified draw (module docstring). Returns the sample and a note per
    slot that took the other size or was skipped."""
    rng = np.random.default_rng(seed)
    years = rng.permutation(np.arange(FIRST_YEAR, LAST_YEAR + 1))
    sectors = rng.permutation(np.array(sorted(frame["sector"].unique())))
    chosen, used, notes = [], set(), []
    for i in range(n):
        year, sector, size = years[i % len(years)], sectors[i % len(sectors)], SIZES[(i // len(years)) % 2]
        cell = frame[(frame["year"] == year) & (frame["sector"] == sector) & ~frame["ticker"].isin(used)]
        pick = cell[cell["size"] == size]
        if pick.empty:
            pick = cell
            notes.append(f"slot {i}: no {size} cap in {year} {sector}, " +
                         ("took the other size" if len(cell) else "skipped"))
        if pick.empty:
            continue
        row = pick.iloc[rng.integers(len(pick))]
        used.add(row["ticker"])
        chosen.append({"slot": i, "target_size": size, **row.to_dict()})
    sample = pd.DataFrame(chosen)
    sample["market_cap_bn"] = (sample.pop("market_cap") / 1e9).round(1)
    return sample, notes


def index_url(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.guidance.sample")
    parser.add_argument("--out", type=Path, default=SAMPLE_PATH)
    args = parser.parse_args(argv)
    config = load_config()
    conn = db.get_connection(f"file:{db.default_db_path(config.data_paths.raw)}?mode=ro", uri=True)
    frame = load_frame(conn)
    sample, notes = draw(frame)
    sample["index_url"] = [index_url(c, a) for c, a in zip(sample["filer_cik"], sample["accession"])]
    cols = ["slot", "ticker", "filer_cik", "accession", "accepted_at", "period_end", "report_form",
            "year", "sector", "size", "target_size", "market_cap_bn", "index_url"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sample[cols].to_csv(args.out, index=False)
    print(f"frame: {len(frame)} releases, {frame['ticker'].nunique()} companies")
    print(frame.groupby(["year", "size"]).size().unstack().to_string())
    print(f"sample: {len(sample)} releases, {sample['ticker'].nunique()} companies -> {args.out}")
    for note in notes:
        print(note)


if __name__ == "__main__":
    main()

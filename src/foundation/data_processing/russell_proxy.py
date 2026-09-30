"""python -m src.foundation.data_processing.russell_proxy [--start-year 2009] [--end-year 2026] [--dry-run]

Point-in-time Russell 1000 / 2000 / 3000 *proxies*, rebuilt the way FTSE Russell
builds the real indexes: once a year, rank every US common stock by total market
cap on a rank day, take the top 1,000 (large caps) and the next 2,000 (small caps),
and hold that membership until the next reconstitution. Real Russell membership
history isn't freely available, so this is the stand-in (`docs/modeling/IDEAS.md`
§6, decided 2026-09-29).

Approximations, all deliberate:
- **Rank day** = last trading day of April on or before `RANK_MONTH_DAY`; the new
  membership takes effect the first weekday after the fourth Friday of June (the
  reconstitution date) and ends the day before the next one.
- **Market cap** = split-adjusted close × cumulative later split ratio × the raw
  share count as of the rank day (`market_cap.reconcile_market_cap`), per ticker.
  Russell ranks a *company* (all share classes); this ranks each ticker.
- **Eligibility**: `tickers.type = 'CS'`, a close on or within 5 days before the rank
  day, a share count filed on or before it, and a rank-day close >= $1 (Russell's
  own price floor, applied to the split-reconciled price the stock actually
  traded at). No float, domicile or IPO-seasoning rules.
- **Prices** are the split-only closes (`market_cap.PRICE_SOURCE`), not the
  default yfinance bars, which are also dividend-adjusted and would understate
  dividend payers' caps. Spin-offs are still folded into Yahoo's split-only
  close (T before 2022 reads ~24% low), a residual bias.
- **Survivorship**: only tickers with price bars can be ranked, and delisted
  history before 2024 isn't on this plan (`docs/backlog.md`, survivorship-free
  price history). So each year's ranking misses companies that later delisted, and
  the proxy is survivors-only exactly like every other universe here.

Stored in `index_membership` as `russell1000_proxy`, `russell2000_proxy` and
`russell3000_proxy` (the union), full replace per run.
"""

from __future__ import annotations

import argparse
import sqlite3

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.data_processing import market_cap
from src.foundation.utils.config_loader import load_config

R1000 = "russell1000_proxy"
R2000 = "russell2000_proxy"
R3000 = "russell3000_proxy"

LARGE_CAP_COUNT = 1000
TOTAL_COUNT = 3000
MIN_PRICE = 1.0
RANK_MONTH_DAY = (4, 30)
MAX_STALE_DAYS = 5
PRICE_SOURCE = market_cap.PRICE_SOURCE


def rank_day(year: int) -> pd.Timestamp:
    """Nominal rank day for `year` (a calendar date; the close used is the last
    one on or before it, see `rank_day_caps`)."""
    return pd.Timestamp(year=year, month=RANK_MONTH_DAY[0], day=RANK_MONTH_DAY[1])


def reconstitution_day(year: int) -> pd.Timestamp:
    """First weekday after the fourth Friday of June -- when `year`'s new
    membership takes effect."""
    june = pd.date_range(f"{year}-06-01", f"{year}-06-30", freq="W-FRI")
    return june[3] + pd.offsets.BDay(1)


def _load_rank_day_closes(conn: sqlite3.Connection, days: list[pd.Timestamp]) -> pd.DataFrame:
    """Each common stock's last close within `MAX_STALE_DAYS` before (or on) each
    of `days`, in one pass over `bars_1d` (the table has no timestamp index, so a
    query per day would rescan it every time). Columns: rank_day, ticker, date, close."""
    windows = [
        ((d - pd.Timedelta(days=MAX_STALE_DAYS)).strftime("%Y-%m-%d"), d.strftime("%Y-%m-%dT23:59:59")) for d in days
    ]
    clause = " OR ".join("(b.timestamp >= ? AND b.timestamp <= ?)" for _ in windows)
    query = f"""
        SELECT b.ticker, b.timestamp, b.close FROM bars_1d b
        JOIN tickers t ON t.ticker = b.ticker
        WHERE b.source = ? AND t.type = 'CS' AND ({clause})
    """
    params = [PRICE_SOURCE] + [v for w in windows for v in w]
    df = pd.read_sql_query(query, conn, params=params, parse_dates=["timestamp"])
    columns = ["rank_day", "ticker", "date", "close"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    df["date"] = df["timestamp"].dt.normalize()
    frames = []
    for day in days:
        in_window = df[(df["date"] <= day) & (df["date"] >= day - pd.Timedelta(days=MAX_STALE_DAYS))]
        last = in_window.sort_values("date").groupby("ticker", as_index=False).last()
        frames.append(last.assign(rank_day=day))
    return pd.concat(frames, ignore_index=True)[columns]


def rank_day_caps(conn: sqlite3.Connection, days: list[pd.Timestamp]) -> pd.DataFrame:
    """Market cap of every eligible common stock at each rank day in `days`.
    Columns: rank_day, ticker, close, market_cap. Tickers without a share count
    filed by then (or priced under `MIN_PRICE`) are left out."""
    columns = ["rank_day", "ticker", "close", "market_cap"]
    closes = _load_rank_day_closes(conn, days)
    if closes.empty:
        return pd.DataFrame(columns=columns)
    tickers = sorted(closes["ticker"].unique())
    shares = market_cap.load_shares_outstanding(conn, tickers)
    splits = market_cap.load_splits(conn, tickers)
    shares_by_ticker = {t: g.set_index("date")["shares_outstanding"] for t, g in shares.groupby("ticker")}
    splits_by_ticker = dict(tuple(splits.groupby("ticker"))) if not splits.empty else {}

    frames = []
    for ticker, group in closes.groupby("ticker"):
        ticker_shares = shares_by_ticker.get(ticker)
        if ticker_shares is None:
            continue
        # One reconciliation per ticker across all its rank days; `date` is the
        # actual bar date, so each close is matched to shares filed by then.
        prices = pd.Series(group["close"].to_numpy(), index=pd.DatetimeIndex(group["date"], name="date"))
        cap = market_cap.reconcile_market_cap(prices, ticker_shares, splits_by_ticker.get(ticker))
        cap = cap.reindex(pd.DatetimeIndex(group["date"]))
        # The price floor applies to what the stock actually traded at: the
        # stored close is split-adjusted, so a stock with large later forward
        # splits (NVDA 2012: stored $0.30) must be scaled back up first.
        traded = group["close"].to_numpy() * cap["cumulative_split_ratio"].to_numpy()
        frames.append(group.assign(market_cap=cap["market_cap"].to_numpy(), traded_close=traded))
    if not frames:
        return pd.DataFrame(columns=columns)
    caps = pd.concat(frames, ignore_index=True)
    caps = caps[caps["market_cap"].notna() & (caps["market_cap"] > 0) & (caps["traded_close"] >= MIN_PRICE)]
    return caps[columns].reset_index(drop=True)


def rank_year(caps: pd.DataFrame) -> pd.DataFrame:
    """Assign each ticker in `caps` to R1000 (top `LARGE_CAP_COUNT` by market cap)
    or R2000 (the next ones, up to `TOTAL_COUNT` overall); the rest are dropped.
    Ties broken by ticker so the result is deterministic."""
    ranked = caps.sort_values(["market_cap", "ticker"], ascending=[False, True]).head(TOTAL_COUNT)
    ranked = ranked.assign(rank=range(1, len(ranked) + 1))
    ranked["index_name"] = [R1000 if r <= LARGE_CAP_COUNT else R2000 for r in ranked["rank"]]
    return ranked.reset_index(drop=True)


def membership_intervals(yearly: dict[int, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Turn per-year rankings (`rank_year` output, keyed by reconstitution year)
    into `index_membership` intervals per proxy index. A ticker in the same index
    in consecutive years gets one merged interval; the latest year's members stay
    open (end_date None)."""
    years = sorted(yearly)
    starts = {y: reconstitution_day(y) for y in years}
    rows = []
    for i, year in enumerate(years):
        end = starts[years[i + 1]] - pd.Timedelta(days=1) if i + 1 < len(years) else None
        for row in yearly[year].itertuples(index=False):
            rows.append((row.index_name, row.ticker, starts[year], end))
            rows.append((R3000, row.ticker, starts[year], end))
    raw = pd.DataFrame(rows, columns=["index_name", "ticker", "start_date", "end_date"])

    result = {}
    for name in (R1000, R2000, R3000):
        merged = []
        for ticker, group in raw[raw["index_name"] == name].groupby("ticker"):
            group = group.sort_values("start_date")
            cur_start, cur_end = None, None
            for start, end in zip(group["start_date"], group["end_date"]):
                if cur_start is not None and cur_end is not None and start == cur_end + pd.Timedelta(days=1):
                    cur_end = end
                    continue
                if cur_start is not None:
                    merged.append((ticker, cur_start, cur_end))
                cur_start, cur_end = start, end
            merged.append((ticker, cur_start, cur_end))
        result[name] = pd.DataFrame(
            [(t, s.strftime("%Y-%m-%d"), None if pd.isna(e) else e.strftime("%Y-%m-%d")) for t, s, e in merged],
            columns=["ticker", "start_date", "end_date"],
        )
    return result


def build(conn: sqlite3.Connection, start_year: int, end_year: int) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Rank every year in [start_year, end_year] and return (membership per proxy
    index, a per-year coverage summary)."""
    years = list(range(start_year, end_year + 1))
    all_caps = rank_day_caps(conn, [rank_day(y) for y in years])
    yearly, summary = {}, []
    for year in years:
        caps = all_caps[all_caps["rank_day"] == rank_day(year)]
        if caps.empty:
            continue
        ranked = rank_year(caps)
        yearly[year] = ranked
        r2 = ranked[ranked["index_name"] == R2000]
        summary.append({
            "year": year,
            "eligible": len(caps),
            "r1000": int((ranked["index_name"] == R1000).sum()),
            "r2000": len(r2),
            "r1000_cutoff_cap_bn": ranked.loc[ranked["index_name"] == R1000, "market_cap"].min() / 1e9,
            "r2000_smallest_cap_bn": r2["market_cap"].min() / 1e9 if not r2.empty else float("nan"),
        })
    return membership_intervals(yearly) if yearly else {}, pd.DataFrame(summary)


def main():
    parser = argparse.ArgumentParser(description="Build point-in-time Russell 1000/2000/3000 proxy membership")
    parser.add_argument("--start-year", type=int, default=2009)
    parser.add_argument("--end-year", type=int, default=pd.Timestamp.today().year)
    parser.add_argument("--dry-run", action="store_true", help="Print the coverage summary without writing")
    args = parser.parse_args()

    config = load_config()
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)
    membership, summary = build(conn, args.start_year, args.end_year)
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    if args.dry_run or not membership:
        return
    for name, frame in membership.items():
        db.replace_index_membership(conn, name, frame)
        print(f"{name}: {len(frame)} intervals, {frame['ticker'].nunique()} tickers")
    conn.close()


if __name__ == "__main__":
    main()

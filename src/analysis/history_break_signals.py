"""python -m src.analysis.history_break_signals [--out-dir DIR] [--tickers GEVO,AAPL,...]

Standalone, read-only exploration for the planned "irrelevant history"
detector (a per-ticker point where earlier bars stop describing the
company that trades today -- GEVO's split-adjusted $158k 2011 high being
the motivating case). Measures how common each candidate signal is across
the active universe and where natural thresholds fall, *before* any
detector is designed. Nothing here is a detector and nothing is stored in
either DB.

Signals, each with the first date it fires (all computable from data
available on that date -- the detector must be point-in-time safe):

- collapse: close falls >= X% below its running all-time max close. (A
  separate "split-adjusted high >= N x today's close" signal is the same
  thing -- N x below the high is a 1 - 1/N drawdown -- so it isn't measured
  twice.)
- dormancy: trailing 63-bar median dollar volume (close x volume, which is
  split-invariant) sits in the bottom P% of the universe on that date. A
  cross-sectional rank, not a dollar threshold, so 1995's generally thinner
  markets don't flag everything old.
- reverse_splits: cumulative reverse-split factor >= F (from `splits`,
  source=yfinance -- partial while that backfill is still running).
- dilution: shares outstanding grows >= M x within 365 days, restated on
  today's split basis (splits applied from where they actually appear in
  the filing-dated counts, not their execution date) (from `shares_outstanding`,
  coverage from ~2015 only).

Only yfinance `bars_1d` is used: it covers the 5,322 active tickers with
full history; delisted tickers only have Polygon's ~2 years. So this
describes active tickers only.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

RAW_DB_PATH = "data/raw/market_data.sqlite"

COLLAPSE_LEVELS = (0.90, 0.95, 0.99, 0.999)
DORMANCY_PCTILES = (0.01, 0.05, 0.10)
REVERSE_SPLIT_LEVELS = (10, 100, 1000)
DILUTION_LEVELS = (3, 10, 30)
DORMANCY_WINDOW = 63


def _connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def load_bars(conn, tickers: list[str] | None) -> pd.DataFrame:
    query = "SELECT ticker, timestamp, close, volume FROM bars_1d WHERE source = 'yfinance'"
    params: tuple = ()
    if tickers:
        query += f" AND ticker IN ({','.join('?' for _ in tickers)})"
        params = tuple(tickers)
    bars = pd.read_sql_query(query, conn, params=params)
    bars["date"] = pd.to_datetime(bars.pop("timestamp")).dt.normalize()
    bars["ticker"] = bars["ticker"].astype("category")
    bars = bars[bars["close"] > 0].sort_values(["ticker", "date"], kind="stable")
    bars["close"] = bars["close"].astype("float64")
    bars["volume"] = bars["volume"].astype("float64")
    return bars.reset_index(drop=True)


def _first_date(mask: pd.Series, dates: pd.Series, tickers: pd.Series) -> pd.Series:
    hit = dates[mask]
    return hit.groupby(tickers[mask], observed=True).min()


def price_signals(bars: pd.DataFrame) -> pd.DataFrame:
    g = bars.groupby("ticker", observed=True)
    running_max = g["close"].cummax()
    drawdown = 1.0 - bars["close"] / running_max

    out = pd.DataFrame(index=bars["ticker"].cat.categories)
    out.index.name = "ticker"
    out["first_date"] = g["date"].min()
    out["last_date"] = g["date"].max()
    out["n_bars"] = g.size()
    out["last_close"] = g["close"].last()
    out["max_close"] = g["close"].max()
    out["max_close_date"] = bars.loc[g["close"].idxmax(), ["ticker", "date"]].set_index("ticker")["date"]
    out["max_drawdown"] = drawdown.groupby(bars["ticker"], observed=True).max()
    out["peak_to_last"] = out["max_close"] / out["last_close"]

    for level in COLLAPSE_LEVELS:
        out[f"collapse_{level}_date"] = _first_date(drawdown >= level, bars["date"], bars["ticker"])
    return out


def dormancy_signals(bars: pd.DataFrame) -> pd.DataFrame:
    dollar_vol = bars["close"] * bars["volume"]
    med = (
        dollar_vol.groupby(bars["ticker"], observed=True)
        .rolling(DORMANCY_WINDOW, min_periods=DORMANCY_WINDOW)
        .median()
        .reset_index(level=0, drop=True)
    )
    pct_rank = med.groupby(bars["date"]).rank(pct=True)

    out = pd.DataFrame(index=bars["ticker"].cat.categories)
    out.index.name = "ticker"
    valid = pct_rank.notna()
    for p in DORMANCY_PCTILES:
        dormant = valid & (pct_rank <= p)
        by_t = dormant.groupby(bars["ticker"], observed=True)
        out[f"dormant_p{int(p * 100)}_share"] = by_t.sum() / valid.groupby(bars["ticker"], observed=True).sum()
        out[f"dormant_p{int(p * 100)}_last_date"] = bars["date"][dormant].groupby(bars["ticker"][dormant], observed=True).max()
    out["dollar_vol_63d_last"] = med.groupby(bars["ticker"], observed=True).last()
    return out


def split_signals(conn) -> tuple[pd.DataFrame, int, pd.DataFrame]:
    splits = pd.read_sql_query(
        "SELECT ticker, execution_date, ratio FROM splits WHERE source = 'yfinance'",
        conn, parse_dates=["execution_date"],
    )
    n_covered = conn.execute(
        "SELECT COUNT(*) FROM fetch_jobs WHERE job_type = 'splits_yfinance' AND status = 'success'"
    ).fetchone()[0]
    rev = splits[splits["ratio"] < 1].sort_values(["ticker", "execution_date"]).copy()
    rev["cum_reverse"] = 1.0 / rev.groupby("ticker")["ratio"].cumprod()
    out = pd.DataFrame(index=pd.Index(sorted(rev["ticker"].unique()), name="ticker"))
    out["n_reverse_splits"] = rev.groupby("ticker").size()
    out["cum_reverse_factor"] = rev.groupby("ticker")["cum_reverse"].max()
    for level in REVERSE_SPLIT_LEVELS:
        hit = rev[rev["cum_reverse"] >= level]
        out[f"revsplit_{level}x_date"] = hit.groupby("ticker")["execution_date"].min()
    return out, n_covered, splits


SPLIT_SEARCH_DAYS = 250
# Yahoo sometimes shows the post-split count a few days *before* execution
# (NVDA's 2024-06-10 10-for-1 appears on 2024-06-08).
SPLIT_LEAD_DAYS = 30


def _effective_split_dates(shares: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """Share counts follow *filing* dates, which lag a split's execution
    date by weeks (AAPL's 2020-08-31 4-for-1 first shows up in the counts on
    2020-10-22). Adjusting by execution date would turn every forward split
    into fake dilution in that gap. Instead, each split is applied from the
    share-count jump nearest the execution date (from SPLIT_LEAD_DAYS before to
    SPLIT_SEARCH_DAYS after) that matches the split ratio (+-33%); if none
    does, fall back to the execution date.
    """
    by_ticker = {t: g for t, g in shares.groupby("ticker", sort=False)}
    eff = []
    for row in splits.itertuples(index=False):
        g = by_ticker.get(row.ticker)
        date = row.execution_date
        if g is not None:
            window = g[(g["date"] >= row.execution_date - pd.Timedelta(days=SPLIT_LEAD_DAYS))
                       & (g["date"] <= row.execution_date + pd.Timedelta(days=SPLIT_SEARCH_DAYS))]
            if len(window):
                prev = g["s"].shift(1).reindex(window.index)
                jump = window["s"] / prev
                match = jump[(jump >= row.ratio * 0.75) & (jump <= row.ratio / 0.75)]
                if len(match):
                    # Nearest matching jump to the execution date, either side.
                    gap = (window.loc[match.index, "date"] - row.execution_date).abs()
                    date = window.loc[gap.idxmin(), "date"]
        eff.append((row.ticker, date, row.ratio))
    return pd.DataFrame(eff, columns=["ticker", "eff_date", "ratio"])


def dilution_signals(conn, splits: pd.DataFrame) -> pd.DataFrame:
    shares = pd.read_sql_query(
        "SELECT ticker, date, shares_outstanding AS s FROM shares_outstanding "
        "WHERE source = 'yfinance' AND shares_outstanding > 0",
        conn, parse_dates=["date"],
    ).sort_values(["ticker", "date"]).reset_index(drop=True)
    # Drop single-point spikes (Yahoo glitches that revert on the next point).
    g = shares.groupby("ticker")["s"]
    prev, nxt = g.shift(1), g.shift(-1)
    spike = ((shares["s"] / prev > 5) | (shares["s"] / prev < 0.2)) & (nxt / prev).between(0.5, 2)
    shares = shares[~spike].reset_index(drop=True)

    # Restate every point on today's share basis: multiply by the product of
    # all split ratios that take effect *after* it (a suffix product per
    # ticker, joined with a forward as-of merge).
    eff = _effective_split_dates(shares, splits[splits["ticker"].isin(shares["ticker"].unique())])
    eff = eff.sort_values(["ticker", "eff_date"])
    eff["after_prod"] = eff.groupby("ticker")["ratio"].transform(lambda r: r[::-1].cumprod()[::-1])
    merged = pd.merge_asof(
        shares.sort_values("date"), eff[["ticker", "eff_date", "after_prod"]].sort_values("eff_date"),
        left_on="date", right_on="eff_date", by="ticker", direction="forward", allow_exact_matches=False,
    )
    merged["s_adj"] = merged["s"] * merged["after_prod"].fillna(1.0)
    merged = merged.sort_values(["ticker", "date"]).reset_index(drop=True)
    # Drop single-point spikes again on the split-adjusted series: some
    # glitches only look like spikes once splits are divided out (TSLA
    # 2020-08-31 reports 4.66B -- its 5-for-1 applied twice -- between
    # 186M before and 933M after).
    g = merged.groupby("ticker")["s_adj"]
    prev, nxt = g.shift(1), g.shift(-1)
    spike = ((merged["s_adj"] / prev > 3) | (merged["s_adj"] / prev < 1 / 3)) & (nxt / prev).between(0.5, 2)
    merged = merged[~spike].reset_index(drop=True)

    # groupby(sort=True) walks tickers in the same order `merged` is sorted
    # in, so the rolling result lines up with it positionally.
    past_min = merged.groupby("ticker").rolling("365D", on="date")["s_adj"].min()
    merged["growth"] = merged["s_adj"].to_numpy() / past_min.to_numpy()
    out = pd.DataFrame({"max_dilution_1y": merged.groupby("ticker")["growth"].max()})
    for level in DILUTION_LEVELS:
        hit = merged[merged["growth"] >= level]
        out[f"dilution_{level}x_date"] = hit.groupby("ticker")["date"].min()
    out.index.name = "ticker"
    return out


def _pct(n: int, d: int) -> str:
    return f"{n:>5} ({100 * n / d:4.1f}%)" if d else f"{n:>5}"


def report(summary: pd.DataFrame, n_split_covered: int, focus: list[str]) -> str:
    n = len(summary)
    lines = [f"Active tickers with yfinance bars: {n}", ""]

    lines.append("Collapse (drawdown from running max close), tickers ever hitting:")
    for level in COLLAPSE_LEVELS:
        c = summary[f"collapse_{level}_date"].notna().sum()
        lines.append(f"  >= {level:.1%}: {_pct(c, n)}")
    lines.append("Dormancy (63d median $vol in bottom P% of universe that day):")
    for p in DORMANCY_PCTILES:
        col = f"dormant_p{int(p * 100)}_share"
        ever = (summary[col] > 0).sum()
        mostly = (summary[col] > 0.5).sum()
        lines.append(f"  p{int(p * 100)}: ever {_pct(ever, n)}, >50% of history {_pct(mostly, n)}")
    lines.append(f"Reverse splits (yfinance splits, {n_split_covered} tickers fetched so far):")
    for level in REVERSE_SPLIT_LEVELS:
        c = summary.get(f"revsplit_{level}x_date", pd.Series(dtype=object)).notna().sum()
        lines.append(f"  cumulative >= {level}x: {c}")
    if "max_dilution_1y" in summary:
        lines.append("Dilution (split-adjusted shares growth within 1y, data from ~2015):")
        for level in DILUTION_LEVELS:
            c = summary[f"dilution_{level}x_date"].notna().sum()
            lines.append(f"  >= {level}x: {_pct(c, n)}")

    flags = pd.DataFrame({
        "collapse99": summary["collapse_0.99_date"].notna(),
        "dormant_p5_majority": summary["dormant_p5_share"] > 0.5,
        "revsplit10": summary.get("revsplit_10x_date", pd.Series(index=summary.index, dtype=object)).notna(),
        "dilution10": summary.get("dilution_10x_date", pd.Series(index=summary.index, dtype=object)).notna(),
    })
    lines += ["", "Overlap between signals (tickers flagged by row AND column):"]
    overlap = flags.T.astype(int) @ flags.astype(int)
    lines.append(overlap.to_string())
    lines.append("")
    lines.append(f"Flagged by >= 1 signal: {_pct(int(flags.any(axis=1).sum()), n)}; "
                 f">= 2: {_pct(int((flags.sum(axis=1) >= 2).sum()), n)}")

    lines += ["", "First-flag year of collapse>=99% (how old is the break typically):"]
    yrs = summary["collapse_0.99_date"].dropna().dt.year.value_counts().sort_index()
    lines.append("  " + ", ".join(f"{y}:{c}" for y, c in yrs.items()))

    cols = ["first_date", "max_close", "max_close_date", "last_close", "max_drawdown", "peak_to_last",
            "collapse_0.99_date", "dormant_p5_share", "cum_reverse_factor",
            "revsplit_10x_date", "max_dilution_1y", "dilution_10x_date"]
    cols = [c for c in cols if c in summary]
    present = [t for t in focus if t in summary.index]
    if present:
        lines += ["", "Focus tickers:"]
        with pd.option_context("display.width", 250, "display.max_columns", 30):
            lines.append(summary.loc[present, cols].to_string())
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Measure candidate 'irrelevant history' signals (read-only)")
    parser.add_argument("--out-dir", default=None, help="Write per-ticker summary parquet + report here")
    parser.add_argument("--tickers", default=None, help="Comma-separated subset (default: all)")
    parser.add_argument("--focus", default="GEVO,AAPL,MSFT,TSLA,PLTR,AMC,GME,NVDA,SIRI,F")
    args = parser.parse_args()

    conn = _connect(RAW_DB_PATH)
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    bars = load_bars(conn, tickers)
    summary = price_signals(bars).join(dormancy_signals(bars))
    del bars
    split_summary, n_split_covered, splits = split_signals(conn)
    summary = summary.join(split_summary)
    summary = summary.join(dilution_signals(conn, splits))
    conn.close()

    text = report(summary, n_split_covered, [t.strip() for t in args.focus.split(",")])
    print(text)
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        summary.to_parquet(out / "history_break_signals.parquet")
        (out / "history_break_signals_report.txt").write_text(text)


if __name__ == "__main__":
    main()

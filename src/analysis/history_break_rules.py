"""python -m src.analysis.history_break_rules [--out-dir DIR] [--tickers GEVO,AAPL,...]

Read-only measurement of two candidate rules for "irrelevant history",
each point-in-time (uses only what was known at the date it's applied to):

1. Anchor distance (AVWAP / volume-profile anchors). An anchor whose price
   level is more than N x away from today's close can never interact with
   price again -- GEVO's split-adjusted $153k 2011 high against a ~$1.50
   close. Measured two ways per anchor: the anchor bar's own price, and
   the anchored VWAP's current value (what's actually drawn). Reports how
   many anchors each N would drop, by anchor type.

2. Training eligibility, per (ticker, date). A row is ineligible if, as of
   that date: the actual traded (split-unadjusted) close is below $1; or a
   reverse split happened within the last 12 months; or more than half of
   the trailing 63 days had zero volume (an absolute per-stock test -- a
   rank against other tickers would be survivors-only here).
   Reports the share of rows each condition removes, by year, and each
   reviewed ticker's ineligible spans next to the manual cut from the
   History Break Review page.

Nothing is stored in either DB. yfinance bars only (active tickers).
Note: yfinance closes are also dividend-adjusted, so the "unadjusted"
close is split-unadjusted only -- close enough for a $1 threshold.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.market_common.anchors import AnchorConfig, discover_anchors
from src.foundation.market_common.models import Timeframe
from src.signals.avwap.compute import anchored_vwap

RAW_DB_PATH = "data/raw/market_data.sqlite"
DISTANCE_LEVELS = (5, 10, 20, 50, 100)
PENNY_PRICE = 1.0
REVERSE_SPLIT_COOLDOWN_DAYS = 365
ZERO_VOLUME_SHARE = 0.5  # dormant: >50% of the trailing window's days had zero volume
PRE_SPLIT_WINDOW = 20
CUM_REVERSE_RESET = 20
DORMANCY_WINDOW = 63

# The History Break Review page's saved decisions (ticker -> cut date or None).
REVIEWED = {
    "GEVO": "2018-08-10", "MTA": "2019-12-20", "PARR": "2014-01-29", "POWW": "2017-05-05",
    "PRPO": "2018-12-07", "YDKG": "2022-12-23",
    "AMC": None, "ATS": None, "AVBH": None, "B": None, "BNY": None, "CBAT": None, "CHRD": None,
    "INTT": None, "PDS": None, "PRTS": None, "RDIB": None, "SIRI": None,
}


def _connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def load_bars(conn, tickers: list[str] | None) -> pd.DataFrame:
    q = "SELECT ticker, timestamp, open, high, low, close, volume FROM bars_1d WHERE source = 'yfinance'"
    params: tuple = ()
    if tickers:
        q += f" AND ticker IN ({','.join('?' for _ in tickers)})"
        params = tuple(tickers)
    bars = pd.read_sql_query(q, conn, params=params)
    bars["date"] = pd.to_datetime(bars.pop("timestamp")).dt.normalize()
    bars = bars[(bars["close"] > 0) & (bars["high"] > 0) & (bars["low"] > 0)]
    return bars.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------- anchors

def anchor_distances(bars: pd.DataFrame) -> pd.DataFrame:
    # True all-time extremes, as measured for Done #62 -- the regime reach
    # rule added later (AnchorConfig.regime_reach_factor) would drop exactly
    # the far anchors this measurement is about.
    config = AnchorConfig(regime_reach_factor=None)
    rows = []
    for ticker, g in bars.groupby("ticker", sort=False):
        g = g.set_index("date")
        if len(g) < config.min_bars:
            continue
        last = float(g["close"].iloc[-1])
        for a in discover_anchors(g, Timeframe.DAILY, config):
            d = pd.Timestamp(a.anchor_date)
            roles = sorted(t.value for t in a.anchor_types)
            is_low = any(r.endswith("low") or r == "atl" for r in roles)
            anchor_price = float(g.loc[d, "low" if is_low else "high"])
            avwap_now = float(anchored_vwap(g, d).iloc[-1])
            rows.append({
                "ticker": ticker, "anchor_date": d, "roles": ",".join(roles), "status": a.status.value,
                "last_close": last, "anchor_price": anchor_price, "avwap_now": avwap_now,
                "price_dist": max(anchor_price / last, last / anchor_price),
                "avwap_dist": max(avwap_now / last, last / avwap_now) if avwap_now > 0 else np.nan,
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------- anchor reset date

def anchor_resets(bars: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """Per ticker, the date from which anchor discovery would start under
    two candidate triggers (latest qualifying reverse split wins):

    - cum20: the cumulative reverse-split factor, counted over consecutive
      reverse splits no more than 3 years apart, reaches CUM_REVERSE_RESET.
    - penny: a reverse split executed while the stock actually traded below
      PENNY_PRICE (median split-unadjusted close over the PRE_SPLIT_WINDOW
      bars before it) -- a split done to stay listed, not a late 1-for-10
      in an established company.
    """
    closes = {t: g.set_index("date")["close"] for t, g in bars.groupby("ticker", sort=False)}
    sp = splits.sort_values(["ticker", "execution_date"])
    rows = []
    for ticker, g in sp.groupby("ticker"):
        if ticker not in closes:
            continue
        c = closes[ticker]
        dates, ratios = g["execution_date"].to_numpy(), g["ratio"].to_numpy()
        cum20, penny, run, prev_rev = None, None, 1.0, None
        for i, (d, r) in enumerate(zip(dates, ratios)):
            if r >= 1:
                continue
            d = pd.Timestamp(d)
            run = run / r if prev_rev is not None and (d - prev_rev).days <= 3 * 365 else 1.0 / r
            prev_rev = d
            if run >= CUM_REVERSE_RESET:
                cum20 = d
            before = c[c.index < d].tail(PRE_SPLIT_WINDOW)
            if len(before):
                # split-unadjusted = adjusted x product of ratios from this split on
                raw = float(before.median()) * float(np.prod(ratios[i:]))
                if raw < PENNY_PRICE:
                    penny = d
        rows.append({"ticker": ticker, "reset_cum20": cum20, "reset_penny": penny})
    return pd.DataFrame(rows, columns=["ticker", "reset_cum20", "reset_penny"]).set_index("ticker")


# ------------------------------------------------------ training eligibility

def eligibility(bars: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    b = bars[["ticker", "date", "close", "volume"]].copy()

    # Split-unadjusted close: adjusted close x the product of split ratios
    # taking effect after the date (a later 1-for-20 has ratio 0.05, so the
    # price actually traded back then was the adjusted close x 0.05).
    sp = splits.sort_values(["ticker", "execution_date"]).copy()
    sp["after_prod"] = sp.groupby("ticker")["ratio"].transform(lambda r: r[::-1].cumprod()[::-1])
    b = pd.merge_asof(
        b.sort_values("date"), sp[["ticker", "execution_date", "after_prod"]].sort_values("execution_date"),
        left_on="date", right_on="execution_date", by="ticker", direction="forward", allow_exact_matches=False,
    ).drop(columns="execution_date")
    b["raw_close"] = b["close"] * b["after_prod"].fillna(1.0)

    # Most recent reverse split on or before each date.
    rev = sp[sp["ratio"] < 1][["ticker", "execution_date"]].rename(columns={"execution_date": "last_rev"})
    b = pd.merge_asof(
        b.sort_values("date"), rev.sort_values("last_rev"),
        left_on="date", right_on="last_rev", by="ticker", direction="backward",
    )
    b = b.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Absolute, per-stock test (no ranking against other tickers, whose set
    # here is survivors only): more than half of the trailing window's days
    # had zero volume.
    zero = (b["volume"] <= 0).astype("float64")
    zero_share = (
        zero.groupby(b["ticker"]).rolling(DORMANCY_WINDOW, min_periods=DORMANCY_WINDOW).mean()
        .reset_index(level=0, drop=True)
    )

    b["penny"] = b["raw_close"] < PENNY_PRICE
    b["post_reverse_split"] = (b["date"] - b["last_rev"]).dt.days.between(0, REVERSE_SPLIT_COOLDOWN_DAYS)
    b["dormant"] = (zero_share > ZERO_VOLUME_SHARE).fillna(False)
    b["ineligible"] = b["penny"] | b["post_reverse_split"] | b["dormant"]
    return b[["ticker", "date", "raw_close", "penny", "post_reverse_split", "dormant", "ineligible"]]


def _spans(dates: pd.Series, flags: pd.Series) -> list[tuple[str, str]]:
    """Contiguous runs of True, as (first, last) ISO dates; gaps <= 10 trading rows merged."""
    idx = np.flatnonzero(flags.to_numpy())
    if not len(idx):
        return []
    out, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > 10:
            out.append((start, prev))
            start = i
        prev = i
    out.append((start, prev))
    d = dates.to_numpy()
    return [(str(pd.Timestamp(d[a]).date()), str(pd.Timestamp(d[z]).date())) for a, z in out]


# ------------------------------------------------------------------ report

def report(anchors: pd.DataFrame, elig: pd.DataFrame, resets: pd.DataFrame) -> str:
    L = []
    n = len(anchors)
    L.append(f"ANCHORS: {n} across {anchors['ticker'].nunique()} tickers (default AnchorConfig, daily)")
    L.append("  share of anchors dropped at distance > N x from today's close:")
    L.append("    N      by anchor price    by current AVWAP value")
    for N in DISTANCE_LEVELS:
        p, v = (anchors["price_dist"] > N).mean(), (anchors["avwap_dist"] > N).mean()
        L.append(f"    {N:<5}  {p:>8.1%} ({(anchors['price_dist'] > N).sum():>5})   {v:>8.1%} ({(anchors['avwap_dist'] > N).sum():>5})")
    L.append("  tickers losing >= 1 anchor at N=20 (by AVWAP): "
             f"{anchors.loc[anchors['avwap_dist'] > 20, 'ticker'].nunique()}")
    primary = anchors["roles"].str.split(",").str[0]
    L.append("  AVWAP distance > 20x by anchor role: " + ", ".join(
        f"{r} {(anchors.loc[primary == r, 'avwap_dist'] > 20).mean():.1%}" for r in sorted(primary.unique())))

    L.append("")
    L.append("ANCHOR RESET (anchors searched only from the latest qualifying reverse split):")
    for col in ("reset_cum20", "reset_penny"):
        r = resets[col].dropna()
        a = anchors.join(r.rename("reset"), on="ticker")
        dropped = a["anchor_date"] < a["reset"]
        L.append(f"  {col:<12} tickers reset {len(r):>5}; anchors dated before the reset {int(dropped.sum()):>5} "
                 f"({dropped.mean():.1%} of all), in {a.loc[dropped, 'ticker'].nunique()} tickers")
    L.append("")
    L.append(f"TRAINING ELIGIBILITY: {len(elig):,} ticker-days")
    for c in ("penny", "post_reverse_split", "dormant", "ineligible"):
        L.append(f"  {c:<20} {elig[c].mean():6.1%} of rows, {elig.loc[elig[c], 'ticker'].nunique():>5} tickers ever")
    by_year = elig.groupby(elig["date"].dt.year)["ineligible"].mean()
    L.append("  ineligible share by year: " + ", ".join(f"{y}:{v:.0%}" for y, v in by_year.items() if y >= 1995))

    L += ["", "REVIEWED TICKERS (your call vs. the two rules)"]
    for t, cut in REVIEWED.items():
        a = anchors[anchors["ticker"] == t]
        dropped = a[a["avwap_dist"] > 20]
        e = elig[elig["ticker"] == t]
        spans = _spans(e["date"], e["ineligible"])
        share = e["ineligible"].mean() if len(e) else float("nan")
        rc = resets["reset_cum20"].get(t) if t in resets.index else None
        rp = resets["reset_penny"].get(t) if t in resets.index else None
        fmt = lambda x: str(pd.Timestamp(x).date()) if x is not None and not pd.isna(x) else "none"
        L.append(f"  {t:<5} your call: {'cut ' + cut if cut else 'keep all'}   | anchor reset cum20: {fmt(rc)}, penny: {fmt(rp)}")
        L.append(f"        anchors: {len(a)}, dropped at N=20: "
                 + (", ".join(f"{r.roles}@{r.anchor_date.date()} ({r.avwap_dist:,.0f}x)" for r in dropped.itertuples()) or "none"))
        L.append(f"        training: {share:.0%} of rows ineligible; spans: "
                 + ("; ".join(f"{s}..{z}" for s, z in spans[:6]) + (" ..." if len(spans) > 6 else "") if spans else "none"))
    return "\n".join(L)


def main():
    parser = argparse.ArgumentParser(description="Measure anchor-distance and training-eligibility rules (read-only)")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--tickers", default=None)
    args = parser.parse_args()

    conn = _connect(RAW_DB_PATH)
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    bars = load_bars(conn, tickers)
    splits = pd.read_sql_query(
        "SELECT ticker, execution_date, ratio FROM splits WHERE source = 'yfinance'", conn, parse_dates=["execution_date"]
    )
    conn.close()

    anchors = anchor_distances(bars)
    resets = anchor_resets(bars, splits)
    elig = eligibility(bars, splits)
    text = report(anchors, elig, resets)
    print(text)
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        anchors.to_parquet(out / "anchor_distances.parquet")
        resets.to_parquet(out / "anchor_resets.parquet")
        elig.to_parquet(out / "eligibility.parquet")
        (out / "history_break_rules_report.txt").write_text(text)


if __name__ == "__main__":
    main()

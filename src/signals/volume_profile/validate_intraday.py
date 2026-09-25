"""python -m src.signals.volume_profile.validate_intraday [--tickers ...] [--cache-dir DIR]

Is a volume profile built from *daily* bars (each bar's volume spread
evenly across its high-low range) close enough to one built from finer
bars? This project only has daily history (bars_1h is empty); Yahoo serves
~730 days of 1h bars for free. For each ticker this fetches both over that
same window, builds `compute.build_profile` twice per (anchor, as_of) --
once from hourly bars (the reference) and once from daily -- and reports
POC/VAH/VAL disagreement in daily-ATR units, bucketed by anchor age.

Hourly is itself spread uniformly within each hour, so it's a proxy for
the trade-level truth, not the truth -- but ~7x finer, so what's being
measured is how much the daily approximation loses relative to it.

Both series come from yfinance with the same (split+dividend) adjustment,
so the comparison isolates the distribution approximation rather than a
source/adjustment mismatch. Anchors: the real market_common.anchors
discovery run on the in-window daily bars, plus fixed-age synthetic
anchors so short-lived anchors are covered too, each evaluated at three
as_of points. Fetched bars are cached as parquet under --cache-dir
(gitignored data/processed by default) -- never written to the raw DB.
Also reports: a cruder daily baseline (all volume at hlc3), and POC
stability of the daily profile across 50/100/200 rows.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.anchors import AnchorConfig, discover_anchors
from src.foundation.market_common.models import Timeframe
from src.signals.volume_profile.compute import build_profile

DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "BAC", "XOM", "CVX",
    "JNJ", "PFE", "WMT", "KO", "PG", "HD", "CAT", "BA", "DIS", "NFLX",
    "T", "INTC", "AMD", "F", "GE", "PLTR", "SOFI", "GEVO",
]
SYNTHETIC_AGES = [5, 10, 20, 40, 60, 120, 250, 400]
AS_OF_OFFSETS = [0, 60, 120]  # bars back from the last daily bar
AGE_BUCKETS = [(0, 20, "<20"), (20, 60, "20-60"), (60, 250, "60-250"), (250, 10_000, "250+")]


def _fetch(ticker: str, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    from src.foundation.data_processing.yfinance_client import YFinanceClient

    cache_dir.mkdir(parents=True, exist_ok=True)
    hourly_path, daily_path = cache_dir / f"{ticker}_1h.parquet", cache_dir / f"{ticker}_1d.parquet"
    if hourly_path.exists() and daily_path.exists():
        return pd.read_parquet(hourly_path), pd.read_parquet(daily_path)

    client = YFinanceClient()
    end = pd.Timestamp.today().normalize()
    hourly = client.get_hourly_bars(ticker, end - pd.Timedelta(days=725), end)
    if hourly.empty:
        return hourly, hourly
    start = hourly.index.min().normalize()
    daily = client.get_daily_bars(ticker, start, end)
    hourly.to_parquet(hourly_path)
    daily.to_parquet(daily_path)
    return hourly, daily


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna()
    return df[(df["volume"] > 0) & (df["high"] >= df["low"]) & (df["low"] > 0)]


def _anchors(daily: pd.DataFrame) -> list[tuple[str, str]]:
    config = AnchorConfig(warmup_bars=20)
    found = [
        (a.anchor_date, "+".join(sorted(t.value for t in a.anchor_types)))
        for a in discover_anchors(daily, Timeframe.DAILY, config)
    ]
    found += [(daily.index[-1 - age].isoformat(), f"synthetic_{age}") for age in SYNTHETIC_AGES if age < len(daily)]
    return found


def _rows_for_ticker(ticker: str, hourly: pd.DataFrame, daily: pd.DataFrame) -> list[dict]:
    atr = indicators.atr(daily, 14)
    hlc3_daily = daily.assign(high=(daily["high"] + daily["low"] + daily["close"]) / 3.0)
    hlc3_daily["low"] = hlc3_daily["high"]

    rows = []
    for anchor_date, kind in _anchors(daily):
        for offset in AS_OF_OFFSETS:
            as_of = daily.index[-1 - offset]
            anchor_ts = pd.Timestamp(anchor_date)
            if anchor_ts > as_of:
                continue
            d = daily.loc[:as_of]
            h = hourly.loc[: as_of + pd.Timedelta(days=1)]
            age = int((d.index >= anchor_ts).sum())
            a = float(atr.loc[as_of])
            if not np.isfinite(a) or a <= 0:
                continue

            ref = build_profile(h, anchor_date, row_count=100)
            est = build_profile(d, anchor_date, row_count=100)
            naive = build_profile(hlc3_daily.loc[:as_of], anchor_date, row_count=100)
            if ref is None or est is None or naive is None:
                continue
            by_rows = {n: build_profile(d, anchor_date, row_count=n) for n in (50, 200)}
            ref_by_rows = {n: build_profile(h, anchor_date, row_count=n) for n in (50, 200)}

            rows.append({
                "ticker": ticker, "kind": kind, "anchor_date": anchor_date, "as_of": as_of, "age": age,
                "range_atr": (est.edges[-1] - est.edges[0]) / a,
                "poc_gap": abs(ref.poc - est.poc) / a,
                "vah_gap": abs(ref.vah - est.vah) / a,
                "val_gap": abs(ref.val - est.val) / a,
                "poc_gap_naive": abs(ref.poc - naive.poc) / a,
                "poc_50_vs_100": abs(by_rows[50].poc - est.poc) / a,
                "poc_200_vs_100": abs(by_rows[200].poc - est.poc) / a,
                "poc_gap_50": abs(ref_by_rows[50].poc - by_rows[50].poc) / a,
                "poc_gap_200": abs(ref_by_rows[200].poc - by_rows[200].poc) / a,
                "volume_ratio": est.total.sum() / ref.total.sum(),
            })
    return rows


def _summary(results: pd.DataFrame) -> pd.DataFrame:
    results = results.copy()
    results["age_bucket"] = pd.cut(
        results["age"], [b[0] for b in AGE_BUCKETS] + [AGE_BUCKETS[-1][1]],
        labels=[b[2] for b in AGE_BUCKETS], right=False,
    )
    agg = {
        "n": ("poc_gap", "size"),
        "tickers": ("ticker", "nunique"),
        "range_atr_med": ("range_atr", "median"),
        "poc_gap_med": ("poc_gap", "median"),
        "poc_gap_p90": ("poc_gap", lambda s: s.quantile(0.9)),
        "vah_gap_med": ("vah_gap", "median"),
        "val_gap_med": ("val_gap", "median"),
        "poc_gap_naive_med": ("poc_gap_naive", "median"),
        "poc_gap_50_med": ("poc_gap_50", "median"),
        "poc_gap_200_med": ("poc_gap_200", "median"),
        "poc_50_vs_100_med": ("poc_50_vs_100", "median"),
        "poc_200_vs_100_med": ("poc_200_vs_100", "median"),
    }
    by_bucket = results.groupby("age_bucket", observed=True).agg(**agg)
    by_bucket.loc["all"] = results.assign(age_bucket="all").groupby("age_bucket").agg(**agg).iloc[0]
    return by_bucket


def main():
    parser = argparse.ArgumentParser(description="Daily-vs-hourly volume profile accuracy check")
    parser.add_argument("--tickers", nargs="*", default=DEFAULT_TICKERS)
    parser.add_argument("--cache-dir", default="data/processed/volume_profile_intraday")
    parser.add_argument("--out", default=None, metavar="CSV", help="Write per-(anchor, as_of) rows here")
    args = parser.parse_args()

    all_rows = []
    for ticker in args.tickers:
        try:
            hourly, daily = _fetch(ticker, Path(args.cache_dir))
        except Exception as exc:  # continue-on-error per ticker, as in every module CLI
            print(f"{ticker}: FAILED fetch -- {exc}")
            continue
        hourly, daily = _clean(hourly), _clean(daily)
        if len(daily) < 250 or hourly.empty:
            print(f"{ticker}: SKIPPED -- {len(daily)} daily / {len(hourly)} hourly bars")
            continue
        rows = _rows_for_ticker(ticker, hourly, daily)
        print(f"{ticker}: {len(daily)} daily / {len(hourly)} hourly bars, {len(rows)} comparisons")
        all_rows.extend(rows)

    results = pd.DataFrame(all_rows)
    if args.out:
        results.to_csv(args.out, index=False)
    with pd.option_context("display.width", 200, "display.max_columns", 30, "display.precision", 2):
        print("\nGaps in daily-ATR units (median unless noted), by anchor age in daily bars:")
        print(_summary(results))
        print(f"\nDaily/hourly total-volume ratio: median {results['volume_ratio'].median():.3f}")


if __name__ == "__main__":
    main()

"""Vendor as a hidden future signal (`docs/backlog.md`; checked before E1).

The modeling dataset reads a ticker from Tiingo only when yfinance has no bars
for it at all, which in practice means it was later delisted. If Tiingo's bars
differ systematically from yfinance's, a model can learn the vendor and with it
the delisting -- a leak no perturbation gate can see, since the values don't
depend on the future, only their vendor does.

Three read-outs, from the model-feature cache plus the raw bars:
- **fingerprints** per vendor: zero-volume days, flat bars (high == low), and
  missing sessions against the common calendar -- data-quality traits with no
  economic meaning;
- **feature shift**: per model input, the standardised mean difference between
  Tiingo rows at least `FAR_DAYS` before the ticker's delisting (Tiingo's listing
  end, `tiingo_listings` -- metadata, not holdout prices) and yfinance rows on
  the same dates (far from delisting, so the run-up to it isn't the cause);
- **classifier**: a boosted model telling Tiingo rows from yfinance rows, folds
  grouped by ticker (so it can't memorise names), scored **within date**: the
  chance a Tiingo row outranks a yfinance row on the same day. Tiingo rows sit
  in earlier years, and several inputs drift with the market, so a pooled AUC
  would partly measure "which year". On all rows and on the far rows, with and
  without `sector` (sourced differently).

An AUC near 0.5 on far rows means nothing vendor-specific is learnable. A high
one is not proof of an artefact -- companies that later leave the index can
differ for real years before -- so the fingerprints and the per-column shifts
say which it is.

A fourth read-out, **same ticker** (`same_ticker`), removes that ambiguity:
live tickers stored on both vendors (Tiingo bars for comparison only; they're
still read from yfinance everywhere) get every registered feature computed
twice, once per vendor, on the same dates. Any difference is then the vendor
alone. It passes when a vendor classifier can't beat `SAME_TICKER_MAX_AUC`
(within date, ticker-grouped folds) and no model input's median gap reaches
`SAME_TICKER_MAX_GAP_SD` cross-sectional SDs. First run (2026-10-07, 4
baseline features, 332 tickers): AUC 0.502, largest gap 0.011 SD. Read-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

from src.foundation.data_processing import db
from src.foundation.market_common.price_basis import PriceBasis
from src.models.features import registry

FAR_DAYS = 730
TIINGO_SOURCES = (db.TIINGO, db.TIINGO_SPLIT_ONLY)

SAME_TICKER_MAX_AUC = 0.55
SAME_TICKER_MAX_GAP_SD = 0.05
# Each vendor's bars on each basis, and the splits that go with them.
VENDOR_SOURCES = {
    "yfinance": {PriceBasis.TOTAL_RETURN: db.YFINANCE, PriceBasis.TRADED: db.YFINANCE_SPLIT_ONLY},
    "tiingo": {PriceBasis.TOTAL_RETURN: db.TIINGO, PriceBasis.TRADED: db.TIINGO_SPLIT_ONLY},
}
VENDOR_SPLITS = {"yfinance": db.YFINANCE, "tiingo": db.TIINGO}


def fingerprints(bars: pd.DataFrame, sources: dict[str, str], calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Per vendor: share of zero-volume bars, of flat bars (high == low), and of
    sessions missing between each ticker's first and last bar."""
    rows = []
    cal = np.asarray(calendar, dtype="datetime64[ns]")
    for ticker, g in bars.groupby("ticker", sort=False):
        d = g["date"].to_numpy(dtype="datetime64[ns]")
        expected = int(((cal >= d.min()) & (cal <= d.max())).sum())
        rows.append({
            "vendor": "tiingo" if sources.get(ticker) in TIINGO_SOURCES else "yfinance", "ticker": ticker,
            "bars": len(g), "zero_volume": int((g["volume"] <= 0).sum()),
            "flat": int((g["high"] <= g["low"]).sum()), "missing": max(expected - len(g), 0), "expected": expected,
        })
    per = pd.DataFrame(rows)
    out = per.groupby("vendor").agg(tickers=("ticker", "size"), bars=("bars", "sum"), zero_volume=("zero_volume", "sum"),
                                    flat=("flat", "sum"), missing=("missing", "sum"), expected=("expected", "sum"))
    return pd.DataFrame({
        "tickers": out["tickers"], "bars": out["bars"],
        "zero_volume_share": out["zero_volume"] / out["bars"], "flat_bar_share": out["flat"] / out["bars"],
        "missing_session_share": out["missing"] / out["expected"],
    })


def tag_rows(features: pd.DataFrame, sources: dict[str, str], delisted: pd.Series) -> pd.DataFrame:
    """Adds `tiingo` (bool) and `far` (Tiingo row >= FAR_DAYS before its
    ticker's delisting date, `delisted`; every yfinance row counts as far)."""
    out = features.copy()
    out["tiingo"] = out["ticker"].map(sources).isin(TIINGO_SOURCES)
    days_left = (out["ticker"].map(pd.to_datetime(delisted)) - out["date"]).dt.days
    out["far"] = ~out["tiingo"] | (days_left >= FAR_DAYS)
    return out


def feature_shift(rows: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Standardised mean difference (Tiingo far rows minus yfinance rows on the
    dates both have), per column, with the pooled SD."""
    far = rows[rows["far"]]
    dates = set(far.loc[far["tiingo"], "date"])
    far = far[far["date"].isin(dates)]
    t, y = far[far["tiingo"]], far[~far["tiingo"]]
    out = []
    for c in columns:
        a, b = t[c].astype(float), y[c].astype(float)
        sd = np.sqrt((a.var() + b.var()) / 2)
        out.append({"column": c, "tiingo_mean": a.mean(), "yfinance_mean": b.mean(),
                    "smd": (a.mean() - b.mean()) / sd if sd > 0 else np.nan,
                    "tiingo_missing": a.isna().mean(), "yfinance_missing": b.isna().mean()})
    return pd.DataFrame(out).sort_values("smd", key=np.abs, ascending=False, ignore_index=True)


def within_date_auc(scores: np.ndarray, y: np.ndarray, dates: np.ndarray) -> float:
    """Mean over dates of each date's AUC, weighted by its (Tiingo x yfinance)
    pair count: P(a Tiingo row outscores a yfinance row on the same date)."""
    frame = pd.DataFrame({"s": scores, "y": y.astype(bool), "d": dates})
    frame["r"] = frame.groupby("d")["s"].rank()
    g = frame.groupby("d")
    n_pos, n = g["y"].sum(), g.size()
    n_neg = n - n_pos
    rank_sum = frame[frame["y"]].groupby("d")["r"].sum().reindex(n.index, fill_value=0.0)
    pairs = n_pos * n_neg
    ok = pairs > 0
    auc = (rank_sum[ok] - n_pos[ok] * (n_pos[ok] + 1) / 2) / pairs[ok]
    return float((auc * pairs[ok]).sum() / pairs[ok].sum())


def vendor_auc(rows: pd.DataFrame, columns: list[str], n_splits: int = 5, seed: int = 0) -> float:
    """Out-of-sample, within-date AUC for telling Tiingo rows from yfinance
    rows, folds grouped by ticker; only dates that have rows of both."""
    both = rows.groupby("date")["tiingo"].transform(lambda t: t.any() and not t.all())
    rows = rows[both]
    x, y, groups = rows[columns], rows["tiingo"].to_numpy(), rows["ticker"].to_numpy()
    scores = np.full(len(rows), np.nan)
    for train, test in GroupKFold(n_splits=n_splits).split(x, y, groups):
        model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                               min_samples_leaf=1000, categorical_features="from_dtype",
                                               random_state=seed)
        model.fit(x.iloc[train], y[train])
        scores[test] = model.predict_proba(x.iloc[test])[:, 1]
    return within_date_auc(scores, y, rows["date"].to_numpy())


def run(features: pd.DataFrame, bars: pd.DataFrame, sources: dict[str, str], calendar: pd.DatetimeIndex,
        delisted: pd.Series) -> dict:
    """`features`: the model-feature cache; `bars`: the label-basis bars of
    the same tickers (for the fingerprints); `delisted`: ticker -> delisting
    date for the Tiingo tickers (Tiingo's listing end)."""
    inputs = [registry.model_input(s) for s in registry.model_specs()]
    numeric = [c for c in inputs if c != "sector"]
    rows = tag_rows(features, sources, delisted)
    far = rows[rows["far"]]
    return {
        "n_rows": len(rows), "n_tiingo_rows": int(rows["tiingo"].sum()), "n_tiingo_far_rows": int(far["tiingo"].sum()),
        "n_tiingo_tickers": int(rows.loc[rows["tiingo"], "ticker"].nunique()),
        "fingerprints": fingerprints(bars, sources, calendar),
        "feature_shift": feature_shift(rows, numeric),
        "auc": {
            "all_rows": vendor_auc(rows, inputs), "far_rows": vendor_auc(far, inputs),
            "far_rows_without_sector": vendor_auc(far, numeric),
        },
    }


# ---------------------------------------------------------------- same ticker

def both_vendor_tickers(conn, tickers: list[str]) -> list[str]:
    """Of `tickers`, those with bars from both vendors."""
    def has(t, source):
        return conn.execute("SELECT 1 FROM bars_1d WHERE ticker = ? AND source = ? LIMIT 1", (t, source)).fetchone()
    return [t for t in tickers if has(t, db.YFINANCE) and has(t, db.TIINGO)]


def _vendor_bars(conn, tickers: list[str], source: str, start, end) -> pd.DataFrame:
    frames = []
    for i in range(0, len(tickers), 500):
        batch = tickers[i:i + 500]
        frames.append(pd.read_sql_query(
            "SELECT ticker, timestamp, open, high, low, close, volume FROM bars_1d "
            f"WHERE source = ? AND is_partial = 0 AND ticker IN ({','.join('?' * len(batch))}) "
            "AND timestamp >= ? AND timestamp <= ?",
            conn, params=[source, *batch, pd.Timestamp(start).isoformat(),
                          (pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59)).isoformat()]))
    bars = pd.concat(frames, ignore_index=True)
    bars["date"] = pd.to_datetime(bars.pop("timestamp")).dt.normalize()
    return bars.drop_duplicates(["ticker", "date"], keep="last").sort_values(["ticker", "date"], ignore_index=True)


def vendor_features(conn, tickers: list[str], vendor: str, start, end) -> pd.DataFrame:
    """Every registered column for `tickers` in [start, end], from `vendor`'s
    bars and splits only (warm-up read before `start`)."""
    warm = pd.Timestamp(start) - pd.Timedelta(days=int(1.6 * max(s.warmup_bars for s in registry.REGISTRY)) + 30)
    bars = {basis: _vendor_bars(conn, tickers, source, warm, end) for basis, source in VENDOR_SOURCES[vendor].items()}
    splits = {}
    for t in tickers:
        sp = db.read_splits(conn, t, VENDOR_SPLITS[vendor])
        if not sp.empty:
            splits[t] = sp
    f = registry.compute_registered(bars, splits)
    return f[f["date"].between(pd.Timestamp(start), pd.Timestamp(end))].reset_index(drop=True)


def feature_gaps(yf: pd.DataFrame, ti: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Per column, on the (ticker, date) rows both vendors have: the median
    |Tiingo - yfinance| in units of the cross-sectional SD (median over dates
    of the per-date SD of the yfinance values), the share of rows off by more
    than 0.1 SD, and the share where only one vendor is missing the value."""
    j = yf.merge(ti, on=["ticker", "date"], suffixes=("_yf", "_ti"))
    out = []
    for c in columns:
        a, b = j[f"{c}_yf"].astype(float), j[f"{c}_ti"].astype(float)
        both = a.notna() & b.notna()
        sd = a[both].groupby(j.loc[both, "date"]).std().median()
        gap = (b[both] - a[both]).abs() / sd if sd > 0 else pd.Series(np.nan, index=a[both].index)
        out.append({"column": c, "median_gap_sd": float(gap.median()), "share_over_0.1sd": float((gap > 0.1).mean()),
                    "nan_mismatch": float((a.isna() != b.isna()).mean())})
    return pd.DataFrame(out).sort_values("median_gap_sd", ascending=False, ignore_index=True)


def same_ticker(conn, tickers: list[str], start, end, seed: int = 0) -> dict:
    """The same-ticker read-out for `tickers` (stored on both vendors) over
    [start, end]. `passed` applies SAME_TICKER_MAX_AUC and
    SAME_TICKER_MAX_GAP_SD to the numeric model inputs (sector is the same
    value for both vendors of one ticker, so it can't separate them)."""
    numeric = [registry.model_input(s) for s in registry.model_specs() if s.name != "sector"]
    yf = vendor_features(conn, tickers, "yfinance", start, end)
    ti = vendor_features(conn, tickers, "tiingo", start, end)
    gaps = feature_gaps(yf, ti, numeric)
    rows = pd.concat([yf.assign(tiingo=False), ti.assign(tiingo=True)], ignore_index=True)
    auc = vendor_auc(rows, numeric, seed=seed)
    return {
        "n_tickers": len(tickers), "n_rows": {"yfinance": len(yf), "tiingo": len(ti)},
        "gaps": gaps, "auc": auc,
        "passed": bool(auc <= SAME_TICKER_MAX_AUC and (gaps["median_gap_sd"] < SAME_TICKER_MAX_GAP_SD).all()),
    }

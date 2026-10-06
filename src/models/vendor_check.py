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
  Tiingo rows at least `FAR_DAYS` before the ticker's last bar and yfinance rows
  on the same dates (far from delisting, so the run-up to it isn't the cause);
- **classifier**: out-of-sample AUC of a boosted model telling Tiingo rows from
  yfinance rows, folds grouped by ticker (so it can't memorise names), on all
  rows and on the far rows, with and without `sector` (sourced differently).

An AUC near 0.5 on far rows means nothing vendor-specific is learnable. A high
one is not proof of an artefact -- companies that later leave the index can
differ for real years before -- so the fingerprints and the per-column shifts
say which it is. Read-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from src.foundation.data_processing import db
from src.models.features import registry

FAR_DAYS = 730
TIINGO_SOURCES = (db.TIINGO, db.TIINGO_SPLIT_ONLY)


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


def tag_rows(features: pd.DataFrame, sources: dict[str, str], last_bar: pd.Series) -> pd.DataFrame:
    """Adds `tiingo` (bool) and `far` (Tiingo row >= FAR_DAYS before its
    ticker's last bar; every yfinance row counts as far)."""
    out = features.copy()
    out["tiingo"] = out["ticker"].map(sources).isin(TIINGO_SOURCES)
    days_left = (out["ticker"].map(last_bar) - out["date"]).dt.days
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


def vendor_auc(rows: pd.DataFrame, columns: list[str], n_splits: int = 5, seed: int = 0) -> float:
    """Out-of-sample AUC for telling Tiingo rows from yfinance rows, folds
    grouped by ticker."""
    x, y, groups = rows[columns], rows["tiingo"].to_numpy(), rows["ticker"].to_numpy()
    scores = np.full(len(rows), np.nan)
    for train, test in GroupKFold(n_splits=n_splits).split(x, y, groups):
        model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                               min_samples_leaf=1000, categorical_features="from_dtype",
                                               random_state=seed)
        model.fit(x.iloc[train], y[train])
        scores[test] = model.predict_proba(x.iloc[test])[:, 1]
    return float(roc_auc_score(y, scores))


def run(features: pd.DataFrame, bars: pd.DataFrame, sources: dict[str, str], calendar: pd.DatetimeIndex) -> dict:
    """`features`: the model-feature cache; `bars`: the label-basis bars of
    the same tickers (for fingerprints and each ticker's last bar)."""
    inputs = [registry.model_input(s) for s in registry.model_specs()]
    numeric = [c for c in inputs if c != "sector"]
    rows = tag_rows(features, sources, bars.groupby("ticker")["date"].max())
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

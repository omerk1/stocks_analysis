"""The baselines' feature columns (`docs/modeling/VALIDATION_HARNESS.md` §5;
`ma_study_insights.md` §3): the factors the MA study found explaining away
apparent edge, which every model has to beat.

    B2  mom_12_1, realized_vol_63, sector       momentum, volatility, sector
    B3  B2 + mom_1_0                            + short-term reversal
    B4  B3 + dist_pct_sma_50                    + extension (how stretched)

Definitions are the MA study's own (`moving_averages/features/context.py`,
`distance.py`, `ma.py`), called directly so they mean exactly what they meant
there, but on the harness's timing: a row at date t holds values known at the
close of t (the decision; entry is t+1's open). The MA panel instead shifts
every feature one row (row d = close of d-1), so it isn't reused as-is; and it
only covers the 405 tickers that survived to 2021, not the point-in-time
universe.

Each column also gets a per-date percentile rank (`<col>_rank`, over the rows
passed in -- normally the eligible universe), the cross-sectional form the
study's per-date terciles used; levels like mom_12_1 drift with the market,
ranks don't. `sector` is current-state, not point-in-time
(`ma_study_insights.md` §2.4): used as-is, the leak documented.

Bars are on `MODULE_PRICE_BASIS["models_features"]` (total return, as in the
study). Only reads the database; the cache is a parquet file.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS
from src.models.dataset import check_holdout, read_bars_bulk
from src.signals.moving_averages.features import context, distance, ma

FEATURE_BASIS = MODULE_PRICE_BASIS["models_features"]
# mom_12_1 needs 252 bars (~366 calendar days) before its first value.
FEATURE_WARMUP_DAYS = 400

NUMERIC_COLUMNS = ("mom_12_1", "realized_vol_63", "mom_1_0", "dist_pct_sma_50")
CATEGORICAL_COLUMNS = ("sector",)

# Ladder: each rung adds one confound to the one before (ranks, not levels).
BASELINE_COLUMNS = {
    "B2": ["mom_12_1_rank", "realized_vol_63_rank", "sector"],
    "B3": ["mom_12_1_rank", "realized_vol_63_rank", "sector", "mom_1_0_rank"],
    "B4": ["mom_12_1_rank", "realized_vol_63_rank", "sector", "mom_1_0_rank", "dist_pct_sma_50_rank"],
}


def ticker_features(close: pd.Series) -> pd.DataFrame:
    """One ticker's numeric features from its closes (indexed by date), each
    known at that date's close."""
    sma_50 = ma.compute_ma(close, "sma", 50)
    return pd.DataFrame({
        "mom_12_1": context.mom_12_1(close),
        "realized_vol_63": context.realized_vol_63(close),
        "mom_1_0": context.mom_1_0(close),
        "dist_pct_sma_50": distance.dist_pct(close, sma_50),
    }, index=close.index).astype("float32")


def build_features(
    conn: sqlite3.Connection, tickers: list[str],
    start: str | pd.Timestamp, end: str | pd.Timestamp, open_holdout: bool = False,
) -> pd.DataFrame:
    """Numeric features plus `sector` for `tickers` on every bar in [start, end]
    (ticker, date, ...). No ranks: those depend on which rows share a date
    (`add_ranks`)."""
    check_holdout(end, open_holdout)
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    bars = read_bars_bulk(conn, tickers, FEATURE_BASIS, start - pd.Timedelta(days=FEATURE_WARMUP_DAYS), end)
    parts = []
    for ticker, g in bars.groupby("ticker", sort=False):
        f = ticker_features(g.set_index("date")["close"])
        parts.append(f.assign(ticker=ticker).reset_index())
    if not parts:
        return pd.DataFrame(columns=["ticker", "date", *NUMERIC_COLUMNS, *CATEGORICAL_COLUMNS])
    out = pd.concat(parts, ignore_index=True)
    out = out[out["date"].between(start, end)]
    sectors = db.read_ticker_sector(conn)[["ticker", "sector"]]
    sectors["sector"] = sectors["sector"].replace("", pd.NA)
    out = out.merge(sectors, on="ticker", how="left")
    out["sector"] = out["sector"].astype("category")
    return out[["ticker", "date", *NUMERIC_COLUMNS, "sector"]].sort_values(["ticker", "date"], ignore_index=True)


def add_ranks(frame: pd.DataFrame, columns: tuple[str, ...] = NUMERIC_COLUMNS) -> pd.DataFrame:
    """`<col>_rank`: per-date percentile rank in (0, 1] over the rows of
    `frame`; NaN where the value is NaN (never read as lowest)."""
    out = frame.copy()
    for col in columns:
        out[f"{col}_rank"] = out.groupby("date")[col].rank(pct=True).astype("float32")
    return out


def cache_path(out_dir: Path) -> Path:
    return Path(out_dir) / "baseline_features.parquet"


def write_features(features: pd.DataFrame, out_dir: Path, spec: dict) -> Path:
    path = cache_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(path, index=False)
    manifest = {**spec, "feature_basis": FEATURE_BASIS.value, "n_rows": len(features),
                "n_tickers": int(features["ticker"].nunique())}
    path.with_suffix(".json").write_text(json.dumps(manifest, indent=2, default=str))
    return path


def read_features(out_dir: Path, open_holdout: bool = False) -> pd.DataFrame:
    path = cache_path(out_dir)
    manifest = json.loads(path.with_suffix(".json").read_text())
    check_holdout(manifest["end"], open_holdout)
    features = pd.read_parquet(path)
    features.attrs["manifest"] = manifest
    return features

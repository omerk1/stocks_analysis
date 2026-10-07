"""The model-feature cache: every registered model column (`registry.py`) for the
eligible rows of a point-in-time universe, ranked per date over those rows, as
one parquet file with a JSON manifest.

    universe = dataset.universe_mask(conn, start, end)
    build_feature_cache(conn, universe, out_dir)
    features = read_feature_cache(out_dir)

Values are computed per ticker on that ticker's whole bar history (warmup
before `start` included), then restricted to eligible rows and ranked: a rank
is "where this row sits among the names a model could trade that day". The
manifest records each column's registry entry (prior, source, warmup), the
universe spec, price sources and the git SHA.

Only reads the databases; writes only under `out_dir`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common.price_basis import MODULES_WITH_FALLBACK
from src.models import dataset
from src.models.features import baseline, registry

# The longest registered warmup is 451 bars (~655 calendar days).
WARMUP_DAYS = 750
CACHE_NAME = "model_features.parquet"


def _fallback(basis) -> bool:
    module = "models_universe" if basis == dataset.UNIVERSE_BASIS else "models_features"
    return module in MODULES_WITH_FALLBACK


def build_feature_cache(
    conn: sqlite3.Connection, universe: pd.DataFrame, out_dir: Path,
    specs: list[registry.FeatureSpec] | None = None, open_holdout: bool = False,
) -> Path:
    """`universe`: `dataset.universe_mask` output (its `attrs["spec"]` is
    recorded). Writes `<out_dir>/model_features.parquet` + `.json`."""
    specs = specs if specs is not None else registry.model_specs()
    spec = universe.attrs.get("spec", {})
    start, end = universe["date"].min(), universe["date"].max()
    dataset.check_holdout(end, open_holdout)
    rows = universe.loc[universe["eligible"], ["ticker", "date"]]
    tickers = sorted(rows["ticker"].unique())

    bar_specs = [s for s in specs if s.source is not None]
    bases = sorted({registry.SOURCES[s.source].basis for s in bar_specs}, key=lambda b: b.value)
    first = start - pd.Timedelta(days=WARMUP_DAYS)
    bars, sources = {}, {}
    for basis in bases:
        bars[basis] = dataset.read_bars_bulk(conn, tickers, basis, first, end, fallback=_fallback(basis))
        sources[basis.value] = bars[basis].attrs["price_sources"]
    split_sources = dataset.resolve_sources(conn, tickers, dataset.UNIVERSE_BASIS, _fallback(dataset.UNIVERSE_BASIS))
    splits = dataset._read_splits_bulk(conn, split_sources)

    values = registry.compute_registered(bars, splits, tuple(bar_specs), rank=False)
    out = rows.merge(values, on=["ticker", "date"], how="left")
    ranked = tuple(s.name for s in bar_specs if s.ranked)
    if ranked:
        out = baseline.add_ranks(out, ranked)
    if any(s.name == "sector" for s in specs):
        sectors = db.read_ticker_sector(conn)[["ticker", "sector"]]
        sectors["sector"] = sectors["sector"].replace("", pd.NA)
        out = out.merge(sectors, on="ticker", how="left")
        out["sector"] = out["sector"].astype("category")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / CACHE_NAME
    out = out.sort_values(["ticker", "date"], ignore_index=True)
    out.to_parquet(path, index=False)
    manifest = {
        "universe": spec, "start": str(start.date()), "end": str(end.date()), "open_holdout": bool(open_holdout),
        "n_rows": len(out), "n_tickers": int(out["ticker"].nunique()), "price_sources": sources,
        "columns": {s.name: {k: v for k, v in asdict(s).items() if k != "name"} for s in specs},
        "missing_share": {c: float(out[c].isna().mean()) for c in out.columns if c not in ("ticker", "date")},
        # Whole-history disputes take tickers out of the universe (`dataset.resolve_sources`).
        "disputes": dataset.disputes_fingerprint(),
        "git_sha": dataset._git_sha(), "created": pd.Timestamp.now("UTC").isoformat(),
    }
    path.with_suffix(".json").write_text(json.dumps(manifest, indent=2, default=str))
    return path


def read_feature_cache(out_dir: Path, open_holdout: bool = False) -> pd.DataFrame:
    path = Path(out_dir) / CACHE_NAME
    manifest = json.loads(path.with_suffix(".json").read_text())
    if manifest["open_holdout"] and not open_holdout:
        raise dataset.HoldoutError(f"{path} was built with the holdout open; pass open_holdout=True to read it")
    dataset.check_holdout(manifest["end"], open_holdout)
    features = pd.read_parquet(path)
    features.attrs["manifest"] = manifest
    return features

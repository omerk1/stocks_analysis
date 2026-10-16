"""The model-feature cache: every registered model column (`registry.py`) for the
eligible rows of a point-in-time universe, ranked per date over those rows, as
one parquet file with a JSON manifest.

    universe = dataset.universe_mask(conn, start, end)
    build_feature_cache(conn, universe, out_dir)
    features = read_feature_cache(out_dir)

Values are computed per ticker on that ticker's whole bar history (warmup
before `start` included), then restricted to eligible rows and ranked: a rank
is "where this row sits among the names a model could trade that day". Panel
sources (`market.py`) read every member's bars, eligible or not, plus the
benchmark's: breadth and sector peers are the whole point-in-time index of the
universe's indices (recorded as `panel_membership_indices`). The level
columns (a detector source) are computed from every bar the ticker has, as the
snapshot cache (`level_cache.py`, `build-levels`) was built, so they read it
instead of rerunning the detectors; a ticker it doesn't cover is an error. The
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
from src.models.features import baseline, fundamentals, level_features, market, registry

# The longest registered warmup is 451 bars (~655 calendar days).
WARMUP_DAYS = 750
CACHE_NAME = "model_features.parquet"


def _fallback(basis) -> bool:
    module = "models_universe" if basis == dataset.UNIVERSE_BASIS else "models_features"
    return module in MODULES_WITH_FALLBACK


def _level_misses(bars: pd.DataFrame, splits: dict, root: Path) -> list[str]:
    """Tickers whose snapshot files under `root` don't match these bars (any
    source): each would be recomputed, minutes per ticker."""
    from src.models.features import level_cache, levels
    configs = levels.default_configs()
    misses = []
    for ticker, g in bars.groupby("ticker", sort=False):
        clean = levels.prepare(g.drop(columns="ticker").set_index("date").sort_index())
        taken = levels.snapshot_dates(clean.index)
        digest = level_cache.inputs_digest(ticker, clean, splits.get(ticker), taken)
        if any(level_cache.cached_rows(root, s, ticker, level_cache.fingerprint(
                s, ticker, clean, splits.get(ticker), taken, configs[s], digest)) is None
               for s in levels.SNAPSHOT_SOURCES):
            misses.append(ticker)
    return misses


def build_feature_cache(
    conn: sqlite3.Connection, universe: pd.DataFrame, out_dir: Path,
    specs: list[registry.FeatureSpec] | None = None, open_holdout: bool = False,
    levels_root: Path = level_features.DEFAULT_ROOT, workers: int = 1, allow_level_misses: bool = False,
) -> Path:
    """`universe`: `dataset.universe_mask` output (its `attrs["spec"]` is
    recorded). Writes `<out_dir>/model_features.parquet` + `.json`. The level
    columns read the snapshot cache under `levels_root` (`build-levels`, same
    universe and end), from each ticker's whole history; a ticker it doesn't
    cover raises unless `allow_level_misses` (each miss is minutes of detector
    runs). `workers`: processes for the level columns (the cheap per-ticker
    sources run in-process: a pool costs them more than it saves)."""
    specs = specs if specs is not None else registry.model_specs()
    spec = universe.attrs.get("spec", {})
    start, end = universe["date"].min(), universe["date"].max()
    dataset.check_holdout(end, open_holdout)
    rows = universe.loc[universe["eligible"], ["ticker", "date"]]
    tickers = sorted(rows["ticker"].unique())

    bar_specs = [s for s in specs if s.source is not None]
    panel_specs = [s for s in bar_specs if isinstance(registry.SOURCES[s.source], registry.PanelSource)]
    detector_specs = [s for s in bar_specs if registry.is_detector(s)]
    ticker_specs = [s for s in bar_specs if s not in panel_specs and s not in detector_specs]
    first = start - pd.Timedelta(days=WARMUP_DAYS)
    sectors = db.read_ticker_sector(conn)[["ticker", "sector"]]
    sectors["sector"] = sectors["sector"].replace("", pd.NA)
    panel_indices = list(spec.get("indices", ["sp500"]))

    # Panel sources see every name that was a member of the universe's indices
    # at any point in [first, end] -- eligible or not, delisted ones included --
    # plus the benchmark; per-ticker sources only the eligible names. One read
    # covers both.
    names = tickers
    if panel_specs:
        intervals = pd.concat([dataset.apply_renames(conn, db.read_index_membership(conn, n))
                               for n in panel_indices], ignore_index=True)
        overlap = (pd.to_datetime(intervals["start_date"]) <= end) & (
            pd.to_datetime(intervals["end_date"]).fillna(pd.Timestamp.max) >= first)
        names = sorted(set(tickers) | set(intervals.loc[overlap, "ticker"]) | {market.BENCHMARK})
    bars, sources = {}, {}
    for basis in sorted({registry.SOURCES[s.source].basis for s in bar_specs}, key=lambda b: b.value):
        bars[basis] = dataset.read_bars_bulk(conn, names, basis, first, end, fallback=_fallback(basis))
        sources[basis.value] = bars[basis].attrs["price_sources"]
    split_sources = dataset.resolve_sources(conn, tickers, dataset.UNIVERSE_BASIS, _fallback(dataset.UNIVERSE_BASIS))
    splits = dataset._read_splits_bulk(conn, split_sources)

    values = None
    if ticker_specs:
        eligible_bars = {b: f[f["ticker"].isin(tickers)] for b, f in bars.items()}
        values = registry.compute_registered(eligible_bars, splits, tuple(ticker_specs), rank=False)
    level_misses = []
    if detector_specs:
        # The snapshot cache's own read (`level_cache.build_level_cache`): every
        # bar from the first, so the fingerprints match and the cache is read.
        from src.models.features import level_cache
        sources_by_name = {**registry.SOURCES, "levels": registry.level_source(levels_root)}
        dbasis = {sources_by_name[s.source].basis for s in detector_specs}
        # The splits' own vendors (as the snapshot build pairs them), not resolved again.
        dbars = {b: dataset.read_bars_bulk(conn, tickers, b, level_cache.FIRST_BAR, end,
                                           sources=split_sources if b == dataset.UNIVERSE_BASIS else None,
                                           fallback=_fallback(b))
                 for b in dbasis}
        for b in dbasis:
            sources[f"{b.value}_full_history"] = dbars[b].attrs["price_sources"]
        level_misses = _level_misses(dbars[sources_by_name["levels"].basis], splits, levels_root)
        if level_misses and not allow_level_misses:
            raise ValueError(f"the snapshot cache under {levels_root} doesn't cover {len(level_misses)} tickers "
                             f"(e.g. {level_misses[:5]}): run build-levels for this universe and end first")
        dvalues = registry.compute_registered(dbars, splits, tuple(detector_specs), sources_by_name, rank=False,
                                              workers=workers, since=start)
        values = dvalues if values is None else values.merge(dvalues, on=["ticker", "date"], how="outer")
    if panel_specs:
        # Membership from the index intervals, so the trailing breadth windows are warm on `start` too.
        panel_bars = bars[registry.SOURCES[panel_specs[0].source].basis]
        filings = (fundamentals.load_tables(conn, names, end) if any(s.source == "fundamentals" for s in panel_specs)
                   else (None, None))
        context = market.PanelContext(membership=market.members_from_intervals(intervals, panel_bars),
                                      sectors=sectors.set_index("ticker")["sector"],
                                      fundamentals=filings[0], earnings=filings[1])
        pvalues = registry.compute_registered(bars, {}, tuple(panel_specs), rank=False, context=context)
        values = pvalues if values is None else values.merge(pvalues, on=["ticker", "date"], how="left")
    out = rows.merge(values, on=["ticker", "date"], how="left")
    ranked = tuple(s.name for s in bar_specs if s.ranked)
    if ranked:
        out = baseline.add_ranks(out, ranked)
    if any(s.name == "sector" for s in specs):
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
        "panel_membership_indices": panel_indices if panel_specs else None,
        "levels_root": str(levels_root) if detector_specs else None, "level_cache_misses": level_misses,
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

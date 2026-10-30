"""The level-snapshot cache (`docs/modeling/LRP.md` §4): the weekly snapshots of
`level_snapshots.SNAPSHOT_SOURCES`, one parquet per source and ticker, so the slow
detector runs happen once.

    build_level_cache(conn, tickers, root, end, workers=4)
    snaps = cached_snapshots(root, "sr_line", ticker, bars, splits, dates, config)

Each file carries, in its own parquet metadata, a fingerprint of everything its
rows depend on: the source, the detector config, the snapshot dates, the
ticker's bars and splits, its history-reset override (AVWAP/VP anchors depend
on it), and the code (`CODE_FILES`, hashed without comments or docstrings;
`SNAPSHOT_VERSION` for anything else). `cached_snapshots` returns the stored
rows only when the fingerprint matches and recomputes otherwise, so the cache is
a speed copy of `level_snapshots.snapshots` on the same inputs, never a different answer:
a registered level source can call it from the bars it is given, and a
perturbed copy of those bars (the leakage gate) misses the cache and is
computed fresh, and isn't stored. A build is resumable: a ticker whose files
match is skipped. Sources are separate files, so adding one later redoes none
of the others. One build per `root` at a time; the manifest update is locked
anyway.

Gaps and the bar-only sources aren't cached: they cost seconds per ticker.

Only reads the database; writes only under `root`.
"""

from __future__ import annotations

import ast
import dataclasses
import functools
import hashlib
import json
import os
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.foundation.market_common.history_break_overrides import HISTORY_RESET_OVERRIDES
from src.foundation.utils.file_lock import file_lock
from src.models import dataset
from src.models.features import level_snapshots as snap
from src.models.features import levels

# Bump when `level_snapshots.snapshots`' output for the same inputs changes.
SNAPSHOT_VERSION = 1
MANIFEST = "manifest.json"
# The name overlapping builds agree on: changing it lets a build running old code and one
# running new code both merge the manifest at once.
MANIFEST_LOCK = f"{MANIFEST}.lock"
FINGERPRINT_KEY = b"level_snapshot_fingerprint"
FIRST_BAR = "1900-01-01"  # anchors (all-time highs, old gaps) need the whole history


def _canonical(o):
    if isinstance(o, (set, frozenset)):
        return sorted(_canonical(v) for v in o)
    if dataclasses.is_dataclass(o):
        return {f.name: _canonical(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if isinstance(o, dict):
        return {str(k): _canonical(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_canonical(v) for v in o]
    return o if isinstance(o, (int, float, bool, type(None))) else str(o)


def config_key(config) -> str:
    """A config as sorted JSON: stable across processes (a set's repr isn't --
    string hashing is randomised per process)."""
    return json.dumps(_canonical(config), sort_keys=True)


# The code a snapshot depends on: every module `level_snapshots` imports that
# can change a snapshot (tested against what it really imports). Hashed without
# comments, docstrings or formatting, so only a change in what the code does
# invalidates the cache.
_SRC = Path(__file__).resolve().parents[2]
CODE_FILES = tuple(_SRC / f for f in (
    *[f"signals/sr_lines/{m}.py" for m in ("bar_math", "candidates", "config", "data", "engine", "events",
                                           "flip_status", "lifecycle", "models", "pivots", "scoring")],
    *[f"signals/avwap/{m}.py" for m in ("anchors", "compute", "config", "lifecycle", "models")],
    *[f"signals/volume_profile/{m}.py" for m in ("compute", "config", "detect", "models")],
    *[f"foundation/market_common/{m}.py" for m in ("anchors", "data", "history_breaks", "indicators", "models",
                                                    "pivots", "trendline_fit")],
    *[f"foundation/feature_engineering/{m}.py" for m in ("price_based_indicators", "trend_indicators",
                                                          "volume_indicators")],
    "models/features/level_snapshots.py",
))
# Imported but not on a snapshot's path: DB access and vendor choice (the bars
# and splits passed in are fingerprinted instead), and the overrides (each
# ticker's own entry is in its fingerprint).
CODE_EXCLUDED = tuple(_SRC / f for f in (
    "foundation/data_processing/db.py", "foundation/data_processing/resample.py",
    "foundation/market_common/price_basis.py", "foundation/market_common/vendor_overrides.py",
    "foundation/market_common/price_disputes.py", "foundation/market_common/history_break_overrides.py",
))


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return tree


@functools.lru_cache(maxsize=1)
def code_hash() -> str:
    h = hashlib.sha256()
    for f in CODE_FILES:
        h.update(f.name.encode())
        h.update(ast.dump(_strip_docstrings(ast.parse(f.read_text()))).encode())
    return h.hexdigest()


def inputs_digest(ticker: str, bars: pd.DataFrame, splits: pd.DataFrame | None, dates) -> str:
    """The per-ticker half of a fingerprint, shared by its sources. Inputs are
    hashed as the detectors read them (float prices, datetime splits), so an
    equivalent frame of other dtypes hits."""
    h = hashlib.sha256()
    # Membership and value apart: an override of None ("never reset") isn't the
    # automatic rule a ticker with no entry gets.
    h.update(f"{ticker}|{ticker in HISTORY_RESET_OVERRIDES}|{HISTORY_RESET_OVERRIDES.get(ticker)!r}".encode())
    h.update(pd.DatetimeIndex(dates).asi8.tobytes())
    b = bars[["open", "high", "low", "close", "volume"]].astype("float64")
    b.index = pd.DatetimeIndex(b.index)
    h.update(pd.util.hash_pandas_object(b, index=True).to_numpy().tobytes())
    if splits is not None and len(splits):
        sp = pd.DataFrame({"execution_date": pd.to_datetime(splits["execution_date"]),
                           "ratio": splits["ratio"].astype("float64")})
        sp = sp.sort_values("execution_date").reset_index(drop=True)
        h.update(pd.util.hash_pandas_object(sp, index=False).to_numpy().tobytes())
    return h.hexdigest()


def fingerprint(source: str, ticker: str, bars: pd.DataFrame, splits: pd.DataFrame | None, dates, config,
                digest: str | None = None) -> str:
    digest = digest or inputs_digest(ticker, bars, splits, dates)
    return hashlib.sha256(f"{source}|{SNAPSHOT_VERSION}|{code_hash()}|{config_key(config)}|{digest}".encode()) \
        .hexdigest()


def snapshot_path(root: Path, source: str, ticker: str) -> Path:
    # Not Path.with_suffix: "BF.B" would become "BF.parquet", shared with BF.A.
    return Path(root) / source / f"{ticker}.parquet"


def _ns_dates(frame: pd.DataFrame) -> pd.DataFrame:
    """Every datetime column at nanosecond resolution (a time zone, if any, kept).
    pandas 3 infers a column's unit from its data (seconds for these snapshots,
    milliseconds after a parquet round-trip, which can't store seconds), so without
    this a cache hit and a fresh computation of the same snapshots differ in dtype."""
    targets = {}
    for c in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[c]) and frame[c].dt.unit != "ns":
            tz = frame[c].dt.tz
            targets[c] = pd.DatetimeTZDtype("ns", tz) if tz is not None else "datetime64[ns]"
    return frame.astype(targets) if targets else frame


def read_cached(root: Path, source: str, ticker: str, key: str) -> pd.DataFrame | None:
    """The stored rows if the file's own fingerprint is `key`; a missing or
    unreadable file is a miss. The fingerprint is in the parquet's metadata and
    checked on the table actually read, so a concurrent rewrite can't pair one
    input's key with another's rows."""
    try:
        table = pq.read_table(snapshot_path(root, source, ticker))
    except (OSError, ValueError, pa.ArrowException):
        return None
    if (table.schema.metadata or {}).get(FINGERPRINT_KEY, b"").decode() != key:
        return None
    return _ns_dates(table.to_pandas())


def cached_rows(root: Path, source: str, ticker: str, key: str) -> int | None:
    """The stored row count if the fingerprint matches, from the footer alone
    (key and count from one read)."""
    try:
        meta = pq.read_metadata(snapshot_path(root, source, ticker))
    except (OSError, ValueError, pa.ArrowException):
        return None
    return meta.num_rows if (meta.metadata or {}).get(FINGERPRINT_KEY, b"").decode() == key else None


def _write(root: Path, source: str, ticker: str, key: str, snaps: pd.DataFrame) -> None:
    """One file, fingerprint inside, written to a temporary and swapped in: a
    run killed at any point leaves the old file or the new one, never a mix."""
    path = snapshot_path(root, source, ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(snaps, preserve_index=False)
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), FINGERPRINT_KEY: key.encode()})
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    try:
        pq.write_table(table, tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def cached_snapshots(
    root: Path | None, source: str, ticker: str, bars: pd.DataFrame, splits: pd.DataFrame | None, dates, config,
    store: bool = False, key: str | None = None,
) -> pd.DataFrame:
    """`level_snapshots.snapshots(source, ...)`, read from `root` when the stored
    fingerprint matches these inputs, else computed. Stored only with
    `store=True` -- the cache build's own call, made after `cached_rows` found
    a miss, so it always computes -- and a caller computing on other inputs
    (the leakage gate's perturbed bars) can't replace a real entry.
    `bars` already `prepare`d; `key`, if the caller has it, is their fingerprint."""
    key = key or fingerprint(source, ticker, bars, splits, dates, config)
    if root is not None and not store:
        hit = read_cached(root, source, ticker, key)
        if hit is not None:
            return hit
    snaps = _ns_dates(snap.snapshots(source, bars, splits, dates, config, ticker))
    if root is not None and store:
        _write(root, source, ticker, key, snaps)
    return snaps


def _build_one(root: Path, ticker: str, bars: pd.DataFrame, splits: pd.DataFrame | None,
               configs: dict, sources: tuple[str, ...]) -> tuple[str, dict[str, int], float]:
    t0 = time.perf_counter()
    clean = snap.prepare(bars)
    dates = snap.snapshot_dates(clean.index)
    digest = inputs_digest(ticker, clean, splits, dates)
    counts = {}
    for s in sources:
        key = fingerprint(s, ticker, clean, splits, dates, configs[s], digest)
        rows = cached_rows(root, s, ticker, key)
        if rows is None:  # a miss: computed and stored, not re-read
            rows = len(cached_snapshots(root, s, ticker, clean, splits, dates, configs[s], store=True, key=key))
        counts[s] = rows
    return ticker, counts, time.perf_counter() - t0


def build_level_cache(
    conn: sqlite3.Connection, tickers: list[str], root: Path, end: str | pd.Timestamp,
    workers: int = 4, sources: tuple[str, ...] = snap.SNAPSHOT_SOURCES, open_holdout: bool = False,
    progress=print,
) -> dict:
    """Snapshots for every ticker in `tickers` on every week from
    `level_snapshots.SNAPSHOT_START` to `end`, on the traded basis with the vendor
    fallback (delisted members read from Tiingo), from each ticker's whole bar
    history. Writes `<root>/<source>/<ticker>.parquet` and merges this run
    into `<root>/manifest.json` (per-ticker rows and failures accumulate over
    runs, so a rerun of a few tickers keeps the full build's record); returns
    the manifest."""
    dataset.check_holdout(end, open_holdout)
    root = Path(root)
    configs = levels.default_configs()
    basis, fallback = dataset.UNIVERSE_BASIS, dataset.UNIVERSE_FALLBACK
    price_sources = dataset.resolve_sources(conn, tickers, basis, fallback)
    bars = dataset.read_bars_bulk(conn, tickers, basis, FIRST_BAR, end, fallback=fallback, sources=price_sources)
    splits = dataset._read_splits_bulk(conn, price_sources)
    by_ticker = {t: g.drop(columns="ticker").set_index("date").sort_index() for t, g in bars.groupby("ticker")}
    missing = sorted(set(tickers) - set(by_ticker))

    done, failed, seconds = {}, {}, 0.0
    t0 = time.perf_counter()
    pool = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        if pool is None:  # in-process: one worker gains nothing from a pool, and debugs more easily
            def run(t, b):
                try:
                    return _build_one(root, t, b, splits.get(t), configs, sources)
                except Exception as e:  # noqa: BLE001 -- recorded below, as the pool's results are
                    return e
            results = ((t, run(t, b)) for t, b in by_ticker.items())
        else:
            futures = {pool.submit(_build_one, root, t, b, splits.get(t), configs, sources): t
                       for t, b in by_ticker.items()}
            results = ((futures[f], f.exception() or f.result()) for f in as_completed(futures))
        for i, (ticker, result) in enumerate(results, 1):
            if isinstance(result, Exception):  # one bad ticker shouldn't sink a 10-hour build
                failed[ticker] = f"{type(result).__name__}: {result}"
            else:
                _, counts, secs = result
                done[ticker], seconds = counts, seconds + secs
            if progress and (i % 10 == 0 or i == len(by_ticker)):
                elapsed = time.perf_counter() - t0
                progress(f"  {i}/{len(by_ticker)} tickers, {elapsed / 60:.1f} min elapsed, "
                         f"~{elapsed / i * (len(by_ticker) - i) / 60:.0f} min left, {len(failed)} failed")
    finally:
        if pool is not None:
            pool.shutdown()
    with file_lock(root / MANIFEST_LOCK):  # read-merge-write: an overlapping build's records aren't lost
        return _merge_manifest(root, done, failed, missing, price_sources, configs, sources, end, open_holdout,
                               basis, seconds)


def _manifest_epoch(end) -> dict:
    """What every stored file depends on alike: a change in any makes every old
    per-ticker record stale."""
    return {"snapshot_version": SNAPSHOT_VERSION, "code_hash": code_hash(), "end": str(pd.Timestamp(end).date()),
            "overrides": hashlib.sha256(config_key(HISTORY_RESET_OVERRIDES).encode()).hexdigest()}


def _merge_manifest(root, done, failed, missing, price_sources, configs, sources, end, open_holdout, basis,
                    seconds) -> dict:
    path = root / MANIFEST
    epoch = _manifest_epoch(end)
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        old = {}
    if not isinstance(old, dict) or any(old.get(k) != v for k, v in epoch.items()):
        old = {}  # another build's files: their per-ticker record doesn't describe this code or window
    # Per ticker, per source: a run of some sources keeps the others' records,
    # and a source whose config changed keeps none of its old ones.
    new_configs = {s: json.loads(config_key(configs[s])) for s in sources}
    changed = {s for s in sources if old.get("configs", {}).get(s) != new_configs[s]}
    tickers_done = {t: {s: n for s, n in c.items() if s not in changed}
                    for t, c in old.get("tickers", {}).items() if t not in failed}
    tickers_done = {t: c for t, c in tickers_done.items() if c}
    for t, counts in done.items():
        tickers_done.setdefault(t, {}).update(counts)
    failures = {t: e for t, e in {**old.get("failed", {}), **failed}.items() if t not in done}
    all_sources = sorted({s for c in tickers_done.values() for s in c} | set(sources))
    configs_all = {**old.get("configs", {}), **new_configs}
    manifest = {
        **epoch, "sources": all_sources, "configs": configs_all,
        "first_snapshot": str(snap.SNAPSHOT_START.date()),
        "open_holdout": bool(open_holdout), "basis": basis.value,
        "price_sources": {**old.get("price_sources", {}), **price_sources},
        "n_tickers": len(tickers_done), "no_bars": sorted(set(old.get("no_bars", [])) - set(done) | set(missing)),
        "failed": failures,
        "rows": {s: int(sum(c.get(s, 0) for c in tickers_done.values())) for s in all_sources},
        "tickers": tickers_done,
        "last_run": {"n_tickers": len(done), "failed": len(failed), "sources": list(sources),
                     "cpu_hours": seconds / 3600, "git_sha": dataset._git_sha(),
                     "created": pd.Timestamp.now("UTC").isoformat()},
    }
    tmp = path.with_name(f"{MANIFEST}.tmp{os.getpid()}")
    try:
        tmp.write_text(json.dumps(manifest, indent=2, default=str))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return manifest

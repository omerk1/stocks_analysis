"""The level-snapshot cache (`docs/modeling/LRP.md` §4): the weekly snapshots of
`level_snapshots.SNAPSHOT_SOURCES`, one parquet per source and ticker, so the slow
detector runs happen once.

    build_level_cache(conn, tickers, root, end, workers=4)
    snaps = cached_snapshots(root, "sr_line", ticker, bars, splits, dates, config)

Each file carries, in its own parquet metadata, a fingerprint of everything its
rows depend on: the source, the detector config, the snapshot dates, the
ticker's bars and splits, its history-reset override (AVWAP/VP anchors depend
on it), and the source's own code (`CODE_FILES_BY_SOURCE`, hashed without
comments or docstrings; `SNAPSHOT_VERSION` for anything else). A code change
known not to change any snapshot can be re-stamped (`restamp`, `restamp-levels`)
instead of rebuilt. `cached_snapshots` returns the stored
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


# The code a source's snapshots depend on: every module its detector imports, plus
# what `level_snapshots` itself imports (tested against what each really imports).
# Per source, so a change to one detector doesn't invalidate the others' files (a
# volume-profile refactor in done.md #182 made every S/R and AVWAP lookup miss).
# Hashed without comments, docstrings or formatting, so only a change in what the
# code does invalidates the cache.
_SRC = Path(__file__).resolve().parents[2]
_COMMON = (
    *[f"foundation/market_common/{m}.py" for m in ("data", "history_breaks", "indicators", "models")],
    *[f"foundation/feature_engineering/{m}.py" for m in ("price_based_indicators", "trend_indicators",
                                                          "volume_indicators")],
    "models/features/level_snapshots.py",
)
CODE_FILES_BY_SOURCE = {s: tuple(_SRC / f for f in (*own, *_COMMON)) for s, own in {
    "sr_line": (*[f"signals/sr_lines/{m}.py" for m in ("bar_math", "candidates", "config", "data", "engine",
                                                       "events", "flip_status", "lifecycle", "models", "pivots",
                                                       "scoring")],
                "foundation/market_common/pivots.py", "foundation/market_common/trendline_fit.py"),
    "avwap": (*[f"signals/avwap/{m}.py" for m in ("anchors", "compute", "config", "lifecycle", "models")],
              "foundation/market_common/anchors.py", "foundation/market_common/pivots.py"),
    "vp": (*[f"signals/volume_profile/{m}.py" for m in ("compute", "config", "detect", "models")],
           "foundation/market_common/anchors.py", "foundation/market_common/pivots.py"),
}.items()}
CODE_FILES = tuple(sorted({f for files in CODE_FILES_BY_SOURCE.values() for f in files}))
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


@functools.lru_cache(maxsize=None)
def code_hash(source: str) -> str:
    """The hash of `source`'s code (`CODE_FILES_BY_SOURCE`)."""
    h = hashlib.sha256()
    for f in CODE_FILES_BY_SOURCE[source]:
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
                digest: str | None = None, code: str | None = None) -> str:
    """`code`: the code hash to key on, by default `code_hash(source)` (`restamp`
    passes the old one, to recognise a file stored before a code change)."""
    digest = digest or inputs_digest(ticker, bars, splits, dates)
    code = code or code_hash(source)
    return hashlib.sha256(f"{source}|{SNAPSHOT_VERSION}|{code}|{config_key(config)}|{digest}".encode()).hexdigest()


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
    _write_table(snapshot_path(root, source, ticker), key, pa.Table.from_pandas(snaps, preserve_index=False))


def _write_table(path: Path, key: str, table: pa.Table) -> None:
    """`table` with `key` as its fingerprint, swapped in atomically; its schema as given
    (a re-stamp writes the table it read, so only the key changes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
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
    root = Path(root)
    dataset.prepare_build(root, end, open_holdout)
    configs = levels.default_configs()
    basis = dataset.UNIVERSE_BASIS
    price_sources, by_ticker, splits = _load_bars(conn, tickers, end)
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


def _load_bars(conn: sqlite3.Connection, tickers, end) -> tuple[dict, dict[str, pd.DataFrame], dict]:
    """(price sources, each ticker's whole traded history to `end`, splits): what a
    build fingerprints, so a re-stamp reads exactly the same."""
    basis, fallback = dataset.UNIVERSE_BASIS, dataset.UNIVERSE_FALLBACK
    price_sources = dataset.resolve_sources(conn, tickers, basis, fallback)
    bars = dataset.read_bars_bulk(conn, tickers, basis, FIRST_BAR, end, fallback=fallback, sources=price_sources)
    splits = dataset._read_splits_bulk(conn, price_sources)
    by_ticker = {t: g.drop(columns="ticker").set_index("date").sort_index() for t, g in bars.groupby("ticker")}
    return price_sources, by_ticker, splits


def config_record(config) -> object:
    """A config as the manifest records it: what a build stores and both a build and a
    re-stamp compare against."""
    return json.loads(config_key(config))


def _manifest_epoch(end) -> dict:
    """What every stored file depends on alike: a change in any makes every old
    per-ticker record stale. The code is per source (`code_hashes`)."""
    return {"snapshot_version": SNAPSHOT_VERSION, "end": str(pd.Timestamp(end).date()),
            "overrides": hashlib.sha256(config_key(HISTORY_RESET_OVERRIDES).encode()).hexdigest()}


def _write_manifest(path: Path, manifest: dict) -> None:
    tmp = path.with_name(f"{MANIFEST}.tmp{os.getpid()}")
    try:
        tmp.write_text(json.dumps(manifest, indent=2, default=str))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


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
    # and a source whose config or code changed keeps none of its old ones -- this
    # run's or not (its files miss either way, so its records would claim a hit).
    recorded = {s for c in old.get("tickers", {}).values() for s in c} | set(sources)
    today = {s: config_record(configs[s]) for s in recorded if s in configs}
    new_configs = {s: today[s] for s in sources}
    changed = {s for s in recorded if s not in CODE_FILES_BY_SOURCE or s not in today
               or old.get("code_hashes", {}).get(s) != code_hash(s) or old.get("configs", {}).get(s) != today[s]}
    tickers_done = {t: {s: n for s, n in c.items() if s not in changed}
                    for t, c in old.get("tickers", {}).items() if t not in failed}
    tickers_done = {t: c for t, c in tickers_done.items() if c}
    for t, counts in done.items():
        tickers_done.setdefault(t, {}).update(counts)
    failures = {t: e for t, e in {**old.get("failed", {}), **failed}.items() if t not in done}
    all_sources = sorted({s for c in tickers_done.values() for s in c} | set(sources))
    configs_all = {**{s: c for s, c in old.get("configs", {}).items() if s not in changed}, **new_configs}
    code_hashes = {**{s: h for s, h in old.get("code_hashes", {}).items() if s not in changed},
                   **{s: code_hash(s) for s in sources}}
    manifest = {
        **epoch, "code_hashes": code_hashes, "sources": all_sources, "configs": configs_all,
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
        **({"restamped": old["restamped"]} if "restamped" in old else {}),
    }
    _write_manifest(path, manifest)
    return manifest


class RestampRefused(ValueError):
    """The cache at the given root can't be re-stamped: missing, foreign, another epoch,
    a source it wasn't built for or has no files of, one recorded under other code or
    another config, or recorded tickers the DB has no bars for."""


def restamp(conn: sqlite3.Connection, root: Path, from_code: str, sources: tuple[str, ...],
            progress=print) -> dict:
    """Re-key the stored files of `sources` from the code hash `from_code` to today's,
    without touching their rows: for a code change that is known not to change any
    snapshot (check that first, by recomputing a sample and comparing). Only a file
    whose stored key is exactly what `from_code` gave for today's inputs (same bars,
    splits, dates, config, override) is re-keyed; any other file is left as it is, a
    miss that a build recomputes. `from_code`: the manifest's old `code_hash` (one hash
    for every source, before the per-source hash) or a source's old `code_hashes` entry.
    Refused unless the manifest records `from_code` and today's config for every one of
    `sources`, and every ticker with their files recorded still has bars, so what's left
    as a miss is only a file whose bars or splits changed; it loses its record. Don't
    run it alongside a build of the same root (a build writes files outside the
    manifest lock). Returns the manifest, with a `restamped` record of what was done."""
    root = Path(root)
    if not (root / MANIFEST).is_file():
        raise RestampRefused(f"no level cache at {root} (no {MANIFEST})")
    with file_lock(root / MANIFEST_LOCK):
        try:
            manifest = json.loads((root / MANIFEST).read_text())
            end, recorded = str(pd.Timestamp(manifest["end"]).date()), manifest["tickers"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise RestampRefused(f"{root / MANIFEST} isn't a level-cache manifest ({e})")
        dataset.check_holdout(end)  # a cache reaching into the holdout is rebuilt under its own flag, never re-stamped
        if any(manifest.get(k) != v for k, v in _manifest_epoch(end).items()):
            raise RestampRefused("the manifest's version or overrides differ from today's: rebuild, don't re-stamp")
        configs = levels.default_configs()
        sources = tuple(dict.fromkeys(sources))
        built = set(manifest.get("configs", {})) & set(configs) & set(CODE_FILES_BY_SOURCE)
        had = {s for c in recorded.values() for s in c}
        for s in sources:
            if s not in built:
                raise RestampRefused(f"{s} isn't a source this cache was built for (one of {sorted(built)})")
            if s not in had:
                raise RestampRefused(f"no ticker has {s} files recorded: nothing to re-stamp")
            stored_code = manifest.get("code_hashes", {}).get(s, manifest.get("code_hash"))
            if stored_code != from_code:
                raise RestampRefused(f"{s}'s files are recorded under code {stored_code!r}, not {from_code!r}")
            if manifest.get("configs", {}).get(s) != config_record(configs[s]):
                raise RestampRefused(f"{s}'s config changed since the build: rebuild, don't re-stamp")
        _, by_ticker, splits = _load_bars(conn, sorted(recorded), end)
        gone = sorted(t for t in set(recorded) - set(by_ticker) if any(s in recorded[t] for s in sources))
        if gone:
            # Their files can't be fingerprinted against today's inputs, so a re-stamp
            # can't vouch for them -- and a DB missing many tickers mustn't wipe records.
            raise RestampRefused(f"{len(gone)} tickers with recorded files have no bars in this DB "
                                 f"({', '.join(gone[:5])}): check the DB, or rebuild instead of re-stamping")
        counts = {s: {"restamped": 0, "current": 0, "left": 0} for s in sources}
        left: set[tuple[str, str]] = set()
        for i, (ticker, bars) in enumerate(by_ticker.items(), 1):
            clean = snap.prepare(bars)
            dates = snap.snapshot_dates(clean.index)
            digest = inputs_digest(ticker, clean, splits.get(ticker), dates)
            for s in sources:
                if s not in recorded.get(ticker, {}):
                    continue  # never stored for this ticker: nothing to re-key
                old = fingerprint(s, ticker, clean, splits.get(ticker), dates, configs[s], digest, code=from_code)
                new = fingerprint(s, ticker, clean, splits.get(ticker), dates, configs[s], digest)
                path = snapshot_path(root, s, ticker)
                try:  # the footer decides; the table is read only to re-key it
                    stored = (pq.read_metadata(path).metadata or {}).get(FINGERPRINT_KEY, b"").decode()
                    if stored == old and old != new:
                        table = pq.read_table(path)
                        # Checked again on the table actually read: a build may have swapped the file since.
                        if (table.schema.metadata or {}).get(FINGERPRINT_KEY, b"").decode() != old:
                            stored = None
                        else:
                            _write_table(path, new, table)
                except (OSError, ValueError, pa.ArrowException):
                    stored = None
                if stored == new:
                    counts[s]["current"] += 1
                elif stored == old:
                    counts[s]["restamped"] += 1
                else:
                    counts[s]["left"] += 1
                    left.add((ticker, s))
            if progress and (i % 100 == 0 or i == len(by_ticker)):
                progress(f"  {i}/{len(by_ticker)} tickers")
        # A file left as a miss isn't cached: its record goes, so the manifest claims only hits;
        # a re-stamped source that lost all its records isn't listed at all.
        tickers = {t: {s: n for s, n in c.items() if (t, s) not in left} for t, c in recorded.items()}
        manifest["tickers"] = {t: c for t, c in tickers.items() if c}
        manifest["n_tickers"] = len(manifest["tickers"])
        kept = {s for c in manifest["tickers"].values() for s in c}
        emptied = set(sources) - kept
        manifest["sources"] = [s for s in manifest.get("sources", []) if s not in emptied]
        manifest["configs"] = {s: c for s, c in manifest["configs"].items() if s not in emptied}
        manifest["rows"] = {s: int(sum(c.get(s, 0) for c in manifest["tickers"].values()))
                            for s in manifest["sources"]}
        # The single hash before per-source ones stays with each source not re-stamped
        # here, so a later re-stamp of it can still name it.
        legacy = manifest.pop("code_hash", None)
        hashes = manifest.get("code_hashes", {})
        if legacy is not None:
            listed = set(manifest.get("sources", [])) | set(manifest.get("configs", {}))
            hashes = {**{s: legacy for s in listed}, **hashes}
        manifest["code_hashes"] = {s: h for s, h in {**hashes, **{s: code_hash(s) for s in sources}}.items()
                                   if s not in emptied}
        manifest["restamped"] = [*manifest.get("restamped", []), {
            "from": from_code, "sources": list(sources), "counts": counts, "git_sha": dataset._git_sha(),
            "created": pd.Timestamp.now("UTC").isoformat()}]
        _write_manifest(root / MANIFEST, manifest)
    return manifest

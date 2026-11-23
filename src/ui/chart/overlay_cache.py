"""Saved level-detector results, one file per ticker, timeframe and family, so a chart
opened before shows its levels at once, also after a restart.

A family's file holds its overlays and the key they were made under: the family, the
ticker and timeframe, the bars' vendor, a digest of the chart's bars and of that
vendor's splits (everything the detectors read from the database), and a hash of the
code that could change what they find (`code_hash`). A file whose key doesn't match is
a miss; the family runs and its file is overwritten, so there's one file per chart and
family at most. A family that failed isn't saved, so it runs again next time.

The files are pickles the app wrote itself, in the data folder; they aren't meant to be
shared. Any read error is a miss, and any write error is logged and ignored: the cache
never stops a chart from drawing. Delete the folder to clear it.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import pickle
import platform
import re
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.market_common.models import Timeframe

logger = logging.getLogger(__name__)

CACHE_VERSION = 1  # bump when the file's layout changes

_SRC = Path(__file__).resolve().parents[2]  # src/
# The chart's adapters, from which the detectors' code is found (`code_files`).
_CODE_FILES = ("ui/chart/overlays.py", "ui/chart/bars.py")
# Data files that code reads when it's imported: the vendor disputes decide which vendor
# a ticker's bars come from.
_DATA_FILES = ("foundation/market_common/price_disputes.csv",)


def _module_file(module: str) -> Path | None:
    """The file of a `src.` module (its `__init__.py` for a package), None if none."""
    parts = module.split(".")
    if parts[0] != "src":
        return None
    base = _SRC.joinpath(*parts[1:])
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


def _imports(path: Path) -> set[str]:
    """Every `src.` module `path` imports, anywhere in the file (inside functions too),
    with `from pkg import name` also read as the module `pkg.name` (it may be one)."""
    package = ".".join(("src", *path.relative_to(_SRC).parent.parts))
    out = set()
    for node in ast.walk(ast.parse(path.read_bytes())):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: from the file's own package, up level - 1
                anchor = package.split(".")
                anchor = anchor[:len(anchor) - (node.level - 1)]
                base = ".".join(anchor + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            out.add(base)
            out.update(f"{base}.{a.name}" for a in node.names)
    return {m for m in out if m.startswith("src.")}


def code_files() -> list[Path]:
    """The chart's adapters and every `src.` file they import, directly or through
    others (each package's `__init__.py` on the way included)."""
    def with_packages(module: str) -> list[Path]:  # the module and the packages above it
        parts = module.split(".")
        return [p for n in range(2, len(parts) + 1) if (p := _module_file(".".join(parts[:n]))) is not None]

    todo = [p for f in _CODE_FILES for p in with_packages(".".join(("src", *Path(f).with_suffix("").parts)))]
    seen: set[Path] = set()
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        todo.extend(p for module in _imports(path) for p in with_packages(module) if p not in seen)
    return sorted(seen)


@lru_cache(maxsize=1)
def code_hash() -> str:
    """A hash of the detectors' code (`code_files`, plus `_DATA_FILES`) and of the Python, pandas and NumPy
    versions (a pickle may not load across them). Computed once per process, when the
    app starts (`ChartData`): restart the app after editing a detector."""
    h = hashlib.sha256(f"{CACHE_VERSION}|{platform.python_version()}|{pd.__version__}|{np.__version__}".encode())
    for path in code_files() + [_SRC / f for f in _DATA_FILES]:
        h.update(str(path.relative_to(_SRC)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def stored_bars(conn: sqlite3.Connection, ticker: str, source: str) -> str:
    """A summary of the ticker's stored daily rows from `source` (count, first and last
    date, column totals). S/R, gaps and Fibonacci load their bars from the database,
    not from the chart's bars held in memory, so this is what they read; after a refresh
    in a running app, the two differ."""
    row = conn.execute(
        "SELECT COUNT(*), MIN(timestamp), MAX(timestamp), TOTAL(open), TOTAL(high), TOTAL(low), TOTAL(close),"
        " TOTAL(volume), TOTAL(is_partial) FROM bars_1d WHERE ticker = ? AND source = ?", (ticker, source)).fetchone()
    return repr(tuple(row))


def inputs_digest(bars: pd.DataFrame, splits: pd.DataFrame | None, stored: str = "") -> str:
    """A digest of what the detectors read: the chart's bars (index and values), the
    splits of their vendor, and the stored rows' summary (`stored_bars`)."""
    h = hashlib.sha256(pd.util.hash_pandas_object(bars, index=True).to_numpy().tobytes())
    h.update(",".join(map(str, bars.columns)).encode())
    if splits is not None and not splits.empty:
        h.update(pd.util.hash_pandas_object(splits, index=True).to_numpy().tobytes())
    h.update(stored.encode())
    return h.hexdigest()


def family_key(family: str, ticker: str, timeframe: Timeframe, source: str | None, digest: str,
               code: str | None = None) -> str:
    """The key one family's file is saved under (`code`: by default `code_hash()`)."""
    code = code or code_hash()
    return hashlib.sha256(f"{family}|{ticker}|{timeframe.value}|{source}|{digest}|{code}".encode()).hexdigest()


class OverlayCache:
    """The saved files under `root`, one per (ticker, timeframe, family)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, ticker: str, timeframe: Timeframe, family: str) -> Path:
        # the key holds the ticker, so two tickers sharing a file name only replace each other's file
        name = re.sub(r"[^A-Za-z0-9.\-]", "_", ticker)
        return self.root / f"{name}_{timeframe.value}_{family}.pkl"

    def read(self, ticker: str, timeframe: Timeframe, family: str, key: str) -> list | None:
        """The family's saved overlays if they were saved under `key`, else None."""
        path = self.path(ticker, timeframe, family)
        try:
            with path.open("rb") as f:
                stored_key, items = pickle.load(f)
        except FileNotFoundError:
            return None
        except Exception:  # noqa: BLE001 -- a bad or old file is a miss, never an error
            logger.info("unreadable saved overlays %s; running the family", path, exc_info=True)
            return None
        return list(items) if stored_key == key else None

    def write(self, ticker: str, timeframe: Timeframe, family: str, key: str, items: list) -> None:
        """Save the family's overlays under `key`, replacing its file whole (written to a
        temporary file first, so a reader never sees half of one). Errors are logged."""
        path = self.path(ticker, timeframe, family)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tmp.open("wb") as f:
                pickle.dump((key, list(items)), f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except Exception:  # noqa: BLE001 -- the chart draws either way
            logger.warning("couldn't save overlays to %s", path, exc_info=True)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

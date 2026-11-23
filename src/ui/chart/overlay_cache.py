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

import hashlib
import logging
import os
import pickle
import platform
import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.market_common.models import Timeframe

logger = logging.getLogger(__name__)

CACHE_VERSION = 1  # bump when the file's layout changes

_SRC = Path(__file__).resolve().parents[2]  # src/
# Every detector and what it imports lives under these, plus the chart's adapters. Hashing
# all of them, not only the files a family imports, marks more files stale than needed;
# the cost is a recompute, never a wrong level.
_CODE_DIRS = ("signals", "foundation")
_CODE_FILES = ("ui/chart/overlays.py", "ui/chart/bars.py")


@lru_cache(maxsize=1)
def code_hash() -> str:
    """A hash of the detectors' code (`_CODE_DIRS`, `_CODE_FILES`) and of the Python,
    pandas and NumPy versions (a pickle may not load across them). Computed once per
    process: restart the app after editing a detector."""
    files = sorted({p for d in _CODE_DIRS for p in (_SRC / d).rglob("*.py")} | {_SRC / f for f in _CODE_FILES})
    h = hashlib.sha256(f"{CACHE_VERSION}|{platform.python_version()}|{pd.__version__}|{np.__version__}".encode())
    for path in files:
        h.update(str(path.relative_to(_SRC)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def inputs_digest(bars: pd.DataFrame, splits: pd.DataFrame | None) -> str:
    """A digest of what the detectors read: the chart's bars (index and values) and the
    splits of their vendor."""
    h = hashlib.sha256(pd.util.hash_pandas_object(bars, index=True).to_numpy().tobytes())
    h.update(",".join(map(str, bars.columns)).encode())
    if splits is not None and not splits.empty:
        h.update(pd.util.hash_pandas_object(splits, index=True).to_numpy().tobytes())
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

"""The trial log (`docs/modeling/VALIDATION_HARNESS.md` §6, H7): every trial
gets one row in `docs/modeling/TRIALS.csv`, append-only like the MA study's
`EXPERIMENTS.csv` -- including trials that fail or are abandoned, so the
denominator for multiple testing is honest.

    with trial("E1", spec) as t:
        ...                                   # fit, score, bootstrap
        archive_draws(result, t.dir, "brier_vs_b4")
        t.record(metrics={...}, n_dates=..., outcome="...")

The row is written when the block exits: `ok` if `record` was called,
`abandoned` if not, `failed` (with the error) if it raised -- the error is
re-raised after logging. Draws and per-fold tables go to
`data/models/<trial_id>/` (untracked).

`spec` must state every setting the design asks a trial to log (`SPEC_FIELDS`),
`open_holdout` included; a trial missing one is refused before it runs.
"""

from __future__ import annotations

import csv
import json
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

TRIALS_PATH = Path("docs/modeling/TRIALS.csv")
ARTIFACTS_ROOT = Path("data/models")

OK = "ok"
FAILED = "failed"
ABANDONED = "abandoned"

SPEC_FIELDS = (
    "feature_groups",    # groups and their priors (supported / weak / null)
    "universe",          # indices
    "liquidity_floors",
    "cells",             # (H, U, D) cells
    "fold_scheme",
    "seeds",
    "hyperparameters",
    "open_holdout",
)
COLUMNS = ["trial_id", "date", "experiment_id", "status", "git_sha", "git_dirty", *SPEC_FIELDS,
           "metrics", "n_dates", "outcome"]


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _encode(value):
    """Scalars as-is; lists and dicts as JSON, one cell each."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, default=str)


def git_dirty() -> bool | None:
    """Uncommitted changes besides the trial log itself (every trial appends
    to it, so counting it would mark every trial after the first as dirty).
    None when git can't answer -- unknown, not clean."""
    status = _git("status", "--porcelain", "--", ":(top)", f":(top,exclude){TRIALS_PATH.as_posix()}")
    return None if status is None else bool(status)


class Trial:
    def __init__(self, experiment_id: str, spec: dict, artifacts_root: Path):
        missing = [f for f in SPEC_FIELDS if f not in spec]
        if missing:
            raise ValueError(f"trial spec is missing {missing}")
        self.experiment_id = experiment_id
        self.spec = spec
        self.git_sha = _git("rev-parse", "--short", "HEAD")
        self.git_dirty = git_dirty()
        now = pd.Timestamp.now("UTC")
        self.date = now.isoformat()
        self.trial_id = f"{now:%Y%m%d-%H%M%S}-{self.git_sha or 'nogit'}-{uuid.uuid4().hex[:6]}"
        self.dir = Path(artifacts_root) / self.trial_id
        self.status = ABANDONED
        self.metrics: dict = {}
        self.n_dates: int | None = None
        self.outcome = ""

    def record(self, metrics: dict, n_dates: int, outcome: str) -> None:
        """The result: a metric summary (CIs included), its effective N, and a
        one-line outcome."""
        self.status, self.metrics, self.n_dates, self.outcome = OK, metrics, n_dates, outcome

    def row(self) -> dict:
        return {
            "trial_id": self.trial_id, "date": self.date, "experiment_id": self.experiment_id,
            "status": self.status, "git_sha": self.git_sha, "git_dirty": self.git_dirty,
            **{f: _encode(self.spec[f]) for f in SPEC_FIELDS},
            "metrics": _encode(self.metrics), "n_dates": self.n_dates, "outcome": self.outcome,
        }


def append_row(row: dict, trials_path: Path = TRIALS_PATH) -> None:
    trials_path = Path(trials_path)
    new = not trials_path.exists() or trials_path.stat().st_size == 0
    if not new:
        with trials_path.open(newline="") as f:
            header = next(csv.reader(f))
        if header != COLUMNS:
            raise ValueError(f"{trials_path} has columns {header}, expected {COLUMNS}")
    trials_path.parent.mkdir(parents=True, exist_ok=True)
    with trials_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


@contextmanager
def trial(experiment_id: str, spec: dict, trials_path: Path = TRIALS_PATH, artifacts_root: Path = ARTIFACTS_ROOT):
    t = Trial(experiment_id, spec, artifacts_root)
    t.dir.mkdir(parents=True, exist_ok=True)
    try:
        yield t
    except BaseException as exc:
        t.status, t.outcome = FAILED, f"{type(exc).__name__}: {exc}"
        append_row(t.row(), trials_path)
        raise
    append_row(t.row(), trials_path)


def read_trials(trials_path: Path = TRIALS_PATH) -> pd.DataFrame:
    return pd.read_csv(trials_path)

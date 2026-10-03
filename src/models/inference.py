"""Model-vs-baseline inference (`docs/modeling/VALIDATION_HARNESS.md` §6):
a date-block bootstrap on the difference, returning and archiving its draws.

Every comparison is a difference **on the same rows**. The resampling is the
MA study's own (`moving_averages/stats/inference.py`: circular moving blocks
over dates, `MIN_BLOCKS` gate), with block = 2H for horizon H.

Two estimators share one core, a ratio of date-level sums
`sum(w_d * num_d) / sum(w_d * den_d)` with w the draw's date weights:
- `paired_loss_diff`: additive per-row losses (Brier, log loss). num_d is the
  date's summed row-level difference and den_d its row count, so the point
  estimate equals the pooled difference `metrics.cell_metrics` reports.
- `per_date_diff`: statistics that only exist per date (IC, top-k return);
  den_d = 1, so every date weighs the same.

Results carry the raw draws (`draws`), so a later look can compute any
quantile or an empirical p without rerunning, and `near_edge`: the CI edge
closer to "no improvement". Models are ranked by it, not by a p-value.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src.models.metrics import LOSSES, PROB_COLUMNS, block_length
from src.signals.moving_averages.stats.inference import _block_weights, _validate_block_length

N_BOOT = 1000
CI = 0.90


@dataclass
class BootstrapResult:
    point_estimate: float
    ci_low: float
    ci_high: float
    near_edge: float  # higher_is_better: ci_low; otherwise ci_high
    boot_std: float
    higher_is_better: bool
    n_dates: int
    n_rows: int
    n_boot: int
    block_length: int
    ci: float
    seed: int
    draws: np.ndarray = field(repr=False)

    def summary(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "draws"}


def bootstrap_ratio(
    numerators: pd.Series,
    denominators: pd.Series,
    block: int,
    higher_is_better: bool,
    n_rows: int | None = None,
    n_boot: int = N_BOOT,
    ci: float = CI,
    seed: int = 0,
) -> BootstrapResult:
    """Block bootstrap of sum(num)/sum(den) over dates. Both series are indexed
    by date, aligned; dates with a NaN numerator are dropped. Raises
    `InsufficientBlocksError` below `MIN_BLOCKS * block` dates."""
    frame = pd.DataFrame({"num": numerators, "den": denominators}).dropna().sort_index()
    if not frame.index.is_unique:
        raise ValueError("one value per date expected")
    n_dates = len(frame)
    _validate_block_length(n_dates, block)
    num, den = frame["num"].to_numpy(float), frame["den"].to_numpy(float)
    rng = np.random.default_rng(seed)
    weights = np.vstack([_block_weights(frame.index.to_numpy(), block, rng) for _ in range(n_boot)])
    draws = (weights @ num) / (weights @ den)
    tail = (1 - ci) / 2
    lo, hi = float(np.quantile(draws, tail)), float(np.quantile(draws, 1 - tail))
    return BootstrapResult(
        point_estimate=float(num.sum() / den.sum()), ci_low=lo, ci_high=hi,
        near_edge=lo if higher_is_better else hi, boot_std=float(draws.std()),
        higher_is_better=higher_is_better, n_dates=n_dates,
        n_rows=int(n_rows if n_rows is not None else den.sum()),
        n_boot=n_boot, block_length=block, ci=ci, seed=seed, draws=draws,
    )


def _paired(model: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    """The two prediction frames joined on (ticker, date). Refuses anything
    but the same rows with the same realised labels."""
    keys = ["ticker", "date"]
    for name, f in (("model", model), ("baseline", baseline)):
        if f.duplicated(keys).any():
            raise ValueError(f"{name} has duplicate (ticker, date) rows")
    joined = model.merge(baseline, on=keys, how="outer", suffixes=("_m", "_b"), indicator=True)
    if not (joined["_merge"] == "both").all():
        raise ValueError("model and baseline must be scored on the same (ticker, date) rows")
    same_label = (joined["hit_m"] == joined["hit_b"]) | (joined["hit_m"].isna() & joined["hit_b"].isna())
    if not same_label.all():
        raise ValueError("model and baseline rows carry different realised labels")
    return joined.drop(columns="_merge")


def _side(joined: pd.DataFrame, suffix: str) -> pd.DataFrame:
    return pd.DataFrame({c: joined[f"{c}{suffix}"] for c in [*PROB_COLUMNS.values(), "hit"]}, index=joined.index)


def paired_loss_diff(
    model: pd.DataFrame, baseline: pd.DataFrame, horizon: int, loss: str = "brier",
    n_boot: int = N_BOOT, ci: float = CI, seed: int = 0,
) -> BootstrapResult:
    """Pooled (model - baseline) mean per-row loss; negative = model better.
    Rows with an unresolved label (NaN `hit`) are dropped from both."""
    fn = LOSSES[loss]
    joined = _paired(model, baseline).dropna(subset=["hit_m"])
    diff = fn(_side(joined, "_m")) - fn(_side(joined, "_b"))
    by_date = diff.groupby(joined["date"])
    return bootstrap_ratio(by_date.sum(), by_date.size(), block_length(horizon), higher_is_better=False,
                           n_rows=len(joined), n_boot=n_boot, ci=ci, seed=seed)


def per_date_diff(
    model_by_date: pd.Series, baseline_by_date: pd.Series, horizon: int, higher_is_better: bool = True,
    n_boot: int = N_BOOT, ci: float = CI, seed: int = 0,
) -> BootstrapResult:
    """Date-weighted mean of (model - baseline) for a per-date statistic (IC,
    top-k return). Both series must cover the same dates; a date that is NaN
    on either side is dropped from both."""
    if not model_by_date.index.sort_values().equals(baseline_by_date.index.sort_values()):
        raise ValueError("model and baseline must cover the same dates")
    diff = (model_by_date - baseline_by_date.reindex(model_by_date.index)).dropna()
    return bootstrap_ratio(diff, pd.Series(1.0, index=diff.index), block_length(horizon), higher_is_better,
                           n_rows=len(diff), n_boot=n_boot, ci=ci, seed=seed)


def archive_draws(result: BootstrapResult, directory: Path, name: str) -> Path:
    """Write the draws and their settings to `<directory>/<name>.npz` (for
    step 3's `data/models/<trial_id>/`). Read back with `load_draws`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.npz"
    np.savez_compressed(path, draws=result.draws, summary=json.dumps(result.summary()))
    return path


def load_draws(path: Path) -> BootstrapResult:
    with np.load(path) as f:
        return BootstrapResult(**json.loads(str(f["summary"])), draws=f["draws"])

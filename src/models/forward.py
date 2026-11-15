"""Forward scoring: a pre-registered scorecard's model applied to one decision
date, the way its walk-forward test would have scored that date, for paper
trading on dates after the test (docs/modeling/PREREGISTRATION.md HT1,
"Outcomes": a pass or an inconclusive result is paper-traded forward).

For each horizon and barrier cell: the model is fitted as for the date's
test year (`walk_forward_folds((year,), first_train_start)`: trained to the
end of the previous year, purged, isotonic-calibrated on inner folds), once
per seed, the seeds' calibrated probabilities averaged; every eligible row
of the date is scored by EV in ATR units with the training window's
"neither" return, and the top k are the picks, ties broken as the test's
(`metrics.top_k`). On a date inside a test year whose rows are all resolved
this is the test's own pick list for that date (`tests/test_models_forward.py`);
unlike the test it also ranks rows whose outcome isn't known yet, which is
what scoring forward means. The caches are checked as the test checks them.

A scorecard that opens the holdout scores nothing, on any date, until the
registered test has run every one of its cells (`check_can_score`, before
any cache is read): its caches are the holdout's.

The target and stop are the cell's distances in ATRs from the next open;
`target_px` / `stop_px` put them at the decision close, a guide until the
open is known.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.models import dataset, trial_log
from src.models.ablation import P_COLS, cell_frame, check_features
from src.models.labels.barriers import BarrierCell
from src.models.learners import BoostedModel, fit_calibrated
from src.models.metrics import top_k
from src.models.splits import walk_forward_folds
from src.models.trading import Scorecard, cells_to_run, check_label_ends, ev_atr_score, neither_atr_returns, read_labels

PICK_COLUMNS = ["date", "horizon", "upper_atr", "lower_atr", "rank", "ticker", "score", *P_COLS,
                "close_t", "atr", "target_px", "stop_px"]


def score_cell(sc: Scorecard, frame: pd.DataFrame, cell: BarrierCell, as_of: pd.Timestamp,
               k: int | None = None) -> pd.DataFrame:
    """One cell's top `k` (default `sc.verdict_k`) on `as_of`, from `frame`
    (`ablation.cell_frame` of the features and the cell's labels)."""
    if sc.rank != "ev_atr":
        raise ValueError(f"forward scoring ranks by EV in ATR units, the registered tests' rank; got {sc.rank!r}")
    k = sc.verdict_k if k is None else k
    [fold] = walk_forward_folds((as_of.year,), sc.first_train_start)
    rows = frame[frame["date"] == as_of].dropna(subset=["atr", "close_t"])
    if rows.empty:
        raise ValueError(f"no row with a decision-time ATR and close on {as_of.date()}")
    probs = []
    for seed in sc.seeds:
        model, calibrator = fit_calibrated(frame, fold, lambda: BoostedModel(list(sc.model_columns), sc.config, seed))
        raw = model.predict_proba(rows)
        probs.append(calibrator.transform(raw))
    p = sum(probs) / len(probs)                      # the seeds' calibrated probabilities averaged, as seed_mean
    neither_atr = neither_atr_returns(frame, [fold])[as_of.year]
    if not np.isfinite(neither_atr):
        raise ValueError(f"the training window's 'neither' return in ATRs isn't finite ({neither_atr}): no picks")
    g = rows[["ticker", "date", "close_t", "atr"]].join(p[P_COLS])
    g["score"] = ev_atr_score(g, cell, neither_atr)
    top = top_k(g, "score", k).reset_index(drop=True)
    return top.assign(horizon=cell.horizon, upper_atr=cell.upper_atr, lower_atr=cell.lower_atr,
                      rank=range(1, len(top) + 1), target_px=top["close_t"] + cell.upper_atr * top["atr"],
                      stop_px=top["close_t"] - cell.lower_atr * top["atr"])[PICK_COLUMNS]


def score_date(sc: Scorecard, features: pd.DataFrame, labels_dir: Path, as_of: str | pd.Timestamp,
               k: int | None = None, trials_path=trial_log.TRIALS_PATH,
               artifacts_root=trial_log.ARTIFACTS_ROOT) -> pd.DataFrame:
    """Every horizon and cell of `sc`'s top `k` on `as_of`. Reads the label
    caches as the scorecard does (`open_holdout` from `sc`). A date past the
    holdout boundary is scored only after the test has looked at every one
    of its cells (`trading.cells_to_run` has none left): scoring it first
    would read the holdout before the registered test does."""
    as_of = pd.Timestamp(as_of)
    check_can_score(sc, as_of, trials_path, artifacts_root)
    check_features(sc, features)
    check_label_ends(sc, labels_dir)
    parts = []
    for h in sc.horizons:
        for cell in sc.cells(h):
            parts.append(score_cell(sc, cell_frame(features, read_labels(sc, labels_dir, h, cell)), cell, as_of, k))
    return pd.concat(parts, ignore_index=True)


def check_can_score(sc: Scorecard, as_of: pd.Timestamp, trials_path=trial_log.TRIALS_PATH,
                    artifacts_root=trial_log.ARTIFACTS_ROOT) -> None:
    """Before any cache is read: a date past the boundary only for a
    scorecard registered to open the holdout, and such a scorecard (on any
    date: its caches are the holdout's) only once its test has run every
    cell (`trading.cells_to_run` has none left)."""
    dataset.check_holdout(pd.Timestamp(as_of), sc.open_holdout)
    if sc.open_holdout:
        trials = trial_log.read_existing(trials_path)
        left = [c for h in sc.horizons for c in cells_to_run(sc, h, trials, artifacts_root)]
        if left:
            raise dataset.HoldoutError(f"{sc.experiment_id} hasn't run {len(left)} of its cells yet: run the "
                                       "registered test before scoring with its caches")

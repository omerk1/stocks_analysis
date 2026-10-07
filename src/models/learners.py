"""The v1 learner for one barrier cell (`docs/modeling/VALIDATION_HARNESS.md`
§5), calibration, the fold loop and the monotonicity check. The baselines are
in `baselines.py`.

Every model has the same interface: `fit(frame, y, sample_weight=None)` and
`predict_proba(frame)`, which returns P(+1), P(-1), P(0) as columns
`p_up`, `p_down`, `p_neither` aligned to `frame`'s index.

- `BoostedModel` -- the v1 learner (three-class histogram gradient boosting)
  on a given column set.
- `IsotonicCalibrator` -- one-vs-rest isotonic per class, renormalised.
- `fit_predict` -- one outer fold: calibration fitted on the inner folds'
  out-of-sample predictions only, then the model refitted on the full
  (purged) training window and applied to the test rows.
- `monotonicity_violations` -- for fixed H and U, P(stop first) must not fall
  as the stop D moves closer. Counted, never silently fixed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from src.models.features.registry import check_columns
from src.models.metrics import PROB_COLUMNS
from src.models.splits import Fold, fold_masks, inner_folds

CLASSES = (1, -1, 0)
P_COLUMNS = [PROB_COLUMNS[c] for c in CLASSES]


def as_labels(y) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    if np.isnan(y).any():
        raise ValueError("unresolved labels (NaN hit) can't be fitted; drop them first")
    return y.astype(int)


def prob_frame(probs: np.ndarray, index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(probs, index=index, columns=P_COLUMNS)


@dataclass(frozen=True)
class BoostingConfig:
    """v1 defaults, fixed before any fit. `min_samples_leaf` is large because
    labels overlap (H consecutive rows of one ticker share most of a window);
    `max_features` < 1 subsamples columns per split, which is what makes the
    seeds differ (without it the fit is deterministic). sklearn rounds
    `max_features * n_columns` up, so at 0.8 a model with 4 or fewer
    columns (B2, B3) uses them all and its seeds agree exactly -- its seed
    spread is a true 0, not a missing number."""
    learning_rate: float = 0.05
    max_iter: int = 200
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 1000
    l2_regularization: float = 1.0
    max_features: float = 0.8


class BoostedModel:
    """Three-class histogram gradient boosting on `columns`. Pandas categorical
    columns (sector) are used as categorical splits; NaN is native.

    Every column must be registered (`features/registry.py`), so it has passed
    the leakage gate; `registered_only=False` is for synthetic data only (the
    gates' planted features, unit tests)."""

    def __init__(self, columns: list[str], config: BoostingConfig = BoostingConfig(), seed: int = 0,
                 registered_only: bool = True):
        if registered_only:
            check_columns(list(columns))
        self.columns = list(columns)
        self.config = config
        self.seed = seed

    def fit(self, frame: pd.DataFrame, y, sample_weight=None) -> "BoostedModel":
        self.model_ = HistGradientBoostingClassifier(
            **asdict(self.config), early_stopping=False, categorical_features="from_dtype",
            random_state=self.seed,
        )
        self.model_.fit(frame[self.columns], as_labels(y), sample_weight=sample_weight)
        return self

    def predict_proba(self, frame: pd.DataFrame) -> pd.DataFrame:
        raw = self.model_.predict_proba(frame[self.columns])
        probs = np.zeros((len(frame), len(CLASSES)))
        for j, c in enumerate(self.model_.classes_):
            probs[:, CLASSES.index(int(c))] = raw[:, j]
        return prob_frame(probs, frame.index)


class IsotonicCalibrator:
    """One isotonic map per class (P(c) vs 1[y == c]), then each row
    renormalised to sum to 1."""

    def fit(self, probs: pd.DataFrame, y) -> "IsotonicCalibrator":
        y = as_labels(y)
        self.maps_ = {
            c: IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(
                probs[PROB_COLUMNS[c]].to_numpy(float), (y == c).astype(float))
            for c in CLASSES
        }
        return self

    def transform(self, probs: pd.DataFrame) -> pd.DataFrame:
        out = np.column_stack([self.maps_[c].predict(probs[PROB_COLUMNS[c]].to_numpy(float)) for c in CLASSES])
        total = out.sum(axis=1, keepdims=True)
        # A row every map sends to 0 keeps its uncalibrated probabilities.
        out = np.where(total > 0, out / np.where(total > 0, total, 1.0), probs[P_COLUMNS].to_numpy(float))
        return prob_frame(out, probs.index)


def fit_predict(
    frame: pd.DataFrame,
    fold: Fold,
    make_model: Callable[[], object],
    calibrate: bool = True,
    n_inner: int = 2,
    weight_col: str | None = None,
    label_col: str = "hit",
    keep_raw: bool = False,
) -> pd.DataFrame:
    """One outer fold of one cell. `frame` holds the cell's rows (features,
    `label_col`, `date`, `label_end_date`), already restricted to eligible
    rows. Returns the test rows' `ticker`, `date`, `label_col` with the
    predicted probabilities. Unresolved rows (NaN label) are neither fitted
    on nor returned.

    Calibration: the model is fitted on each inner fold's training window and
    predicts that inner fold's test year; the isotonic maps are fitted on
    those out-of-sample predictions. Inner test rows whose label window
    reaches the outer test period are purged too -- otherwise outer-test
    outcomes would shape the calibration.

    `keep_raw` also returns the final model's uncalibrated probabilities as
    `raw_p_up`, `raw_p_down`, `raw_p_neither` (same model, no extra fit).
    """
    train, test = fold_masks(frame, fold)
    resolved = frame[label_col].notna().to_numpy()
    train, test = train & resolved, test & resolved

    def weights(mask):
        return None if weight_col is None else frame.loc[mask, weight_col].to_numpy()

    calibrator = None
    if calibrate:
        ends = pd.to_datetime(frame["label_end_date"]).to_numpy()
        oos = []
        for inner in inner_folds(fold, n_inner=n_inner):
            itrain, itest = fold_masks(frame, inner)
            itrain &= resolved
            itest &= resolved & (ends < np.datetime64(fold.test_start))
            if not itrain.any() or not itest.any():
                continue
            m = make_model().fit(frame.loc[itrain], frame.loc[itrain, label_col], sample_weight=weights(itrain))
            oos.append(m.predict_proba(frame.loc[itest]).assign(**{label_col: frame.loc[itest, label_col]}))
        if not oos:
            raise ValueError(f"no inner-fold predictions to calibrate {fold.name} on")
        inner_preds = pd.concat(oos)
        calibrator = IsotonicCalibrator().fit(inner_preds[P_COLUMNS], inner_preds[label_col])

    model = make_model().fit(frame.loc[train], frame.loc[train, label_col], sample_weight=weights(train))
    raw = model.predict_proba(frame.loc[test])
    probs = calibrator.transform(raw) if calibrator is not None else raw
    out = frame.loc[test, ["ticker", "date", label_col]].join(probs)
    if keep_raw:
        out = out.join(raw.add_prefix("raw_"))
    return out


def monotonicity_violations(preds_by_lower: dict[float, pd.DataFrame], tol: float = 1e-9) -> dict:
    """For one (H, U): `preds_by_lower` maps each stop distance D to that
    cell's predictions (`ticker`, `date`, `p_down`). A closer stop can't be
    less likely to be hit first, so P(-1) must not rise as D grows. Counts
    rows (present in every cell) with at least one violation."""
    ds = sorted(preds_by_lower)
    keyed = [preds_by_lower[d].set_index(["ticker", "date"])["p_down"].rename(d) for d in ds]
    joined = pd.concat(keyed, axis=1, join="inner")
    steps = np.diff(joined[ds].to_numpy(), axis=1)  # p_down(D_next) - p_down(D)
    bad = (steps > tol).any(axis=1)
    return {"lowers": ds, "n_rows": int(len(joined)), "n_violations": int(bad.sum()),
            "share": float(bad.mean()) if len(joined) else float("nan")}

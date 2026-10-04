"""The baselines a model has to beat (`docs/modeling/VALIDATION_HARNESS.md` §5;
`ma_study_insights.md` §3) -- a ladder of cheap models, each knowing one more
thing the MA study found explaining away apparent edge:

    B0  nothing: the training class frequencies, the same for every row
    B2  momentum, volatility, sector
    B3  B2 + short-term reversal (last month's return)
    B4  B3 + extension (distance from the 50-day SMA)

B2-B4 are the v1 learner itself (`learners.BoostedModel`, same settings) on
their fixed columns (`features/baseline.py::BASELINE_COLUMNS`), so a model
beating B4 shows its extra columns carry information, not that its learner
differs. `StratumModel` is B2's matched-stratum form (class frequencies per
momentum tercile x volatility tercile x sector, the study's C2), run once to
check it agrees with the boosted B2.

Not here, decided 2026-10-03: B1 (the date's own outcome rate) -- within-day
skill is measured directly by the IC and the top-k excess over the day's mean
(`metrics.py`); B5 (the Tier-2 slope percentile) -- one fragile cell out of 107
is too weak to be a rung.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.features.baseline import BASELINE_COLUMNS
from src.models.learners import CLASSES, P_COLUMNS, BoostedModel, BoostingConfig, as_labels, prob_frame

STRATUM_B2 = "B2_stratum"


def _class_freqs(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    return np.array([w[y == c].sum() for c in CLASSES]) / w.sum()


class ConstantModel:
    """B0: the training class frequencies (sample-weighted), for every row."""

    def fit(self, frame: pd.DataFrame, y, sample_weight=None) -> "ConstantModel":
        y = as_labels(y)
        w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
        self.freqs_ = _class_freqs(y, w)
        return self

    def predict_proba(self, frame: pd.DataFrame) -> pd.DataFrame:
        return prob_frame(np.tile(self.freqs_, (len(frame), 1)), frame.index)


class StratumModel:
    """B2's matched-stratum form: class frequencies per stratum, where each
    rank column (per-date percentile, in (0, 1]) is cut into `n_buckets`
    and categorical columns are used as-is. Each stratum is shrunk toward
    the overall frequencies with `prior_rows` pseudo-rows, so a thin stratum
    doesn't predict 0 or 1; an unseen stratum (or a NaN key) gets the overall
    frequencies."""

    def __init__(self, rank_columns: list[str], categorical_columns: list[str], n_buckets: int = 3,
                 prior_rows: float = 50.0):
        self.rank_columns = list(rank_columns)
        self.categorical_columns = list(categorical_columns)
        self.n_buckets = n_buckets
        self.prior_rows = prior_rows

    def _keys(self, frame: pd.DataFrame) -> pd.Series:
        parts = [np.ceil(frame[c].astype(float) * self.n_buckets).clip(1, self.n_buckets).astype("Int64").astype(str)
                 for c in self.rank_columns]
        parts += [frame[c].astype(str) for c in self.categorical_columns]
        missing = frame[self.rank_columns + self.categorical_columns].isna().any(axis=1)
        keys = parts[0].str.cat(parts[1:], sep="|") if len(parts) > 1 else parts[0]
        return keys.where(~missing)

    def fit(self, frame: pd.DataFrame, y, sample_weight=None) -> "StratumModel":
        y = as_labels(y)
        w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
        self.overall_ = _class_freqs(y, w)
        keys = self._keys(frame).to_numpy()
        table = pd.DataFrame({"key": keys, "w": w, **{str(c): w * (y == c) for c in CLASSES}}).dropna(subset=["key"])
        sums = table.groupby("key")[["w", *map(str, CLASSES)]].sum()
        counts = sums[[str(c) for c in CLASSES]].to_numpy() + self.prior_rows * self.overall_
        self.table_ = pd.DataFrame(counts / (sums["w"].to_numpy()[:, None] + self.prior_rows),
                                   index=sums.index, columns=P_COLUMNS)
        return self

    def predict_proba(self, frame: pd.DataFrame) -> pd.DataFrame:
        probs = self.table_.reindex(self._keys(frame).to_numpy()).to_numpy(copy=True)
        unseen = np.isnan(probs).any(axis=1)
        probs[unseen] = self.overall_
        return prob_frame(probs, frame.index)




def make_baseline(name: str, config: BoostingConfig = BoostingConfig(), seed: int = 0):
    """A fresh, unfitted baseline by name: B0, B2, B3, B4 or B2_stratum."""
    if name == "B0":
        return ConstantModel()
    if name == STRATUM_B2:
        return StratumModel(["mom_12_1_rank", "realized_vol_63_rank"], ["sector"])
    if name in BASELINE_COLUMNS:
        return BoostedModel(BASELINE_COLUMNS[name], config, seed)
    raise ValueError(f"unknown baseline {name!r}; known: B0, {', '.join(BASELINE_COLUMNS)}, {STRATUM_B2}")

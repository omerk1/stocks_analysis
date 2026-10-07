"""Feature-group ablations against a baseline (`docs/modeling/VALIDATION_HARNESS.md`
§7; `LRP.md` §3): does adding a group of features to the v1 learner lower the
out-of-sample Brier score on the same rows?

Pre-registered experiments are defined here (`PREREGISTERED`) as the executable
copy of their `docs/modeling/PREREGISTRATION.md` entry; the two must agree, and
neither changes once the experiment has run.

An experiment is a ladder of steps (T1 = baseline + group 1, T2 = T1 + group 2,
...) at one barrier cell per horizon. One **trial** is one step at one
horizon, compared with the step before it (the first step with the baseline),
and gets one `TRIALS.csv` row:

- walk-forward yearly test folds, expanding; isotonic calibration on the inner
  folds (`learners.fit_predict`); every model fitted at each seed, the seeds'
  probabilities averaged before scoring (per-seed differences reported);
- primary: the pooled three-class Brier difference (step - reference; negative
  = better) with its date-block bootstrap 90% CI, and a one-sided bootstrap p
  (share of draws showing no improvement) for the experiment's BH correction;
- stability: the difference per test year and per era;
- secondary, never a verdict: uncalibrated Brier, log loss, per-date IC, and
  the top-k picks' excess return and return after costs.

`close_experiment` runs once, after every trial is logged: BH across the
pre-registered trial count (a missing or failed trial counts with p = 1),
then the three-verdict rule (`LRP.md` §3, amended 2026-10-07):

- **pass**: BH-significant, better in at least `min_folds_improving` test
  years, and better in every era;
- otherwise **null** if the CI's improving end stays inside the pre-committed
  relevance band (an improvement as large as the band is ruled out), else
  **inconclusive** (underpowered; never evidence of no effect).

A group passes if any horizon passes, and is null only if every horizon is.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.models import dataset, trial_log
from src.models.inference import N_BOOT, BootstrapResult, archive_draws, paired_loss_diff, per_date_diff
from src.models.labels.barriers import REFERENCE_HORIZON, BarrierCell
from src.models.learners import BoostedModel, BoostingConfig, fit_predict
from src.models.metrics import COSTS_BPS, PROB_COLUMNS, TOP_K, brier_rows, daily_ic, top_k_daily
from src.models.splits import EXPANDING, V1_FIRST_TRAIN_START, V1_TEST_YEARS, Fold, fold_masks, walk_forward_folds
from src.signals.moving_averages.stats.multiple_testing import benjamini_hochberg

PASS = "pass"
NULL = "null"
INCONCLUSIVE = "inconclusive"

P_COLS = list(PROB_COLUMNS.values())
RAW_COLS = [f"raw_{c}" for c in P_COLS]
LABEL_COLS = ["hit", "ret", "atr", "close_t", "label_end_date"]

# Relevance band (see `relevance_band`): the mean standard-normal score of the
# top 5 of ~450 names, and a typical ATR(14) / close for the S&P 500 (median
# daily return sd 1.46% in 2011-2013, ATR ~1.3-1.5x that).
TOP_PICK_Z = 2.6
TYPICAL_ATR_PCT = 0.02


def relevance_band(cell: BarrierCell, cost_bps: float, atr_pct: float = TYPICAL_ATR_PCT,
                   top_z: float = TOP_PICK_Z) -> float:
    """The smallest Brier improvement that matters economically. A calibrated
    signal that moves P(+1) up and P(-1) down by s (sd across names) improves
    the three-class Brier score by 2 s^2, and lifts the EV of the day's top
    picks by about top_z * s * (U + D) * ATR / close. The band is the
    improvement whose pick-EV lift just covers `cost_bps` round trip. It is
    generous to the signal (all of it learned, all of it in the picks), so it
    is small, and calling a demonstrated null is a strict test."""
    s = cost_bps / 1e4 / (top_z * (cell.upper_atr + cell.lower_atr) * atr_pct)
    return 2 * s * s


@dataclass(frozen=True)
class Step:
    name: str
    added: tuple[tuple[str, str], ...]  # (registry group, prior) added at this step
    columns: tuple[str, ...]            # every model input at this step


@dataclass(frozen=True)
class Experiment:
    experiment_id: str
    baseline: str
    baseline_columns: tuple[str, ...]
    steps: tuple[Step, ...]
    horizons: tuple[int, ...]
    upper: float  # in reference-horizon ATRs, scaled by sqrt(H / 21) like the v1 grid
    lower: float
    band_cost_bps: float
    seeds: tuple[int, ...] = (0, 1, 2)
    test_years: tuple[int, ...] = V1_TEST_YEARS
    first_train_start: str = V1_FIRST_TRAIN_START
    eras: tuple[tuple[int, ...], ...] = ((2014, 2015, 2016, 2017), (2018, 2019, 2020, 2021))
    min_folds_improving: int = 5
    ci: float = 0.90
    q: float = 0.10
    indices: tuple[str, ...] = ("sp500",)
    config: BoostingConfig = BoostingConfig()

    @property
    def n_trials(self) -> int:
        return len(self.steps) * len(self.horizons)

    def cell(self, horizon: int) -> BarrierCell:
        return BarrierCell(horizon, self.upper, self.lower, REFERENCE_HORIZON)

    def reference(self, i: int) -> tuple[str, tuple[str, ...]]:
        """The model step `i` is compared with: the step before it, or the baseline."""
        if i == 0:
            return self.baseline, self.baseline_columns
        return self.steps[i - 1].name, self.steps[i - 1].columns


B4_COLUMNS = ("mom_12_1_rank", "realized_vol_63_rank", "sector", "mom_1_0_rank", "dist_pct_sma_50_rank")
MA_SUPPORTED = ("slope_log_21_sma_50_rank", "ribbon_agreement_state")
MA_WEAK = ("dist_z_sma_20", "dist_from_52w_low", "stack_fully_bearish", "log_dollar_volume_20d_rank",
           "macd_hist_pct", "ribbon_width_pctile", "dist_z_sma_200", "slope_log_63_sma_50", "adx_14")

# Column lists are literal, not read from the registry, so a later registry
# change can't silently change a registered experiment.
PREREGISTERED: dict[str, Experiment] = {
    "E1": Experiment(
        "E1", "B4", B4_COLUMNS,
        steps=(Step("T1", (("ma", "supported"),), B4_COLUMNS + MA_SUPPORTED),
               Step("T2", (("ma", "weak"),), B4_COLUMNS + MA_SUPPORTED + MA_WEAK)),
        horizons=(10, 21, 42, 63), upper=2.0, lower=2.0, band_cost_bps=10,
    ),
}


# ---------------------------------------------------------------- fitting

def cell_frame(features: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Feature rows (eligible ticker-days) joined with one cell's labels. A row
    without a label (not a member, or dropped for a disputed day) is out."""
    keys = ["ticker", "date"]
    if labels.duplicated(keys).any():
        raise ValueError("labels hold more than one cell; read one with read_labels(cell=...)")
    return features.merge(labels[keys + LABEL_COLS], on=keys, how="inner")


def oos_predictions(frame: pd.DataFrame, columns: tuple[str, ...], folds: list[Fold], seeds: tuple[int, ...],
                    config: BoostingConfig) -> pd.DataFrame:
    """Every test row's calibrated and raw probabilities, per fold and seed
    (long: one row per ticker, date, seed)."""
    parts = []
    for fold in folds:
        for seed in seeds:
            p = fit_predict(frame, fold, lambda: BoostedModel(list(columns), config, seed), keep_raw=True)
            parts.append(p.assign(fold=fold.test_start.year, seed=seed))
    return pd.concat(parts, ignore_index=True)


def seed_mean(preds: pd.DataFrame) -> pd.DataFrame:
    """The seeds' probabilities averaged per row (each still sums to 1)."""
    return preds.groupby(["ticker", "date"], as_index=False, sort=True).agg(
        hit=("hit", "first"), fold=("fold", "first"), **{c: (c, "mean") for c in P_COLS + RAW_COLS})


def _raw(preds: pd.DataFrame) -> pd.DataFrame:
    return preds.drop(columns=P_COLS).rename(columns=dict(zip(RAW_COLS, P_COLS)))


def neither_returns(frame: pd.DataFrame, folds: list[Fold]) -> dict[int, float]:
    """Per fold: the mean realised return of "neither" rows in its (purged)
    training window, for the EV ranking -- never the scored rows."""
    out = {}
    for fold in folds:
        train, _ = fold_masks(frame, fold)
        out[fold.test_start.year] = float(frame.loc[train & (frame["hit"] == 0).to_numpy(), "ret"].mean())
    return out


# ---------------------------------------------------------------- comparing

def _p_value(result: BootstrapResult) -> float:
    """One-sided bootstrap p for "the step improves on its reference": the
    share of draws with no improvement (>= 0), add-one smoothed."""
    return float((np.sum(result.draws >= 0) + 1) / (len(result.draws) + 1))


def _brier_diff(model: pd.DataFrame, ref: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Per-row Brier (model - reference) on their shared rows, and the rows' dates."""
    j = model[["ticker", "date", "hit", *P_COLS]].merge(ref[["ticker", "date", *P_COLS]], on=["ticker", "date"],
                                                         suffixes=("", "_ref"))
    other = j[["hit"]].assign(**{c: j[f"{c}_ref"] for c in P_COLS})
    return brier_rows(j) - brier_rows(other), j["date"]


def _top_k(preds: pd.DataFrame, frame: pd.DataFrame, cell: BarrierCell, neither: dict[int, float],
           k: int) -> pd.DataFrame:
    scored = preds.merge(frame[["ticker", "date", "ret", "atr", "close_t"]], on=["ticker", "date"])
    return pd.concat([top_k_daily(g, cell, neither[year], k) for year, g in scored.groupby("fold")])


def compare(model: pd.DataFrame, ref: pd.DataFrame, frame: pd.DataFrame, exp: Experiment, horizon: int,
            folds: list[Fold], n_boot: int = N_BOOT, seed: int = 0) -> tuple[dict, dict[str, BootstrapResult]]:
    """The trial's metrics (model vs reference, both per-seed long frames from
    `oos_predictions`) and the bootstrap results whose draws get archived."""
    cell = exp.cell(horizon)
    m, r = seed_mean(model), seed_mean(ref)
    boots = {
        "brier": paired_loss_diff(m, r, horizon, "brier", n_boot, exp.ci, seed),
        "brier_uncalibrated": paired_loss_diff(_raw(m), _raw(r), horizon, "brier", n_boot, exp.ci, seed),
        "log_loss": paired_loss_diff(m, r, horizon, "log_loss", n_boot, exp.ci, seed),
    }
    diff, date = _brier_diff(m, r)
    year = date.dt.year
    by_year = diff.groupby(year).mean()
    by_era = {f"{e[0]}-{e[-1]}": float(diff[year.isin(e)].mean()) for e in exp.eras}
    per_seed = {s: float(_brier_diff(model[model["seed"] == s], ref[ref["seed"] == s])[0].mean()) for s in exp.seeds}

    ic_m, ic_r = daily_ic(m), daily_ic(r)
    boots["ic"] = per_date_diff(ic_m, ic_r, horizon, True, n_boot, exp.ci, seed)
    neither = neither_returns(frame, folds)
    top = {}
    for k in TOP_K:
        tm, tr = _top_k(m, frame, cell, neither, k), _top_k(r, frame, cell, neither, k)
        boots[f"top{k}_excess"] = per_date_diff(tm["excess"], tr["excess"], horizon, True, n_boot, exp.ci, seed)
        top[k] = {"model": {c: float(tm[c].mean()) for c in ["hit_rate", "excess", *[f"ret_net_{c}bps" for c in COSTS_BPS]]},
                  "reference": {c: float(tr[c].mean()) for c in ["hit_rate", "excess", *[f"ret_net_{c}bps" for c in COSTS_BPS]]}}

    band = relevance_band(cell, exp.band_cost_bps)
    brier = boots["brier"]
    metrics = {
        "brier": brier.summary(),
        "brier_p": _p_value(brier),
        "band": band,
        "folds_improving": int((by_year < 0).sum()),
        "n_folds": int(len(by_year)),
        "brier_by_year": {int(y): float(v) for y, v in by_year.items()},
        "brier_by_era": by_era,
        "brier_by_seed": per_seed,
        "brier_model": float(brier_rows(m).mean()),
        "brier_reference": float(brier_rows(r).mean()),
        "secondary": {name: b.summary() for name, b in boots.items() if name != "brier"},
        "top_k": top,
        "neither_ret": neither,
    }
    return metrics, boots


def provisional_outcome(metrics: dict, reference: str, n_trials: int) -> str:
    b = metrics["brier"]
    eras = "/".join(f"{v:+.6f}" for v in metrics["brier_by_era"].values())
    return (f"Brier vs {reference} {b['point_estimate']:+.6f} [{b['ci_low']:+.6f}, {b['ci_high']:+.6f}], "
            f"p {metrics['brier_p']:.3f}; {metrics['folds_improving']}/{metrics['n_folds']} years better; "
            f"eras {eras}; band {metrics['band']:.6f}. Verdict at close (BH over {n_trials}).")


# ---------------------------------------------------------------- running

def trial_spec(exp: Experiment, i: int, horizon: int, features: pd.DataFrame, labels: pd.DataFrame) -> dict:
    step = exp.steps[i]
    ref_name, _ = exp.reference(i)
    fm, lm = features.attrs.get("manifest", {}), labels.attrs.get("manifest", {})
    cell = exp.cell(horizon)
    return {
        "feature_groups": {"step": step.name, "added": [list(a) for a in step.added], "reference": ref_name,
                           "baseline": exp.baseline, "columns": list(step.columns)},
        "universe": {"indices": list(exp.indices), "features_built": fm.get("created"),
                     "labels_built": lm.get("created"), "disputes": lm.get("disputes"),
                     "n_disputed_dropped": lm.get("n_disputed_dropped")},
        "liquidity_floors": fm.get("universe", {}).get("floors"),
        "cells": [{"horizon": horizon, "upper": cell.upper, "lower": cell.lower,
                   "upper_atr": cell.upper_atr, "lower_atr": cell.lower_atr}],
        "fold_scheme": {"scheme": EXPANDING, "test_years": list(exp.test_years),
                        "first_train_start": exp.first_train_start, "calibration": "isotonic, 2 inner folds",
                        "purge": "label window", "embargo_days": 0},
        "seeds": list(exp.seeds),
        "hyperparameters": asdict(exp.config),
        "open_holdout": False,
    }


def run_horizon(exp: Experiment, horizon: int, features: pd.DataFrame, labels_dir: Path, n_boot: int = N_BOOT,
                trials_path: Path = trial_log.TRIALS_PATH, artifacts_root: Path = trial_log.ARTIFACTS_ROOT) -> list[dict]:
    """Every step of `exp` at one horizon, one logged trial each. The
    reference models' predictions are fitted once and reused."""
    labels = dataset.read_labels(labels_dir, horizon, cell=(exp.upper, exp.lower))
    frame = cell_frame(features, labels)
    folds = walk_forward_folds(exp.test_years, exp.first_train_start)
    preds: dict[str, pd.DataFrame] = {}

    def predictions(name, columns):
        if name not in preds:
            preds[name] = oos_predictions(frame, columns, folds, exp.seeds, exp.config)
        return preds[name]

    results = []
    for i, step in enumerate(exp.steps):
        ref_name, ref_columns = exp.reference(i)
        with trial_log.trial(exp.experiment_id, trial_spec(exp, i, horizon, features, labels),
                             trials_path, artifacts_root) as t:
            ref = predictions(ref_name, ref_columns)
            model = predictions(step.name, step.columns)
            metrics, boots = compare(model, ref, frame, exp, horizon, folds, n_boot)
            for name, b in boots.items():
                archive_draws(b, t.dir, name)
            pd.concat([seed_mean(model).assign(model=step.name), seed_mean(ref).assign(model=ref_name)]
                      ).to_parquet(t.dir / "predictions.parquet", index=False)
            t.record(metrics, n_dates=metrics["brier"]["n_dates"],
                     outcome=provisional_outcome(metrics, ref_name, exp.n_trials))
        results.append({"trial_id": t.trial_id, "step": step.name, "horizon": horizon, **metrics})
    return results


# ---------------------------------------------------------------- closing

def _verdict(row: dict, exp: Experiment) -> str:
    if row["bh_significant"] and row["folds_improving"] >= exp.min_folds_improving and row["every_era_better"]:
        return PASS
    return NULL if row["ci_low"] >= -row["band"] else INCONCLUSIVE


def close_experiment(exp: Experiment, trials: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """BH and the three verdicts over `trials` (a `trial_log.read_trials`
    frame). Each (step, horizon) uses its latest `ok` row; one with none
    counts with p = 1 and is inconclusive. Returns the per-trial table and
    each step's group verdict."""
    mine = trials[(trials["experiment_id"] == exp.experiment_id) & (trials["status"] == trial_log.OK)]
    latest = {}
    for _, t in mine.sort_values("date").iterrows():
        step = json.loads(t["feature_groups"])["step"]
        horizon = json.loads(t["cells"])[0]["horizon"]
        latest[(step, horizon)] = (t["trial_id"], json.loads(t["metrics"]))
    rows = []
    for step in exp.steps:
        for h in exp.horizons:
            trial_id, m = latest.get((step.name, h), (None, None))
            if m is None:
                rows.append({"step": step.name, "horizon": h, "trial_id": None, "p": 1.0, "point": np.nan,
                             "ci_low": np.nan, "ci_high": np.nan, "band": np.nan, "folds_improving": 0,
                             "every_era_better": False})
                continue
            rows.append({"step": step.name, "horizon": h, "trial_id": trial_id, "p": m["brier_p"],
                         "point": m["brier"]["point_estimate"], "ci_low": m["brier"]["ci_low"],
                         "ci_high": m["brier"]["ci_high"], "band": m["band"],
                         "folds_improving": m["folds_improving"],
                         "every_era_better": all(v < 0 for v in m["brier_by_era"].values())})
    table = pd.DataFrame(rows)
    table["bh_significant"] = benjamini_hochberg(table["p"].to_numpy(), q=exp.q)
    table["verdict"] = [INCONCLUSIVE if r["trial_id"] is None else _verdict(r, exp) for r in table.to_dict("records")]
    groups = {}
    for step in exp.steps:
        v = table.loc[table["step"] == step.name, "verdict"]
        groups[step.name] = PASS if (v == PASS).any() else NULL if (v == NULL).all() else INCONCLUSIVE
    return table, groups

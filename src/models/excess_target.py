"""A market-relative target for the combined model (Track A, exploration, the
development window only; `docs/modeling/VALIDATION_HARNESS.md` §9, "A
market-relative target").

The frozen model predicts absolute barrier probabilities and ranks by EV in
ATRs, but it is judged on its top 20 minus the market. Here the target is the
judged quantity itself: each row's barrier return (same cell, same exits)
minus that date's equal-weight market basket return, over the same pool the
scorecard's market uses (`trading.pickable`: a resolved label and a
decision-time ATR and close). A regressor (`learners.BoostedRegressor`,
squared loss, the v1 settings) predicts it, and each date's top 20 by the
prediction are the picks.

- **Purging.** A row's target uses every pool row's exit on its date, so its
  label window for purging is the date's latest `label_end_date`, not its own
  (a delisted row ends early, but its target doesn't).
- **Clipping.** The training target is clipped to each date's 1st-99th
  percentile, so a few huge moves don't set the fit; picks are scored on the
  raw returns.
- **No calibration.** A monotone map within a fold doesn't change a date's
  ranking, so there are no inner-fold fits.
- **Seeds** 0, 1, 2, predictions averaged, as the holdout test.

Compared, on the same test dates, with the frozen model's archived dev-window
predictions (`FROZEN_IDS`, its 24 columns at seeds 0, 1, 2, probabilities
averaged as the holdout test did, ranked by EV in ATRs) and their B4
reference. Each fitted cell is a trial under `EXPERIMENT_ID` (the 24 columns
and B4's 5 on the new target); `close` pools them per horizon. No verdict:
the "carry forward" rule (`carry_forward`) was fixed before the run and only
decides whether this is worth a registration.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from src.models import trading, trial_log
from src.models.ablation import B4_COLUMNS, P_COLS, cell_frame, check_features, check_labels
from src.models.inference import archive_draws, per_date_diff
from src.models.labels.barriers import BarrierCell
from src.models.learners import BoostedRegressor, BoostingConfig
from src.models.metrics import top_k
from src.models.splits import fold_masks, walk_forward_folds

EXPERIMENT_ID = "excess_target"
FROZEN_IDS = ("S2_no_market_v", "S2_no_market_v_seed1", "S2_no_market_v_seed2")
MODEL_COLUMNS = trading.COLUMN_SETS["S2_no_market"]
SEEDS = (0, 1, 2)
CLIP = (0.01, 0.99)
K = 20
COST_BPS = 10
COSTS_BPS = (0, 10, 25)
CI = 0.99
BAND = 0.001            # +-10 bps per trade
CELL_N_BOOT = 1_000
POOLED_N_BOOT = 10_000
MIN_YEARS_POSITIVE = 5  # of the 8 dev test years
TRADERS = ("new", "new_b4", "frozen", "b4")
# (a, b): the pooled readouts, a minus b, net of each side's cost
PAIRS = (("new", "market"), ("new", "frozen"), ("new_b4", "b4"), ("frozen", "market"), ("new_b4", "market"))



# ---------------------------------------------------------------- the target

def excess_frame(frame: pd.DataFrame, clip: tuple[float, float] = CLIP) -> pd.DataFrame:
    """`frame` (one cell's `cell_frame`) with `market_ret` (the date's
    equal-weight mean `ret` over the pool), `excess` (ret - market_ret),
    `target` (`excess` clipped to the date's `clip` quantiles) and
    `label_end_date` moved to the date's latest pool end (the row's own is
    kept as `own_label_end`). Rows outside the pool get NaN targets."""
    out = frame.copy()
    pool = out[["ret", "atr", "close_t"]].notna().all(axis=1)
    by_date = out.loc[pool].groupby("date")
    out["market_ret"] = by_date["ret"].transform("mean")
    out["excess"] = out["ret"] - out["market_ret"]
    g = out.loc[pool, "excess"].groupby(out.loc[pool, "date"])
    out["target"] = out["excess"].clip(g.transform("quantile", clip[0]), g.transform("quantile", clip[1]))
    out["own_label_end"] = out["label_end_date"]
    ends = pd.to_datetime(out["label_end_date"])
    pool_end = ends[pool].groupby(out.loc[pool, "date"]).transform("max")
    out["label_end_date"] = pool_end.reindex(out.index).fillna(ends)
    return out


def oos_predictions(frame: pd.DataFrame, columns: tuple[str, ...], folds, seeds: tuple[int, ...] = SEEDS,
                    config: BoostingConfig = BoostingConfig(), registered_only: bool = True) -> pd.DataFrame:
    """Every test row's predicted excess (`pred`), averaged over `seeds`, with
    its `fold`. `frame` is `excess_frame`'s; only rows with a target are fitted
    on or scored."""
    has = frame["target"].notna().to_numpy()
    parts = []
    for fold in folds:
        train, test = fold_masks(frame, fold)
        train, test = train & has, test & has
        for seed in seeds:
            m = BoostedRegressor(list(columns), config, seed, registered_only).fit(
                frame.loc[train], frame.loc[train, "target"])
            parts.append(frame.loc[test, ["ticker", "date"]].assign(
                pred=m.predict(frame.loc[test]), fold=fold.test_start.year, seed=seed))
    p = pd.concat(parts, ignore_index=True)
    return p.groupby(["ticker", "date"], as_index=False, sort=True).agg(fold=("fold", "first"), pred=("pred", "mean"))


# ---------------------------------------------------------------- the sides

def new_picks(preds: pd.DataFrame, frame: pd.DataFrame, k: int = K) -> pd.DataFrame:
    """Each date's `k` pool rows with the highest predicted excess."""
    scored = preds[["ticker", "date", "pred"]].merge(
        frame[["ticker", "date", "hit", "ret", "atr", "close_t"]], on=["ticker", "date"]
    ).dropna(subset=["pred", "ret", "atr", "close_t"])
    scored = scored.assign(atr_pct=scored["atr"] / scored["close_t"])
    return top_k(scored, "pred", k)[["date", "ticker", "hit", "ret", "pred", "atr_pct"]]


def frozen_predictions(trials: pd.DataFrame, cell: BarrierCell, artifacts_root: Path,
                       features: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """The frozen model's and B4's archived predictions for `cell`, the
    probabilities averaged over the `FROZEN_IDS` runs (one seed each) per
    (ticker, date, model). Refuses a cell without exactly one `ok` trial per
    run, a run on another seed than expected, or a cache rebuilt since the
    fits (their rows would no longer be these)."""
    fm, lm = features.attrs.get("manifest", {}), labels.attrs.get("manifest", {})
    parts = []
    for i, eid in enumerate(FROZEN_IDS):
        rows = trials[(trials["experiment_id"] == eid) & (trials["status"] == trial_log.OK)]
        rows = rows[[tuple(json.loads(c)[0][f] for f in ("horizon", "upper", "lower"))
                     == (cell.horizon, cell.upper, cell.lower) for c in rows["cells"]]]
        if len(rows) != 1:
            raise ValueError(f"{eid}: {len(rows)} ok trials for H{cell.horizon} {cell.upper:g}/{cell.lower:g}, need 1")
        row = rows.iloc[0]
        if json.loads(row["seeds"]) != [SEEDS[i]]:
            raise ValueError(f"{eid} was fitted on seeds {row['seeds']}, not [{SEEDS[i]}]")
        u = json.loads(row["universe"])
        if (u.get("features_built"), u.get("labels_built")) != (fm.get("created"), lm.get("created")):
            raise ValueError(f"{row['trial_id']} was fitted on other caches (features {u.get('features_built')}, "
                             f"labels {u.get('labels_built')}) than these ({fm.get('created')}, {lm.get('created')})")
        parts.append(pd.read_parquet(Path(artifacts_root) / row["trial_id"] / "predictions.parquet"))
    p = pd.concat(parts, ignore_index=True)
    counts = p.groupby(["ticker", "date", "model"]).size()
    if (counts != len(FROZEN_IDS)).any():
        raise ValueError(f"the frozen runs' predictions cover different rows ({int((counts != len(FROZEN_IDS)).sum())})")
    return p.groupby(["ticker", "date", "model"], as_index=False, sort=True).agg(
        fold=("fold", "first"), **{c: (c, "mean") for c in P_COLS})


def cell_sides(frame: pd.DataFrame, new: pd.DataFrame, new_b4: pd.DataFrame, frozen: pd.DataFrame,
               cell: BarrierCell, sc: trading.Scorecard, k: int = K) -> tuple[dict[str, pd.DataFrame], dict[str, pd.Series]]:
    """Every side's top-`k` picks for one cell (the market: every pool row)
    and its per-date basket net of its cost (none for the market). `frame` is
    the plain `cell_frame`; `new`, `new_b4` the new target's predictions,
    `frozen` `frozen_predictions`, ranked by EV in ATRs on `sc`'s folds as
    the frozen runs were. Refuses a pool that differs between the new
    and the frozen predictions: the two would be judged on different days."""
    every = trading.pickable(frame, new)
    old_every = trading.pickable(frame, frozen[frozen["model"] == "model"])
    keys = ["ticker", "date"]
    if not every[keys].sort_values(keys).reset_index(drop=True).equals(
            old_every[keys].sort_values(keys).reset_index(drop=True)):
        raise ValueError(f"H{cell.horizon} {cell.upper:g}/{cell.lower:g}: the new and the frozen predictions' "
                         f"pools differ ({len(every)} vs {len(old_every)} rows)")
    old = trading.cell_picks(replace(sc, rank="ev_atr"), cell, frozen, frame, k)
    picked = {"new": new_picks(new, frame, k), "new_b4": new_picks(new_b4, frame, k),
              "frozen": old["model"], "b4": old["reference"],
              "market": every[["date", "ticker", "hit", "ret", "atr_pct"]]}
    return picked, {s: trading.basket(p, 0 if s == "market" else COST_BPS) for s, p in picked.items()}


def beta(side: pd.Series, market: pd.Series) -> float:
    """The slope of a side's per-date basket return on the market's (gross,
    shared dates): how much of the market's daily move the picks carry."""
    both = pd.concat([side, market], axis=1, join="inner").dropna()
    var = both.iloc[:, 1].var()
    return float(both.iloc[:, 0].cov(both.iloc[:, 1]) / var) if var > 0 else np.nan


def overlap(a: pd.DataFrame, b: pd.DataFrame) -> float:
    """The mean daily share of `b`'s names that `a` also picks."""
    keys = ["ticker", "date"]
    both = b[keys].merge(a[keys].assign(_a=True), on=keys, how="left")
    return float(both["_a"].notna().groupby(both["date"]).mean().mean())


def cell_readout(picked: dict[str, pd.DataFrame], baskets: dict[str, pd.Series], horizon: int,
                 n_boot: int = CELL_N_BOOT) -> tuple[dict, dict]:
    """One cell's descriptive readout: each pair's per-date difference (net)
    with its date-block CI, each trading side's trade statistics at
    `COSTS_BPS`, mean ATR / close and beta, and the new picks' overlap with
    the frozen ones. Returns the readout and the bootstraps."""
    n_years = baskets["market"].index.nunique() / trading.TRADING_DAYS
    gross_market = baskets["market"]
    boots, out = {}, {"pairs": {}, "sides": {}}
    for a, b in PAIRS:
        boots[f"{a}_vs_{b}"] = r = per_date_diff(baskets[a], baskets[b].reindex(baskets[a].index), horizon, True,
                                                 n_boot, CI)
        out["pairs"][f"{a}_vs_{b}"] = r.summary()
    for s in (*TRADERS, "market"):
        t = picked[s]
        out["sides"][s] = {"costs": {c: trading.trade_stats(t, c, n_years) for c in COSTS_BPS},
                           "atr_pct": float(t["atr_pct"].mean()),
                           "beta": beta(trading.basket(t), gross_market)}
    out["overlap_new_frozen"] = overlap(picked["new"], picked["frozen"])
    out["overlap_new_b4_b4"] = overlap(picked["new_b4"], picked["b4"])
    return out, boots


# ---------------------------------------------------------------- trials

def scorecard() -> trading.Scorecard:
    """The run's settings as a `trading.Scorecard`: the dev folds, the
    frozen model's columns and B4's, for the trial spec, the checks and the
    frozen picks' folds."""
    return trading.Scorecard(experiment_id=EXPERIMENT_ID, model_columns=MODEL_COLUMNS, reference="B4",
                             reference_columns=B4_COLUMNS, seeds=SEEDS, ks=(K,), ci=CI, band=BAND)


def trial_spec(sc: trading.Scorecard, cell: BarrierCell, features: pd.DataFrame, labels: pd.DataFrame) -> dict:
    spec = trading.trial_spec(sc, cell, features, labels)
    spec["feature_groups"].update({
        "rank": "pred_excess", "target": "ret minus the date's equal-weight pool mean, clipped per date",
        "clip": list(CLIP), "learner": "BoostedRegressor (squared loss)", "compared_with": list(FROZEN_IDS)})
    spec["fold_scheme"].update({"calibration": "none (monotone maps don't change a date's ranking)",
                                "purge": "the date's latest pool label end", "costs_bps": list(COSTS_BPS)})
    return spec


def trial_cells(trials: pd.DataFrame | None, horizon: int) -> dict[tuple[float, float], str]:
    """(upper, lower) -> the first `ok` trial of `EXPERIMENT_ID` at `horizon`."""
    if trials is None:
        return {}
    mine = trials[(trials["experiment_id"] == EXPERIMENT_ID) & (trials["status"] == trial_log.OK)]
    out = {}
    for _, t in mine.sort_values("date").iterrows():
        c = json.loads(t["cells"])[0]
        if c["horizon"] == horizon:
            out.setdefault((c["upper"], c["lower"]), t["trial_id"])
    return out


def run_horizon(horizon: int, features: pd.DataFrame, labels_dir: Path, frozen_root: Path,
                trials_path=trial_log.TRIALS_PATH, artifacts_root=trial_log.ARTIFACTS_ROOT,
                sc: trading.Scorecard | None = None) -> list[dict]:
    """Every cell of one horizon not yet logged `ok`: both new-target models
    fitted, every side scored, one trial per cell, predictions and the
    per-cell bootstraps archived. A cell already logged is skipped (a resumed
    run doesn't refit it). `sc` (default `scorecard()`) is for tests."""
    sc = sc or scorecard()
    check_features(sc, features)
    missing = [c for c in sc.model_columns + sc.reference_columns if c not in features.columns]
    if missing:
        raise ValueError(f"the feature cache lacks {missing}")
    trials = trial_log.read_existing(trials_path)
    trial_log.check_environment(trials, EXPERIMENT_ID)
    done = trial_cells(trials, horizon)
    folds = walk_forward_folds(sc.test_years, sc.first_train_start)
    results = []
    for cell in sc.cells(horizon):
        if (cell.upper, cell.lower) in done:
            continue
        labels = trading.read_labels(sc, labels_dir, horizon, cell)
        frame = cell_frame(features, labels)
        unlabelled = check_labels(sc, features, frame)
        frozen = frozen_predictions(trial_log.read_trials(trials_path), cell, frozen_root, features, labels)
        with trial_log.trial(EXPERIMENT_ID, trial_spec(sc, cell, features, labels), trials_path, artifacts_root) as t:
            ex = excess_frame(frame)
            new = oos_predictions(ex, sc.model_columns, folds, sc.seeds, sc.config)
            new_b4 = oos_predictions(ex, sc.reference_columns, folds, sc.seeds, sc.config)
            picked, baskets = cell_sides(frame, new, new_b4, frozen, cell, sc)
            metrics, boots = cell_readout(picked, baskets, horizon)
            metrics.update(unlabelled_share=unlabelled, n_pool_rows=int(ex["target"].notna().sum()))
            for name, b in boots.items():
                archive_draws(b, t.dir, name)
            pd.concat([new.assign(model="new"), new_b4.assign(model="new_b4")]
                      ).to_parquet(t.dir / "predictions.parquet", index=False)
            t.record(metrics, n_dates=metrics["pairs"]["new_vs_market"]["n_dates"],
                     outcome=outcome(metrics, cell))
        results.append({"trial_id": t.trial_id, "cell": cell, **metrics})
    return results


def outcome(metrics: dict, cell: BarrierCell) -> str:
    p = metrics["pairs"]
    f = lambda r: f"{r['point_estimate']:+.2%} [{r['ci_low']:+.2%}, {r['ci_high']:+.2%}]"  # noqa: E731
    return (f"Track A, no verdict. H{cell.horizon} {cell.upper:g}/{cell.lower:g}, top-{K} by predicted excess, "
            f"net {COST_BPS} bps: new - market {f(p['new_vs_market'])}, new - frozen {f(p['new_vs_frozen'])}, "
            f"new B4 - B4 {f(p['new_b4_vs_b4'])} ({CI:.0%} CI).")


# ---------------------------------------------------------------- pooled

def close(features: pd.DataFrame, labels_dir: Path, frozen_root: Path, horizons: tuple[int, ...] = (21, 63),
          trials_path=trial_log.TRIALS_PATH, artifacts_root=trial_log.ARTIFACTS_ROOT,
          n_boot: int = POOLED_N_BOOT, sc: trading.Scorecard | None = None) -> dict:
    """Per horizon, every pair pooled over the cells (`trading.pooled_readout`:
    a date counts once every cell has it), its CI, by year and cell; the
    sides' mean ATR / close and beta over the cells; and `carry_forward`.
    Read-only. A horizon missing a cell is reported as such, not pooled."""
    sc = sc or scorecard()
    check_features(sc, features)
    trials = trial_log.read_trials(trials_path)
    out = {}
    for h in horizons:
        ids = trial_cells(trials, h)
        cells = sc.cells(h)
        missing = [(c.upper, c.lower) for c in cells if (c.upper, c.lower) not in ids]
        if missing:
            out[h] = {"missing_cells": missing}
            continue
        baskets, readouts = {}, {}
        for c in cells:
            labels = trading.read_labels(sc, labels_dir, h, c)
            frame = cell_frame(features, labels)
            preds = pd.read_parquet(Path(artifacts_root) / ids[(c.upper, c.lower)] / "predictions.parquet")
            frozen = frozen_predictions(trials, c, frozen_root, features, labels)
            picked, baskets[(c.upper, c.lower)] = cell_sides(
                frame, preds[preds["model"] == "new"], preds[preds["model"] == "new_b4"], frozen, c, sc)
            readouts[(c.upper, c.lower)], _ = cell_readout(picked, baskets[(c.upper, c.lower)], h, n_boot=1)
        pairs = {}
        for a, b in PAIRS:
            _, r = trading.pooled_readout(baskets, a, b, h, sc, n_boot)
            r = {k: v for k, v in r.items() if k != "verdict"}   # Track A: no verdict
            r["years_positive"] = trading.years_positive(r)
            pairs[f"{a}_vs_{b}"] = r
        sides = {s: {m: float(np.mean([r["sides"][s][m] for r in readouts.values()])) for m in ("atr_pct", "beta")}
                 for s in (*TRADERS, "market")}
        for s in TRADERS:
            sides[s]["trades_per_year"] = float(np.mean(
                [r["sides"][s]["costs"][COST_BPS]["trades_per_year"] for r in readouts.values()]))
        out[h] = {"pairs": pairs, "sides": sides,
                  "overlap_new_frozen": float(np.mean([r["overlap_new_frozen"] for r in readouts.values()])),
                  "trial_ids": {f"{u:g}/{d:g}": t for (u, d), t in ids.items()}}
    return {"experiment_id": EXPERIMENT_ID, "k": K, "cost_bps": COST_BPS, "ci": CI, "n_boot": n_boot,
            "horizons": out, "carry_forward": carry_forward(out)}


def carry_forward(horizons: dict) -> dict:
    """The rule fixed before the run (Track A: it decides only whether the new
    target is worth a registration). At one horizon or more, new - frozen is
    at least +`BAND` and positive in at least `MIN_YEARS_POSITIVE` test years,
    with the new picks' beta or ATR / close below the frozen picks'; and at no
    horizon does that CI sit wholly below zero."""
    full = {h: r for h, r in horizons.items() if "pairs" in r}
    if len(full) < len(horizons):
        return {"met": False, "why": "a horizon is missing a cell"}
    per = {}
    for h, r in full.items():
        d, s = r["pairs"]["new_vs_frozen"], r["sides"]
        per[h] = {"at_least_band": d["point_estimate"] >= BAND,
                  "years_positive": d["years_positive"] >= MIN_YEARS_POSITIVE,
                  "calmer": s["new"]["beta"] < s["frozen"]["beta"] or s["new"]["atr_pct"] < s["frozen"]["atr_pct"],
                  "ci_wholly_below_zero": d["ci_high"] < 0}
    met = (any(p["at_least_band"] and p["years_positive"] and p["calmer"] for p in per.values())
           and not any(p["ci_wholly_below_zero"] for p in per.values()))
    return {"met": bool(met), "by_horizon": per}

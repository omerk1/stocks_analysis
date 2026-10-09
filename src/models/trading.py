"""Trading scorecard for the combined model (`docs/modeling/VALIDATION_HARNESS.md`
§9, "the combined model"): does a model's top pick each day make a trade worth
taking after costs?

The ablations (`ablation.py`) ask whether a feature group improves the
probabilities. This asks the question the modeling phase exists for: one model
over every registered feature, judged by the trades it would pick.

For each barrier cell, a **model** (every registered column) and a
**reference** (B4's columns) are fitted the way `ablation.py` fits them
(expanding yearly folds, inner-fold isotonic calibration), and each day's
top-k rows by EV (`metrics.expected_value`) are the picks. Three strategies
are scored on the same test dates:

- **model**: the model's top k;
- **reference**: B4's top k (the strongest benchmark that isn't the model);
- **market**: every eligible row's trade, the same barriers (what a pick has to
  beat; a random k has the same expectancy).

Per strategy and round-trip cost: target / stop / timeout rates, win rate,
average win and loss and their ratio (the realised R/R), expectancy per trade,
profit factor, skew, trades per year and the yearly cost drag, the same per
era, and a **portfolio** view: every H trading days, enter that day's picks
equally weighted, so positions never overlap; annual return, max drawdown and
Sharpe, as the median over the H possible start days (one start day is luck).
The portfolio assumes capital is tied up for the full H days even when a
barrier exits early.

The model's per-date basket return minus the reference's, and minus the
market's, get date-block bootstrap CIs. The difference doesn't depend on the
cost (both sides pay it per trade), so it is computed once.

Every cell is a logged trial (`TRIALS.csv`, H7) under `EXPERIMENT_ID`, with no
verdict: step 1 is Track A (exploration), a shakedown of the scorecard on the
features we have before more are added. Its numbers are looks, not findings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src.models import dataset, trial_log
from src.models.ablation import (B4_COLUMNS, MA_SUPPORTED, MA_WEAK, P_COLS, cell_frame, check_features, check_labels,
                                 neither_returns, oos_predictions, seed_mean)
from src.models.inference import N_BOOT, BootstrapResult, archive_draws, per_date_diff
from src.models.labels.barriers import BarrierCell, v1_grid
from src.models.learners import BoostingConfig
from src.models.metrics import TOP_K, expected_value
from src.models.splits import EXPANDING, V1_FIRST_TRAIN_START, V1_TEST_YEARS, walk_forward_folds

EXPERIMENT_ID = "S1"
TRACK = "A"
TRADING_DAYS = 252
COSTS_BPS = (0, 10, 25)   # round trip; 0 = gross
HEADLINE_COST_BPS = 10
STRATEGIES = ("model", "reference", "market")
FULL_COLUMNS = B4_COLUMNS + MA_SUPPORTED + MA_WEAK


@dataclass(frozen=True)
class Scorecard:
    experiment_id: str = EXPERIMENT_ID
    model_columns: tuple[str, ...] = FULL_COLUMNS
    reference: str = "B4"
    reference_columns: tuple[str, ...] = B4_COLUMNS
    horizons: tuple[int, ...] = (21, 63)
    seeds: tuple[int, ...] = (0,)
    test_years: tuple[int, ...] = V1_TEST_YEARS
    first_train_start: str = V1_FIRST_TRAIN_START
    eras: tuple[tuple[int, ...], ...] = ((2014, 2015, 2016, 2017), (2018, 2019, 2020, 2021))
    ks: tuple[int, ...] = TOP_K
    costs_bps: tuple[int, ...] = COSTS_BPS
    ci: float = 0.90
    n_boot: int = N_BOOT
    indices: tuple[str, ...] = ("sp500",)
    config: BoostingConfig = BoostingConfig()
    grid: tuple[tuple[float, float], ...] = ()   # (U, D) cells; empty = every v1 cell

    def cells(self, horizon: int) -> list[BarrierCell]:
        return [c for c in v1_grid() if c.horizon == horizon and (not self.grid or (c.upper, c.lower) in self.grid)]


# ---------------------------------------------------------------- the trades

def picks(preds: pd.DataFrame, frame: pd.DataFrame, cell: BarrierCell, neither: dict[int, float],
          k: int) -> pd.DataFrame:
    """Each test date's `k` rows with the highest EV (ties broken by ticker),
    with their realised `hit` and `ret`. `preds` is one row per (ticker,
    date) with `fold` and the probabilities; EV uses the fold's training-window
    `neither` return."""
    keys = ["ticker", "date"]
    scored = preds[[*keys, "fold", *P_COLS]].merge(frame[[*keys, "hit", "ret", "atr", "close_t"]], on=keys)
    parts = []
    for year, g in scored.groupby("fold"):
        g = g.assign(ev=expected_value(g, cell, neither[year])).dropna(subset=["ev", "ret"])
        parts.append(g.sort_values(["date", "ev", "ticker"], ascending=[True, False, True]).groupby("date").head(k))
    return pd.concat(parts, ignore_index=True)[["date", "ticker", "hit", "ret", "ev"]]


def basket(trades: pd.DataFrame, cost_bps: float = 0) -> pd.Series:
    """Per date: the equal-weighted return of that date's trades, net of cost."""
    return trades.groupby("date")["ret"].mean() - cost_bps / 1e4


def trade_stats(trades: pd.DataFrame, cost_bps: float, n_years: float) -> dict:
    """The trade-level readout of one strategy at one round-trip cost. A trade
    "wins" if it is positive after cost. `n_years` is the test span, for
    trades per year and the yearly cost drag (CLAUDE.md invariant 8)."""
    net = trades["ret"] - cost_bps / 1e4
    wins, losses = net[net > 0], net[net <= 0]
    per_year = len(trades) / n_years
    return {
        "n_trades": int(len(trades)),
        "n_dates": int(trades["date"].nunique()),
        "trades_per_year": float(per_year),
        "cost_per_year": float(per_year * cost_bps / 1e4),
        "target_rate": float((trades["hit"] == 1).mean()),
        "stop_rate": float((trades["hit"] == -1).mean()),
        "timeout_rate": float((trades["hit"] == 0).mean()),
        "win_rate": float((net > 0).mean()),
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(losses.mean()) if len(losses) else np.nan,
        "payoff_ratio": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else np.nan,
        "expectancy": float(net.mean()),
        "median": float(net.median()),
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else np.nan,
        "skew": float(net.skew()),
    }


def portfolio(daily: pd.Series, horizon: int) -> dict:
    """Non-overlapping holding: every `horizon`-th date's basket, compounded.
    One series per start day (0 .. horizon - 1); the median of each statistic
    across them, plus the annual return's range."""
    daily = daily.sort_index()
    runs = []
    for start in range(min(horizon, len(daily))):
        r = daily.iloc[start::horizon]
        if len(r) < 2:
            continue
        equity = np.concatenate([[1.0], np.cumprod(1 + r.to_numpy())])
        years = len(r) * horizon / TRADING_DAYS
        runs.append({
            "annual_return": float(equity[-1] ** (1 / years) - 1) if equity[-1] > 0 else -1.0,
            "max_drawdown": float((equity / np.maximum.accumulate(equity) - 1).min()),
            "sharpe": float(r.mean() / r.std() * np.sqrt(TRADING_DAYS / horizon)) if r.std() > 0 else np.nan,
        })
    runs = pd.DataFrame(runs)
    return {**{c: float(runs[c].median()) for c in runs.columns},
            "annual_return_min": float(runs["annual_return"].min()),
            "annual_return_max": float(runs["annual_return"].max()),
            "n_start_days": int(len(runs))}


# ---------------------------------------------------------------- one cell

def score_cell(model: pd.DataFrame, ref: pd.DataFrame, frame: pd.DataFrame, cell: BarrierCell, sc: Scorecard,
               n_boot: int, seed: int = 0) -> tuple[dict, dict[str, BootstrapResult]]:
    """The scorecard of one cell from the two models' seed-averaged
    predictions (one row per scored (ticker, date), with `fold`)."""
    folds = walk_forward_folds(sc.test_years, sc.first_train_start)
    neither = neither_returns(frame, folds)
    keys = ["ticker", "date"]
    every = frame.merge(model[keys], on=keys).dropna(subset=["ret"])
    n_years = every["date"].nunique() / TRADING_DAYS
    metrics = {"neither_ret": neither, "n_years": n_years, "by_k": {}}
    boots = {}
    for k in sc.ks:
        trades = {"model": picks(model, frame, cell, neither, k), "reference": picks(ref, frame, cell, neither, k),
                  "market": every[["date", "ticker", "hit", "ret"]]}
        gross = {s: basket(t) for s, t in trades.items()}
        for other in ("reference", "market"):
            boots[f"top{k}_vs_{other}"] = per_date_diff(gross["model"], gross[other], cell.horizon, True,
                                                        n_boot, sc.ci, seed)
        out = {"vs_reference": boots[f"top{k}_vs_reference"].summary(),
               "vs_market": boots[f"top{k}_vs_market"].summary()}
        for s, t in trades.items():
            t_year = t["date"].dt.year
            out[s] = {
                "costs": {c: trade_stats(t, c, n_years) for c in sc.costs_bps},
                "by_era": {f"{e[0]}-{e[-1]}": float(t.loc[t_year.isin(e), "ret"].mean() - HEADLINE_COST_BPS / 1e4)
                           for e in sc.eras},
                "portfolio": portfolio(basket(t, HEADLINE_COST_BPS), cell.horizon),
            }
        metrics["by_k"][k] = out
    return metrics, boots


def outcome(metrics: dict, cell: BarrierCell, k: int = TOP_K[0]) -> str:
    m = metrics["by_k"][k]
    e = {s: m[s]["costs"][HEADLINE_COST_BPS]["expectancy"] for s in STRATEGIES}
    pay = m["model"]["costs"][HEADLINE_COST_BPS]["payoff_ratio"]
    d = m["vs_reference"]
    return (f"Track A, no verdict. H{cell.horizon} {cell.upper:g}/{cell.lower:g}, top-{k} net "
            f"{HEADLINE_COST_BPS} bps per trade: model {e['model']:+.2%} (R/R {pay:.2f}), reference "
            f"{e['reference']:+.2%}, market {e['market']:+.2%}; model - reference {d['point_estimate']:+.2%} "
            f"[{d['ci_low']:+.2%}, {d['ci_high']:+.2%}].")


def trial_spec(sc: Scorecard, cell: BarrierCell, features: pd.DataFrame, labels: pd.DataFrame) -> dict:
    fm, lm = features.attrs.get("manifest", {}), labels.attrs.get("manifest", {})
    return {
        "feature_groups": {"track": TRACK, "model": list(sc.model_columns), "reference": sc.reference,
                           "reference_columns": list(sc.reference_columns)},
        "cells": [{"horizon": cell.horizon, "upper": cell.upper, "lower": cell.lower,
                   "upper_atr": cell.upper_atr, "lower_atr": cell.lower_atr}],
        "fold_scheme": {"scheme": EXPANDING, "test_years": list(sc.test_years),
                        "first_train_start": sc.first_train_start, "eras": [list(e) for e in sc.eras],
                        "calibration": "isotonic, 2 inner folds", "purge": "label window", "embargo_days": 0,
                        "ks": list(sc.ks), "costs_bps": list(sc.costs_bps)},
        "seeds": list(sc.seeds),
        "hyperparameters": asdict(sc.config),
        "universe": {"indices": list(sc.indices), "features_built": fm.get("created"),
                     "labels_built": lm.get("created"), "disputes": lm.get("disputes"),
                     "n_disputed_dropped": lm.get("n_disputed_dropped")},
        "liquidity_floors": fm.get("universe", {}).get("floors"),
        "open_holdout": False,
    }


def run_horizon(sc: Scorecard, horizon: int, features: pd.DataFrame, labels_dir, n_boot: int | None = None,
                trials_path=trial_log.TRIALS_PATH, artifacts_root=trial_log.ARTIFACTS_ROOT) -> list[dict]:
    """Every cell of one horizon: both models fitted, scored, logged as one
    trial per cell, predictions and bootstrap draws archived."""
    n_boot = sc.n_boot if n_boot is None else n_boot
    check_features(sc, features)
    folds = walk_forward_folds(sc.test_years, sc.first_train_start)
    results = []
    for cell in sc.cells(horizon):
        labels = dataset.read_labels(labels_dir, horizon, cell=(cell.upper, cell.lower))
        frame = cell_frame(features, labels)
        unlabelled = check_labels(sc, features, frame)
        with trial_log.trial(sc.experiment_id, trial_spec(sc, cell, features, labels),
                             trials_path, artifacts_root) as t:
            model = seed_mean(oos_predictions(frame, sc.model_columns, folds, sc.seeds, sc.config))
            ref = seed_mean(oos_predictions(frame, sc.reference_columns, folds, sc.seeds, sc.config))
            metrics, boots = score_cell(model, ref, frame, cell, sc, n_boot)
            metrics["unlabelled_share"] = unlabelled
            for name, b in boots.items():
                archive_draws(b, t.dir, name)
            pd.concat([model.assign(model="model"), ref.assign(model=sc.reference)]
                      ).to_parquet(t.dir / "predictions.parquet", index=False)
            t.record(metrics, n_dates=metrics["by_k"][sc.ks[0]]["vs_reference"]["n_dates"],
                     outcome=outcome(metrics, cell, sc.ks[0]))
        results.append({"trial_id": t.trial_id, "cell": cell, **metrics})
    return results


# ---------------------------------------------------------------- the grid

def grid_table(results: list[dict], k: int, cost_bps: int = HEADLINE_COST_BPS) -> pd.DataFrame:
    """One row per cell: each strategy's expectancy and R/R at `cost_bps`,
    the model's portfolio, and the model - reference / - market differences."""
    rows = []
    for r in results:
        m, c = r["by_k"][k], r["cell"]
        row = {"H": c.horizon, "U": c.upper, "D": c.lower}
        for s in STRATEGIES:
            st = m[s]["costs"][cost_bps]
            row[f"{s}_exp"] = st["expectancy"]
            row[f"{s}_rr"] = st["payoff_ratio"]
            row[f"{s}_win"] = st["win_rate"]
        row["model_annual"] = m["model"]["portfolio"]["annual_return"]
        row["model_mdd"] = m["model"]["portfolio"]["max_drawdown"]
        row["model_sharpe"] = m["model"]["portfolio"]["sharpe"]
        for other in ("reference", "market"):
            d = m[f"vs_{other}"]
            row[f"vs_{other}"], row[f"vs_{other}_lo"], row[f"vs_{other}_hi"] = (
                d["point_estimate"], d["ci_low"], d["ci_high"])
        rows.append(row)
    return pd.DataFrame(rows)

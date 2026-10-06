"""Out-of-sample metrics for one barrier cell (`docs/modeling/VALIDATION_HARNESS.md` §6, H6).

Input is a predictions frame, one row per (ticker, date) test row of one cell:

    date, ticker              keys
    p_up, p_down, p_neither   the model's P(+1), P(-1), P(0); rows sum to 1
    hit                       realised label: +1 target first, -1 stop first, 0 neither
    ret                       realised trade return (labels/barriers.py), before cost
    atr, close_t              ATR and close as known at the decision close (same basis)
    tie                       optional: the label's same-bar tie flag
    capped                    optional: row is in a survivorship-capped bucket

Metrics:
- **Three-class Brier and log loss** (the model is three-class).
- **Reliability**, one-vs-rest for P(+1) and P(-1), 10 equal-width bins, each
  with its own n_rows and n_dates.
- **Per-date Spearman IC** of P(+1) against the realised `hit` (ordinal -1/0/+1).
- **Top-k per day by EV**, realised hit rate and realised return after 10 and
  25 bps round trip, plus its excess over that day's mean return (within-day
  skill; the IC is the other within-day measure). EV ranks on decision-time
  quantities only: ATR over the decision close, never the entry price (the
  next open isn't known when the ranking is made), and `neither_ret`, the
  mean return of "neither" rows, which the caller estimates on training rows
  -- never on the rows scored here.

Every row carries `n_rows` and `n_dates`. A group with fewer than
`MIN_BLOCKS x 2H` dates is `not_computable`: counts kept, metrics NaN, never
silently pooled.

Per-row losses and per-date series are exposed separately so `inference.py`
can bootstrap model-vs-baseline differences from them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.labels.barriers import BarrierCell
from src.signals.moving_averages.stats.inference import MIN_BLOCKS

PROB_COLUMNS = {1: "p_up", -1: "p_down", 0: "p_neither"}
TOP_K = (5, 20)
COSTS_BPS = (10, 25)
RELIABILITY_BINS = 10
MIN_NAMES_FOR_IC = 20
LOG_LOSS_EPS = 1e-15

OK = "ok"
NOT_COMPUTABLE = "not_computable"


def block_length(horizon: int) -> int:
    """Date-block length for a horizon's bootstrap and computability gate: 2H."""
    return 2 * horizon


def min_dates(horizon: int) -> int:
    return MIN_BLOCKS * block_length(horizon)


def _probs(frame: pd.DataFrame) -> np.ndarray:
    return frame[[PROB_COLUMNS[c] for c in (1, -1, 0)]].to_numpy(dtype=float)


def _onehot(frame: pd.DataFrame) -> np.ndarray:
    hit = frame["hit"].to_numpy(dtype=float)
    return np.column_stack([hit == 1, hit == -1, hit == 0]).astype(float)


def brier_rows(frame: pd.DataFrame) -> pd.Series:
    """Three-class Brier score per row: sum over classes of (p - outcome)^2, in [0, 2]."""
    return pd.Series(((_probs(frame) - _onehot(frame)) ** 2).sum(axis=1), index=frame.index)


def log_loss_rows(frame: pd.DataFrame) -> pd.Series:
    """Per-row negative log probability of the realised class (clipped at LOG_LOSS_EPS)."""
    p = (np.clip(_probs(frame), LOG_LOSS_EPS, 1.0) * _onehot(frame)).sum(axis=1)
    return pd.Series(-np.log(p), index=frame.index)


LOSSES = {"brier": brier_rows, "log_loss": log_loss_rows}


def reliability(frame: pd.DataFrame, cls: int = 1, bins: int = RELIABILITY_BINS) -> pd.DataFrame:
    """One-vs-rest reliability for P(cls): equal-width bins on [0, 1], with the
    mean prediction, the observed frequency, n_rows and n_dates per bin. Empty
    bins are kept (NaN means, zero counts) so tables align across folds.
    Rows with an unresolved label or a missing probability are dropped, as in
    `cell_metrics` -- a NaN label is not a miss."""
    frame = frame.dropna(subset=["hit", PROB_COLUMNS[cls]])
    p = frame[PROB_COLUMNS[cls]].to_numpy(dtype=float)
    observed = (frame["hit"].to_numpy(dtype=float) == cls).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, bins - 1)
    tmp = pd.DataFrame({"bin": idx, "p": p, "obs": observed, "date": frame["date"].to_numpy()})
    g = tmp.groupby("bin")
    out = pd.DataFrame({
        "mean_pred": g["p"].mean(), "observed": g["obs"].mean(),
        "n_rows": g.size(), "n_dates": g["date"].nunique(),
    }).reindex(range(bins))
    out[["n_rows", "n_dates"]] = out[["n_rows", "n_dates"]].fillna(0).astype(int)
    out.insert(0, "bin_low", edges[:-1])
    out.insert(1, "bin_high", edges[1:])
    out.insert(0, "cls", cls)
    return out.reset_index(drop=True)


def daily_ic(frame: pd.DataFrame, prob_col: str = "p_up", outcome_col: str = "hit",
             min_names: int = MIN_NAMES_FOR_IC) -> pd.Series:
    """Per-date Spearman rank correlation of `prob_col` with `outcome_col`,
    indexed by date. NaN on dates with fewer than `min_names` rows or no
    variation on either side."""
    ranked = frame[["date", prob_col, outcome_col]].copy()
    grouped = ranked.groupby("date")
    ranked["rp"] = grouped[prob_col].rank()
    ranked["ro"] = grouped[outcome_col].rank()
    counts = grouped.size()
    with np.errstate(invalid="ignore", divide="ignore"):
        ic = ranked.groupby("date")[["rp", "ro"]].corr().xs("rp", level=1)["ro"]
    return ic.where(counts >= min_names).rename("ic")


def expected_value(frame: pd.DataFrame, cell: BarrierCell, neither_ret: float) -> pd.Series:
    """EV of the long trade as a return, from decision-time quantities only:
    P(+1)*U*A/close - P(-1)*D*A/close + P(0)*neither_ret, with U, D the cell's
    actual distances (`upper_atr`, `lower_atr`)."""
    a = frame["atr"].to_numpy(dtype=float) / frame["close_t"].to_numpy(dtype=float)
    ev = frame["p_up"] * cell.upper_atr * a - frame["p_down"] * cell.lower_atr * a + frame["p_neither"] * neither_ret
    return ev.rename("ev")


def top_k_daily(frame: pd.DataFrame, cell: BarrierCell, neither_ret: float, k: int,
                costs_bps: tuple[int, ...] = COSTS_BPS) -> pd.DataFrame:
    """Each day, the `k` rows with the highest EV (ties broken by ticker; a day
    with fewer rows takes them all). Per date: n_picked, hit_rate (share hitting
    +1), ret (mean realised return, gross), ret_net_<c>bps per cost level, and
    excess: ret minus that day's mean return over every row scored -- the
    within-day skill, with the market's own move on the day removed."""
    day_mean = frame.groupby("date")["ret"].mean()
    picks = frame.assign(ev=expected_value(frame, cell, neither_ret)).dropna(subset=["ev"])
    picks = picks.sort_values(["date", "ev", "ticker"], ascending=[True, False, True])
    picks = picks.groupby("date", sort=True).head(k)
    g = picks.groupby("date")
    out = pd.DataFrame({
        "n_picked": g.size(),
        "hit_rate": g["hit"].apply(lambda h: (h == 1).mean()),
        "ret": g["ret"].mean(),
    })
    for c in costs_bps:
        out[f"ret_net_{c}bps"] = out["ret"] - c / 1e4
    out["excess"] = out["ret"] - day_mean.reindex(out.index)
    return out


def cell_metrics(
    frame: pd.DataFrame,
    cell: BarrierCell,
    neither_ret: float,
    by: str | None = "fold",
    ks: tuple[int, ...] = TOP_K,
    costs_bps: tuple[int, ...] = COSTS_BPS,
) -> pd.DataFrame:
    """One summary row per value of `by` (e.g. fold, year, half), or a single
    row with `by=None`. Rows with a NaN label are dropped first (unresolved
    windows). The reliability curves are separate (`reliability`)."""
    frame = frame.dropna(subset=["hit"])
    groups = [(None, frame)] if by is None else list(frame.groupby(by, sort=True))
    rows = []
    for key, g in groups:
        n_dates = g["date"].nunique()
        row = {
            "horizon": cell.horizon, "upper": cell.upper, "lower": cell.lower,
            "upper_atr": cell.upper_atr, "lower_atr": cell.lower_atr,
            "n_rows": len(g), "n_dates": n_dates,
            "tie_share": float(g["tie"].mean()) if "tie" in g and len(g) else np.nan,
            "capped_share": float(g["capped"].mean()) if "capped" in g and len(g) else np.nan,
        }
        if by is not None:
            row = {by: key, **row}
        computable = n_dates >= min_dates(cell.horizon)
        row["status"] = OK if computable else NOT_COMPUTABLE
        if computable:
            row["brier"] = float(brier_rows(g).mean())
            row["log_loss"] = float(log_loss_rows(g).mean())
            row["base_rate_up"] = float((g["hit"] == 1).mean())
            ic = daily_ic(g)
            row["ic_mean"] = float(ic.mean())
            row["ic_n_dates"] = int(ic.notna().sum())
            for k in ks:
                daily = top_k_daily(g, cell, neither_ret, k, costs_bps)
                row[f"top{k}_hit_rate"] = float(daily["hit_rate"].mean())
                row[f"top{k}_ret"] = float(daily["ret"].mean())
                row[f"top{k}_excess"] = float(daily["excess"].mean())
                for c in costs_bps:
                    row[f"top{k}_ret_net_{c}bps"] = float(daily[f"ret_net_{c}bps"].mean())
                row[f"top{k}_short_days"] = int((daily["n_picked"] < k).sum())
        rows.append(row)
    return pd.DataFrame(rows)

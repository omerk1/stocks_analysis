"""Survival-analysis machinery for M6.4 (DESIGN.md, "M6.4 -- Slope
persistence and flip hazard"; PREREGISTRATION.md, 2026-09-24). Nothing
like this exists elsewhere in `stats/` -- a standard Kaplan-Meier
product-limit estimator plus a GBM-null simulator, built fresh for this
module rather than adding a new project dependency for one estimator.

Framing (DESIGN's own): not "does slope predict return" but "given a
slope-positive run has lasted N days, what's the probability it flips in
the next k?" -- a run's *duration* is right-censored when the run is still
active at the end of a ticker's own available history (delisting, or the
study's own coverage-window boundary), never truncated or dropped.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def kaplan_meier(durations: pd.Series, events: pd.Series) -> pd.DataFrame:
    """Standard product-limit estimator. `events`: 1 where the run ended
    in an observed flip, 0 where it was still ongoing when the ticker's
    own data ended (right-censored) -- never drop censored rows, they
    still inform `at_risk` at every time up to their own duration (the
    same "censored, not absent" discipline `features/state.py`'s own
    run-length censoring uses).

    Returns one row per distinct *event* time (censoring-only times don't
    get their own row, standard KM convention), columns `time`,
    `survival`, `at_risk`, `events`. `survival` is the step function's
    value *at and after* `time`, i.e. this table alone is enough to look
    up `survival_at(t)` for any query time via `survival_at` below.
    """
    df = pd.DataFrame({"duration": np.asarray(durations, dtype=float), "event": np.asarray(events, dtype=int)})
    df = df.dropna(subset=["duration"])
    n = len(df)
    if n == 0:
        return pd.DataFrame(columns=["time", "survival", "at_risk", "events"])

    event_times = np.sort(df.loc[df["event"] == 1, "duration"].unique())
    durations_arr = df["duration"].to_numpy()
    events_arr = df["event"].to_numpy()

    rows = []
    survival = 1.0
    for t in event_times:
        at_risk = int((durations_arr >= t).sum())
        n_events = int(((durations_arr == t) & (events_arr == 1)).sum())
        if at_risk == 0:
            continue
        survival *= 1.0 - n_events / at_risk
        rows.append({"time": float(t), "survival": survival, "at_risk": at_risk, "events": n_events})
    return pd.DataFrame(rows)


def survival_at(km_table: pd.DataFrame, t: float) -> float:
    """Step-function lookup: the KM curve's value at time `t` (1.0 before
    the first event time, the last event time's own survival value for any
    `t` past the final observed event). NaN if `km_table` is empty.
    """
    if km_table.empty:
        return float("nan")
    prior = km_table[km_table["time"] <= t]
    if prior.empty:
        return 1.0
    return float(prior["survival"].iloc[-1])


def simulate_gbm_paths(n_paths: int, n_days: int, mu: float, sigma: float, seed: int) -> np.ndarray:
    """`n_paths` independent GBM price paths (i.i.d. daily log-returns
    `Normal(mu, sigma)`, matching this study's own `slope_log_k` log-scale
    convention -- CLAUDE.md invariant #7), each starting at price 100.
    Shape `(n_paths, n_days)`.
    """
    rng = np.random.default_rng(seed)
    log_returns = rng.normal(mu, sigma, size=(n_paths, n_days))
    log_prices = np.log(100.0) + np.cumsum(log_returns, axis=1)
    return np.exp(log_prices)


def _sma(prices: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average along axis 1 (days), NaN for the first
    `period - 1` columns of each path -- vectorised via a cumulative-sum
    trick, not a per-day Python loop (this study's own "vectorise across
    the panel" style rule applies to simulated paths too).
    """
    n_paths, n_days = prices.shape
    out = np.full((n_paths, n_days), np.nan)
    csum = np.cumsum(prices, axis=1)
    out[:, period - 1] = csum[:, period - 1] / period
    if n_days > period:
        out[:, period:] = (csum[:, period:] - csum[:, :-period]) / period
    return out


def _slope_sign_runs_single_path(slope_positive: np.ndarray) -> list[tuple[float, int]]:
    """`(duration, event)` pairs for one boolean path (NaN-padded prefix
    allowed), same censoring convention as the real-data construction:
    the first run is left-censored (dropped, unknown true start), the
    last run is right-censored (`event=0`, still active when the path
    ends), every run in between ended in an observed flip (`event=1`).
    """
    valid = ~np.isnan(slope_positive)
    if not valid.any():
        return []
    first_valid = int(np.argmax(valid))
    vals = slope_positive[first_valid:].astype(bool)

    change_points = np.flatnonzero(np.diff(vals)) + 1
    run_starts = np.concatenate(([0], change_points))
    run_ends = np.concatenate((change_points, [len(vals)]))
    run_lengths = run_ends - run_starts

    pairs = []
    # Run 0 (first) is left-censored -- drop, matching `features/state.py`'s
    # own `run_length_bucket` convention for the real-data construction.
    for i in range(1, len(run_lengths)):
        is_last = i == len(run_lengths) - 1
        pairs.append((float(run_lengths[i]), 0 if is_last else 1))
    return pairs


def gbm_null_survival(
    n_paths: int,
    n_days: int,
    mu: float,
    sigma: float,
    sma_period: int,
    slope_k: int,
    seed: int,
    n_groups: int = 100,
) -> dict:
    """Simulates `n_paths` GBM paths, runs the identical
    SMA -> `slope_log_k` -> sign-run construction real data goes through,
    and returns a pooled null KM curve plus a simulation envelope (5th/95th
    percentile survival at each of a fixed grid of reference horizons,
    computed by splitting the paths into `n_groups` independent groups and
    taking each group's own pooled KM curve as one replicate -- a
    simulation-based band, not a bootstrap of a single sample, since the
    "sample" here is generated data, not observed data needing resampling).
    """
    prices = simulate_gbm_paths(n_paths, n_days, mu, sigma, seed)
    sma = _sma(prices, sma_period)
    log_sma = np.log(sma)
    slope = log_sma[:, slope_k:] - log_sma[:, :-slope_k]
    slope_padded = np.concatenate([np.full((n_paths, slope_k), np.nan), slope], axis=1)
    slope_positive = np.where(np.isnan(slope_padded), np.nan, (slope_padded > 0).astype(float))

    group_size = max(1, n_paths // n_groups)
    reference_horizons = (5, 10, 21, 42, 63, 126)
    envelope_rows = {h: [] for h in reference_horizons}
    all_pairs: list[tuple[float, int]] = []

    for g in range(n_groups):
        group_paths = slope_positive[g * group_size : (g + 1) * group_size]
        if len(group_paths) == 0:
            continue
        group_pairs: list[tuple[float, int]] = []
        for path in group_paths:
            group_pairs.extend(_slope_sign_runs_single_path(path))
        all_pairs.extend(group_pairs)
        if not group_pairs:
            continue
        durations, events = zip(*group_pairs)
        km = kaplan_meier(pd.Series(durations), pd.Series(events))
        for h in reference_horizons:
            envelope_rows[h].append(survival_at(km, h))

    pooled_durations, pooled_events = zip(*all_pairs) if all_pairs else ((), ())
    pooled_km = kaplan_meier(pd.Series(pooled_durations), pd.Series(pooled_events))

    envelope = {}
    for h in reference_horizons:
        vals = np.array(envelope_rows[h], dtype=float)
        vals = vals[~np.isnan(vals)]
        if len(vals) == 0:
            envelope[h] = (float("nan"), float("nan"))
        else:
            envelope[h] = (float(np.percentile(vals, 5)), float(np.percentile(vals, 95)))

    return {"km": pooled_km, "envelope": envelope, "n_runs": len(all_pairs)}

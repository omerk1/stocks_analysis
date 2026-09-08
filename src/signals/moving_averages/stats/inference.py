"""Block-bootstrap inference for matched-control deltas (DESIGN.md §6.2).

21-day forward returns overlap 20/21 -- naive SEs from the raw row/date
count are inflated by roughly sqrt(21) (DESIGN §6.2). This module resamples
*dates* in contiguous blocks (block length >= 2x horizon, per §6.2), not
rows, so the resampling unit respects the overlap structure rather than
pretending every row is an independent draw.

Performance note: a bootstrap draw does NOT re-run `c2_delta` on a
duplicated/resampled copy of the full panel (too slow at 500+ draws over a
1M+ row panel). Instead, `stratum_deltas` computes each (date, *match_cols)
stratum's (event_mean - control_mean) exactly once -- the same quantity
`c2_delta` averages across strata -- and the bootstrap loop reweights that
small, precomputed table by how many times each date was drawn. Repeating
a date k times in the resampled sequence is mathematically identical to
giving that date's strata weight k in the stratum average, so this is not
an approximation of the literal block-resampling estimator, it's the same
estimator computed efficiently.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def stratum_deltas(
    panel: pd.DataFrame,
    group_col: str,
    value_col: str,
    match_cols: list[str],
    date_col: str = "date",
) -> pd.DataFrame:
    """Per (date, *match_cols) stratum: event_mean - control_mean --
    exactly the per-stratum quantity `stats.controls.c2_delta` averages
    across strata (`c2_delta`'s point estimate == `stratum_deltas(...)
    ["delta"].mean()`). Strata missing an event or control side are
    dropped, same convention as `c2_delta`.
    """
    required = [date_col, group_col, value_col, *match_cols]
    valid = panel[required].dropna(subset=[group_col, value_col, *match_cols])
    is_event = valid[group_col].astype(bool)

    strata_cols = [date_col, *match_cols]
    event_mean = valid[is_event].groupby(strata_cols, observed=True)[value_col].mean()
    control_mean = valid[~is_event].groupby(strata_cols, observed=True)[value_col].mean()
    delta = (event_mean - control_mean).dropna().rename("delta")
    return delta.reset_index()


def _block_weights(dates: np.ndarray, block_length: int, rng: np.random.Generator) -> np.ndarray:
    """One moving-block-bootstrap draw's weight per original date index --
    circular blocks (wrapping at the end), enough blocks to cover the full
    date range. Weight[i] = how many times date i appears in this draw's
    resampled date sequence.
    """
    n_dates = len(dates)
    n_blocks = int(np.ceil(n_dates / block_length))
    starts = rng.integers(0, n_dates, size=n_blocks)
    weight = np.zeros(n_dates)
    for start in starts:
        idx = (start + np.arange(block_length)) % n_dates
        weight[idx] += 1
    return weight


def block_bootstrap_delta(
    panel: pd.DataFrame,
    group_col: str,
    value_col: str,
    match_cols: list[str],
    date_col: str = "date",
    block_length: int = 42,
    n_boot: int = 500,
    ci: float = 0.90,
    seed: int = 0,
) -> dict:
    """Block-bootstrap CI on the C2-style matched-control delta (DESIGN
    §6.2/§6.3). `block_length` defaults to 42 (2x the 21-day horizon this
    study uses everywhere, per §6.2's "block length >= 2x horizon").

    Returns `point_estimate` (identical to calling `c2_delta` directly),
    `ci_low`/`ci_high` at the requested `ci` level, `boot_std`, and
    `n_dates` (the effective-N count DESIGN §6.3 asks every table to
    carry -- distinct dates contributing at least one valid stratum, not
    the raw row count).
    """
    deltas = stratum_deltas(panel, group_col, value_col, match_cols, date_col)
    if deltas.empty:
        return {"point_estimate": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                "boot_std": float("nan"), "n_dates": 0, "n_boot": 0}

    dates = np.array(sorted(deltas[date_col].unique()))
    date_index = {d: i for i, d in enumerate(dates)}
    strata_date_idx = deltas[date_col].map(date_index).to_numpy()
    delta_values = deltas["delta"].to_numpy()

    point_estimate = delta_values.mean()

    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_boot)
    for b in range(n_boot):
        weight = _block_weights(dates, block_length, rng)
        row_weight = weight[strata_date_idx]
        total = row_weight.sum()
        boot_means[b] = (row_weight * delta_values).sum() / total if total > 0 else np.nan

    boot_means = boot_means[~np.isnan(boot_means)]
    tail = (1 - ci) / 2
    return {
        "point_estimate": point_estimate,
        "ci_low": float(np.quantile(boot_means, tail)),
        "ci_high": float(np.quantile(boot_means, 1 - tail)),
        "boot_std": float(boot_means.std()),
        "n_dates": len(dates),
        "n_boot": len(boot_means),
    }


def block_bootstrap_spread(
    panel: pd.DataFrame,
    decile_col: str,
    decile_low: int,
    decile_high: int,
    value_col: str,
    match_cols: list[str],
    date_col: str = "date",
    block_length: int = 42,
    n_boot: int = 500,
    ci: float = 0.90,
    seed: int = 0,
) -> dict:
    """Block-bootstrap CI on the (decile_high - decile_low) C2 spread --
    the headline "C2 delta" per facet used throughout M4. Both deciles'
    per-stratum deltas are resampled with the *same* draw's date weights
    each iteration (not independently), since they share the same
    underlying dates and their bootstrap draws are correlated -- taking
    separately-bootstrapped CIs and differencing the endpoints would be
    wrong; the spread must be computed within each draw.
    """
    # group_col must be boolean; build it per decile explicitly.
    panel_low = panel.assign(**{"__is_event": panel[decile_col] == decile_low})
    panel_high = panel.assign(**{"__is_event": panel[decile_col] == decile_high})

    low = stratum_deltas(panel_low, "__is_event", value_col, match_cols, date_col)
    high = stratum_deltas(panel_high, "__is_event", value_col, match_cols, date_col)

    all_dates = np.array(sorted(set(low[date_col]).union(high[date_col])))
    if len(all_dates) == 0:
        return {"point_estimate": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                "boot_std": float("nan"), "n_dates": 0, "n_boot": 0}
    date_index = {d: i for i, d in enumerate(all_dates)}

    low_idx = low[date_col].map(date_index).to_numpy()
    low_vals = low["delta"].to_numpy()
    high_idx = high[date_col].map(date_index).to_numpy()
    high_vals = high["delta"].to_numpy()

    point_low = low_vals.mean() if len(low_vals) else float("nan")
    point_high = high_vals.mean() if len(high_vals) else float("nan")
    point_estimate = point_high - point_low

    rng = np.random.default_rng(seed)
    boot_spreads = np.empty(n_boot)
    for b in range(n_boot):
        weight = _block_weights(all_dates, block_length, rng)

        low_w = weight[low_idx]
        low_total = low_w.sum()
        low_mean = (low_w * low_vals).sum() / low_total if low_total > 0 else np.nan

        high_w = weight[high_idx]
        high_total = high_w.sum()
        high_mean = (high_w * high_vals).sum() / high_total if high_total > 0 else np.nan

        boot_spreads[b] = high_mean - low_mean

    boot_spreads = boot_spreads[~np.isnan(boot_spreads)]
    tail = (1 - ci) / 2
    return {
        "point_estimate": point_estimate,
        "ci_low": float(np.quantile(boot_spreads, tail)),
        "ci_high": float(np.quantile(boot_spreads, 1 - tail)),
        "boot_std": float(boot_spreads.std()),
        "n_dates": len(all_dates),
        "n_boot": len(boot_spreads),
    }

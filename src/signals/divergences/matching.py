"""Event-to-control matching for the Track-B run, exactly as
pre-registered (PREREGISTRATION.md "Controls"): within p2 calendar month,
nearest-neighbor on (impulse decile, realized-vol bucket), up to 3
controls per event, sampled without replacement. Pure functions over
frames the run script assembles; covariates only -- no outcome column
ever enters this module, so the balance report can run (and be reviewed)
before anything is unblinded."""

from __future__ import annotations

import numpy as np
import pandas as pd

MAX_CONTROLS_PER_EVENT = 3
N_IMPULSE_BINS = 10
N_VOL_BINS = 5

# Context poles, PREREGISTRATION "Context classification". Everything
# else (buffer band, deep-fast, NaN scalars) is None = out of the primary
# contrast.
RETRACE_EXTENSION_MAX = 0.25
RETRACE_PULLBACK_MIN = 0.33
LEG2_PULLBACK_MIN = 5


def classify_context(retrace_frac, leg2_bars) -> str | None:
    if retrace_frac is None or pd.isna(retrace_frac):
        return None
    if retrace_frac < RETRACE_EXTENSION_MAX:
        return "extension"
    if retrace_frac >= RETRACE_PULLBACK_MIN and leg2_bars is not None and not pd.isna(leg2_bars) and leg2_bars >= LEG2_PULLBACK_MIN:
        return "pullback_rebuild"
    return None


def quantile_edges(values: pd.Series, n_bins: int) -> np.ndarray:
    """Interior quantile edges over the POOLED events+controls sample --
    computed once by the caller and reused for both sides, so a bucket
    means the same thing for an event and its candidate controls."""
    clean = values.dropna()
    return clean.quantile(np.linspace(0, 1, n_bins + 1)[1:-1]).to_numpy()


def assign_bucket(values: pd.Series, edges: np.ndarray) -> pd.Series:
    """np.searchsorted bucketing; NaN stays NaN (unmatched -- missingness
    is preserved, never silently bucketed)."""
    out = pd.Series(np.searchsorted(edges, values.to_numpy()), index=values.index, dtype="float")
    out[values.isna()] = np.nan
    return out


def match_controls(
    events: pd.DataFrame,
    controls: pd.DataFrame,
    seed: int = 20261007,
    max_per_event: int = MAX_CONTROLS_PER_EVENT,
) -> pd.DataFrame:
    """Greedy without-replacement matching. Both frames need columns:
    id, direction, context_class, p2_month (YYYY-MM string),
    impulse_gain_pct, realized_vol_63 -- bucket columns are derived here
    from pooled quantiles. Returns a frame (event_id, control_id, rank).

    Greedy order is randomized by `seed` (events shuffled once), so no
    alphabetic-ticker systematic claims the scarce controls first, and the
    whole match is reproducible from the seed.
    """
    rng = np.random.default_rng(seed)

    pooled_impulse = pd.concat([events["impulse_gain_pct"], controls["impulse_gain_pct"]])
    pooled_vol = pd.concat([events["realized_vol_63"], controls["realized_vol_63"]])
    imp_edges = quantile_edges(pooled_impulse, N_IMPULSE_BINS)
    vol_edges = quantile_edges(pooled_vol, N_VOL_BINS)

    events = events.copy()
    controls = controls.copy()
    for frame in (events, controls):
        frame["impulse_bin"] = assign_bucket(frame["impulse_gain_pct"], imp_edges)
        frame["vol_bin"] = assign_bucket(frame["realized_vol_63"], vol_edges)

    # Hard cell = (direction, context_class, p2_month); the covariate bins
    # act as a +/-1 CALIPER inside it rather than an exact-cell key --
    # exact bin equality on a fine decile grid is brittle at bin edges (an
    # event can sit one bin away from a control 0.001 apart in raw value
    # and lose it). Within the caliper, nearest by raw impulse distance,
    # raw vol distance as tiebreaker, id as the final deterministic one.
    cell_cols = ["direction", "context_class", "p2_month"]
    controls_by_cell: dict[tuple, pd.DataFrame] = {
        key: grp for key, grp in controls.dropna(subset=["impulse_bin", "vol_bin"]).groupby(cell_cols)
    }
    used: set = set()
    matches: list[dict] = []

    order = events.dropna(subset=["impulse_bin", "vol_bin"]).index.to_numpy().copy()
    rng.shuffle(order)
    for idx in order:
        ev = events.loc[idx]
        key = tuple(ev[c] for c in cell_cols)
        pool = controls_by_cell.get(key)
        if pool is None:
            continue
        available = pool[
            ~pool["id"].isin(used)
            & ((pool["impulse_bin"] - ev["impulse_bin"]).abs() <= 1)
            & ((pool["vol_bin"] - ev["vol_bin"]).abs() <= 1)
        ]
        if available.empty:
            continue
        dist = (available["impulse_gain_pct"] - ev["impulse_gain_pct"]).abs()
        vol_dist = (available["realized_vol_63"] - ev["realized_vol_63"]).abs()
        ranked = available.assign(_d=dist, _v=vol_dist).sort_values(["_d", "_v", "id"])
        take = ranked.head(max_per_event)
        for rank, ctrl in enumerate(take.itertuples(index=False), start=1):
            used.add(ctrl.id)
            matches.append({"event_id": ev["id"], "control_id": ctrl.id, "rank": rank})

    return pd.DataFrame(matches, columns=["event_id", "control_id", "rank"])


def standardized_mean_difference(a: pd.Series, b: pd.Series) -> float:
    a, b = a.dropna(), b.dropna()
    if a.empty or b.empty:
        return float("nan")
    pooled_sd = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    if not np.isfinite(pooled_sd) or pooled_sd == 0:
        return float("nan")
    return float((a.mean() - b.mean()) / pooled_sd)


BALANCE_COVARIATES = [
    "impulse_gain_pct", "realized_vol_63", "interpeak_retrace_frac", "leg2_bars",
]


def balance_report(
    events: pd.DataFrame, controls: pd.DataFrame, matches: pd.DataFrame
) -> pd.DataFrame:
    """Per (direction, context_class) x covariate: SMD of events vs the
    FULL control pool (before) and vs the matched controls (after), plus
    counts. |SMD| after matching is the match-quality number the run
    report quotes; covariates only, no outcomes."""
    matched_controls = controls[controls["id"].isin(matches["control_id"])]
    matched_events = events[events["id"].isin(matches["event_id"])]
    rows = []
    for (direction, cls), ev_grp in matched_events.groupby(["direction", "context_class"]):
        pool = controls[(controls["direction"] == direction) & (controls["context_class"] == cls)]
        mctrl = matched_controls[
            (matched_controls["direction"] == direction) & (matched_controls["context_class"] == cls)
        ]
        for cov in BALANCE_COVARIATES:
            rows.append(
                {
                    "direction": direction,
                    "context_class": cls,
                    "covariate": cov,
                    "smd_before": standardized_mean_difference(ev_grp[cov], pool[cov]),
                    "smd_after": standardized_mean_difference(ev_grp[cov], mctrl[cov]),
                    "n_events": len(ev_grp),
                    "n_pool": len(pool),
                    "n_matched": len(mctrl),
                }
            )
    return pd.DataFrame(rows)

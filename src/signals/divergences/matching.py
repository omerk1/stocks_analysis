"""Event-to-control matching for the Track-B run, exactly as
pre-registered (PREREGISTRATION.md "Controls", as amended 2026-10-07):
hard cell = p2 calendar month within direction x context class; a +/-1-bin
caliper on THREE covariates (impulse deciles, realized-vol quintiles,
retrace-fraction quintiles), each bucketed on pooled events+controls
quantiles computed PER (direction, context class) -- cross-class pooling
would make the retrace caliper vacuous inside the extension class, whose
retrace values all sit below every pullback-dominated edge; nearest by
raw impulse distance, retrace then vol as tiebreakers; up to 3 controls
per event, without replacement, greedy in a seed-fixed random order.

Pure functions over frames the run script assembles; covariates only --
no outcome column ever enters this module, so the balance report can run
(and be reviewed) before anything is unblinded."""

from __future__ import annotations

import numpy as np
import pandas as pd

MAX_CONTROLS_PER_EVENT = 3
N_IMPULSE_BINS = 10
N_VOL_BINS = 5
# Third covariate (PREREG amendment 2026-10-07): matched on impulse+vol
# alone, retrace depth retained SMD -0.37/-0.50 within the pullback class
# -- events sit shallower in the class than their controls. Quintiles,
# not deciles: the class bounds already cap its range.
N_RETRACE_BINS = 5

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
    impulse_gain_pct, realized_vol_63, interpeak_retrace_frac -- bucket
    columns are derived here from pooled quantiles computed PER
    (direction, context class). Returns a frame (event_id, control_id,
    rank).

    Greedy order is randomized by `seed` (events shuffled once), so no
    alphabetic-ticker systematic claims the scarce controls first, and the
    whole match is reproducible from the seed.

    The quantile edges are a dev-window (full-sample) statistic -- a
    sanctioned, pre-registered exception to the rolling-statistics
    invariant: matching is ex-post control construction at analysis time,
    not a tradable feature (PREREGISTRATION "Controls").
    """
    rng = np.random.default_rng(seed)

    covariate_bins = {
        "impulse_gain_pct": ("impulse_bin", N_IMPULSE_BINS),
        "realized_vol_63": ("vol_bin", N_VOL_BINS),
        "interpeak_retrace_frac": ("retrace_bin", N_RETRACE_BINS),
    }
    events = events.copy()
    controls = controls.copy()
    for cov, (bin_col, _n) in covariate_bins.items():
        events[bin_col] = np.nan
        controls[bin_col] = np.nan
    class_keys = set(
        map(tuple, pd.concat([events[["direction", "context_class"]],
                              controls[["direction", "context_class"]]]).drop_duplicates().to_numpy())
    )
    for direction, cls in class_keys:
        ev_mask = (events["direction"] == direction) & (events["context_class"] == cls)
        ct_mask = (controls["direction"] == direction) & (controls["context_class"] == cls)
        for cov, (bin_col, n_bins) in covariate_bins.items():
            edges = quantile_edges(
                pd.concat([events.loc[ev_mask, cov], controls.loc[ct_mask, cov]]), n_bins
            )
            events.loc[ev_mask, bin_col] = assign_bucket(events.loc[ev_mask, cov], edges)
            controls.loc[ct_mask, bin_col] = assign_bucket(controls.loc[ct_mask, cov], edges)

    # Hard cell = (direction, context_class, p2_month); the covariate bins
    # act as a +/-1 CALIPER inside it rather than an exact-cell key --
    # exact bin equality on a fine decile grid is brittle at bin edges (an
    # event can sit one bin away from a control 0.001 apart in raw value
    # and lose it). Within the caliper, nearest by raw impulse distance,
    # then raw retrace distance, then raw vol distance, id as the final
    # deterministic tiebreaker.
    cell_cols = ["direction", "context_class", "p2_month"]
    bin_cols = ["impulse_bin", "vol_bin", "retrace_bin"]
    controls_by_cell: dict[tuple, pd.DataFrame] = {
        key: grp for key, grp in controls.dropna(subset=bin_cols).groupby(cell_cols)
    }
    used: set = set()
    matches: list[dict] = []

    order = events.dropna(subset=bin_cols).index.to_numpy().copy()
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
            & ((pool["retrace_bin"] - ev["retrace_bin"]).abs() <= 1)
        ]
        if available.empty:
            continue
        dist = (available["impulse_gain_pct"] - ev["impulse_gain_pct"]).abs()
        ret_dist = (available["interpeak_retrace_frac"] - ev["interpeak_retrace_frac"]).abs()
        vol_dist = (available["realized_vol_63"] - ev["realized_vol_63"]).abs()
        ranked = available.assign(_d=dist, _r=ret_dist, _v=vol_dist).sort_values(["_d", "_r", "_v", "id"])
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
    """Per (direction, context_class) x covariate: SMD of ALL classified
    events vs the full control pool (before) and of MATCHED events vs
    their matched controls (after), plus counts for every denominator.
    The before side deliberately includes events matching failed to serve
    -- they skew toward the covariate extremes, and excluding them (an
    earlier bug) understates pre-match imbalance and flatters the
    shrinkage. Covariates only, no outcomes."""
    matched_controls = controls[controls["id"].isin(matches["control_id"])]
    matched_events = events[events["id"].isin(matches["event_id"])]
    rows = []
    for (direction, cls), ev_all in events.groupby(["direction", "context_class"]):
        pool = controls[(controls["direction"] == direction) & (controls["context_class"] == cls)]
        m_ev = matched_events[
            (matched_events["direction"] == direction) & (matched_events["context_class"] == cls)
        ]
        mctrl = matched_controls[
            (matched_controls["direction"] == direction) & (matched_controls["context_class"] == cls)
        ]
        for cov in BALANCE_COVARIATES:
            rows.append(
                {
                    "direction": direction,
                    "context_class": cls,
                    "covariate": cov,
                    "smd_before": standardized_mean_difference(ev_all[cov], pool[cov]),
                    "smd_after": standardized_mean_difference(m_ev[cov], mctrl[cov]),
                    "n_events": len(ev_all),
                    "n_matched_events": len(m_ev),
                    "n_pool": len(pool),
                    "n_matched": len(mctrl),
                }
            )
    return pd.DataFrame(rows)

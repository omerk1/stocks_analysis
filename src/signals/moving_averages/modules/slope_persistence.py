"""M6.4 -- Slope persistence and flip hazard (DESIGN.md lines ~835-839;
PREREGISTRATION.md, 2026-09-24).

Track B. DESIGN's own reframing: not "does slope predict return" but
"given the N-day SMA's own slope has been positive for N days, what is the
probability it flips in the next k?" -- a survival/hazard question, a
better fit for how slope is actually used (a trend-intact/trend-broken
switch) than a return-prediction question. Compares an empirical
Kaplan-Meier survival curve for slope-positive runs against a GBM-null
simulation calibrated to the same volatility level -- DESIGN's own framing:
"the finding is only interesting where the empirical hazard departs from
the simulated null."

Shared-feature note: this module originally carried its own local,
temporary `efficiency_ratio` (built in parallel before a sibling M9 fork's
`features/regime.py` landed). **Reconciled 2026-09-25**: now imports M9's
shared `efficiency_ratio` directly. The two implementations differed in one
respect -- this module's own original version used `.fillna(0.0)`, silently
treating an undefined warmup row as "zero efficiency ratio" (pure chop)
rather than missing (a CLAUDE.md invariant #9 concern); `features/regime.py`'s
version correctly leaves warmup as NaN and only maps `inf` (a zero-volatility
window) to NaN. Confirmed harmless to every number already logged: this
module's shortest slope construction (`slope_log_21_sma_20`) needs ~41 days
of warmup before a run can start, far past `efficiency_ratio`'s own 10-day
warmup, so no real run-entry row was ever classified via the undefined-as-
zero path -- checked directly, not assumed, before swapping the
implementation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features import state
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.features.regime import efficiency_ratio
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.survival import gbm_null_survival, kaplan_meier, survival_at

LOOKBACKS = (20, 50, 150, 200)
SLOPE_K = 21
REFERENCE_HORIZON = 21
N_VOL_BUCKETS = 3
N_ER_BUCKETS = 3
GBM_N_PATHS = 2000
GBM_N_DAYS = 1500
GBM_N_GROUPS = 100


def slope_column(lookback: int) -> str:
    return f"slope_log_{SLOPE_K}_sma_{lookback}"


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds the local `efficiency_ratio` feature (lagged, module-local, not
    written to the shared panel), `vol_tercile`/`er_tercile` per-date
    cross-sectional buckets, and a `slope_positive_<lookback>` boolean
    (NaN-preserving, CLAUDE.md invariant #9) for each of `LOOKBACKS`.
    Returns a new frame; `panel` itself is not mutated.
    """
    working = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    working["efficiency_ratio_raw"] = working.groupby("ticker")["close"].transform(
        lambda s: efficiency_ratio(s)
    )
    working = apply_lag(working, ["efficiency_ratio_raw"])
    working["efficiency_ratio"] = working["efficiency_ratio_raw"]

    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=N_VOL_BUCKETS)
    working["er_tercile"] = cross_sectional_bucket(working, "efficiency_ratio", n_buckets=N_ER_BUCKETS)

    for lookback in LOOKBACKS:
        col = slope_column(lookback)
        valid = working[col].notna()
        working[f"slope_positive_{lookback}"] = (working[col] > 0).where(valid)

    return working


def build_run_table(working: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """One row per (ticker, run) of `slope_positive_<lookback>`, excluding
    the left-censored first run per ticker (`run_id == 0`, same convention
    `features/state.py::run_length_bucket` already uses). `duration` is the
    run's own observed length; `event=1` if the run ended in an observed
    flip, `event=0` if it was still the ticker's *current* (most recent)
    run when its own history ends -- delisting or the study's coverage
    boundary, either way right-censored, never dropped (CLAUDE.md
    invariant #4's spirit applied to a duration, not a return).
    """
    slope_col = f"slope_positive_{lookback}"
    rows = []
    for ticker, group in working.groupby("ticker", sort=False):
        run_id = state.state_run_id(group[slope_col])
        days = state.days_in_run(group[slope_col], run_id=run_id)
        frame = group.assign(_run_id=run_id, _days=days)
        valid = frame["_run_id"].notna() & (frame["_run_id"] != 0)
        if not valid.any():
            continue
        summary = (
            frame[valid]
            .groupby("_run_id")
            .agg(
                duration=("_days", "max"),
                entry_vol_tercile=("vol_tercile", "first"),
                entry_er_tercile=("er_tercile", "first"),
                entry_realized_vol_63=("realized_vol_63", "first"),
                direction=(slope_col, "first"),
                entry_date=("date", "first"),
            )
            .reset_index()
        )
        max_run_id = summary["_run_id"].max()
        summary["event"] = (summary["_run_id"] != max_run_id).astype(int)
        summary["ticker"] = ticker
        rows.append(summary)

    if not rows:
        return pd.DataFrame(
            columns=["ticker", "_run_id", "duration", "entry_vol_tercile", "entry_er_tercile", "direction", "entry_date", "event"]
        )
    return pd.concat(rows, ignore_index=True)


def gbm_calibration(
    working: pd.DataFrame, run_table: pd.DataFrame, direction: bool = True,
    stratify_col: str = "entry_vol_tercile", n_buckets: int = N_VOL_BUCKETS,
) -> dict:
    """Global daily log-return drift (pooled across the whole panel, never
    per-stratum -- a stratum-specific drift would partly launder the very
    trend-persistence effect this module tests for into its own null) and
    a per-tercile sigma (median `realized_vol_63` among this direction's
    real run *entry* rows in that tercile of `stratify_col` -- a
    representative volatility level for that regime, whether the
    stratification axis is vol-tercile itself or the ER-tercile companion
    facet; the null's own noise level always tracks realized volatility
    either way, only the *grouping* changes).

    **Open calibration caveat, named not resolved (CLAUDE.md's own "argue
    against your own result" requirement):** `realized_vol_63` is computed
    from the *same* (potentially autocorrelated/trending) real return
    series this module is testing for persistence. If real returns have
    positive short-horizon autocorrelation, a trailing daily-return stdev
    can read *lower* than the volatility of a matched-total-variance i.i.d.
    process would over the same window -- meaning this null's `sigma` could
    be a systematically "too calm" input, which would mechanically shorten
    simulated run durations and bias this module's own comparison toward
    finding "departure from null" even without a genuine persistence edge.
    Not corrected here (would need a longer-horizon, autocorrelation-aware
    volatility estimator, e.g. a variance-ratio-implied one) -- flagged as
    an open validity question on the magnitude of any reported departure,
    not on whether this module's own construction is internally consistent.
    """
    log_returns = np.log(working["close"]).groupby(working["ticker"]).diff().dropna()
    mu = float(log_returns.mean())

    subset = run_table[run_table["direction"] == direction]
    sigma_by_tercile = {}
    for tercile in range(n_buckets):
        tercile_runs = subset[subset[stratify_col] == tercile]
        if tercile_runs.empty or tercile_runs["entry_realized_vol_63"].isna().all():
            sigma_by_tercile[tercile] = float(working["realized_vol_63"].median())
        else:
            sigma_by_tercile[tercile] = float(tercile_runs["entry_realized_vol_63"].median())

    return {"mu": mu, "sigma_by_tercile": sigma_by_tercile}


def stratum_result(
    run_table: pd.DataFrame, working: pd.DataFrame, lookback: int, tercile: int, direction: bool = True,
    stratify_col: str = "entry_vol_tercile", n_buckets: int = N_VOL_BUCKETS, seed_offset: int = 0,
) -> dict:
    """Empirical KM curve for one (lookback, tercile, direction) stratum
    vs. a GBM null calibrated to that stratum's own sigma. The decisive
    comparison (this module's own pre-registered kill criterion): is the
    empirical survival at `REFERENCE_HORIZON` days outside the null's 90%
    simulation envelope at that same horizon? `stratify_col` switches
    between the primary vol-tercile grid and the ER-tercile companion
    facet without duplicating this logic.
    """
    subset = run_table[(run_table[stratify_col] == tercile) & (run_table["direction"] == direction)]
    n_runs = len(subset)
    n_tickers = subset["ticker"].nunique()

    empirical_km = kaplan_meier(subset["duration"], subset["event"])
    empirical_survival_21 = survival_at(empirical_km, REFERENCE_HORIZON)

    calibration = gbm_calibration(working, run_table, direction=direction, stratify_col=stratify_col, n_buckets=n_buckets)
    sigma = calibration["sigma_by_tercile"][tercile]
    null = gbm_null_survival(
        n_paths=GBM_N_PATHS, n_days=GBM_N_DAYS, mu=calibration["mu"], sigma=sigma,
        sma_period=lookback, slope_k=SLOPE_K, seed=seed_offset + tercile * 100 + lookback, n_groups=GBM_N_GROUPS,
    )
    envelope_lo, envelope_hi = null["envelope"][REFERENCE_HORIZON]
    departs = (
        not np.isnan(empirical_survival_21)
        and not np.isnan(envelope_lo)
        and (empirical_survival_21 < envelope_lo or empirical_survival_21 > envelope_hi)
    )

    return {
        "lookback": lookback,
        "stratify_col": stratify_col,
        "tercile": tercile,
        "direction": "rising" if direction else "falling",
        "n_runs": n_runs,
        "n_tickers": n_tickers,
        "n_events": int(subset["event"].sum()),
        "empirical_survival_21d": empirical_survival_21,
        "null_envelope_21d_lo": envelope_lo,
        "null_envelope_21d_hi": envelope_hi,
        "null_sigma": sigma,
        "null_mu": calibration["mu"],
        "departs_from_null": bool(departs),
        "empirical_km": empirical_km,
        "null_km": null["km"],
    }


def evaluate_kill_criterion(results: list[dict]) -> dict:
    """PREREGISTRATION.md M6.4's own kill criterion: a stratum's persistence
    is "not distinguishable from a random walk's own run-length statistics"
    unless its empirical 21-day survival sits outside the GBM null's 90%
    simulation envelope at that horizon. Module-level: killed iff every
    declared primary stratum agrees with its own null.
    """
    n_strata = len(results)
    n_departing = sum(1 for r in results if r["departs_from_null"])
    return {
        "n_strata": n_strata,
        "n_departing": n_departing,
        "module_killed": n_departing == 0,
    }

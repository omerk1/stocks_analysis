"""M8 -- MA family horse race at matched lag (DESIGN.md lines ~930-934;
PREREGISTRATION.md, 2026-09-24).

Track B. See PREREGISTRATION.md for the full hypothesis / kill-criterion /
scope statement, including the module's own lag-matching methodology and
its two named exceptions (HMA, KAMA). Skeptical hypothesis: at matched
center of mass (average lag), kernel shape is nearly irrelevant to
above/below-state forward-return behavior.

7 families compared on an identical event definition (above/below state on
`fwd_ret_21`, the exact construction M1's own `state_table` uses): `sma`
and `ema` reuse the shared cached panel's own `above_sma_50`/`above_ema_50`
directly (SMA(50) is the module's own lag-matching reference point, so no
new computation needed there); `wma`/`hma`/`dema`/`kama`/`vwma` are new,
module-local columns (`features/kernels.py`) -- never added to the shared
panel (a sibling M10 fork owns `features/panel.py` exclusively this
batch).

`stats/multiple_testing.py::white_reality_check` (new, built for this
module) is the decisive statistical layer -- DESIGN's own named procedure
for the "best-performer claim," a different correction than this study's
usual BH pass (that controls false-discovery *rate* across many separately
reported cells; this controls for having searched over 7 candidates and
picked whichever looked best before crediting the winner with a real
edge).
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features import distance, kernels
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.modules.baseline_state import _cell_row
from src.signals.moving_averages.stats.controls import cross_sectional_bucket, stratum_deltas
from src.signals.moving_averages.stats.multiple_testing import white_reality_check

HORIZON = 21
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")
BENCHMARK_FAMILY = "ema"

# Matched-lag periods, derived via `features/kernels.py::solve_matched_period`
# against SMA(50)'s own center of mass (24.5) -- full derivation in
# PREREGISTRATION.md. `sma`/`ema` need no entry here: they reuse the
# shared panel's own already-lagged `sma_50`/`ema_50` columns directly
# (SMA(50) *is* this module's reference lag). `hma` is deliberately NOT
# matched (see PREREGISTRATION.md's own finding: HMA's lag-reduction is so
# extreme that matching SMA50's lag would need a ~1900-day period,
# impractical given this panel's ~3000-trading-day history) -- reported at
# `period=50`, the idiomatic "same n" convention, with its own much-shorter
# realized lag named explicitly as a limitation, not hidden. `kama` uses
# its own canonical parameters (no period at all -- adaptive by
# construction, a fixed lag is a category error for this family).
MATCHED_PERIODS = {"wma": 74, "hma": 50, "dema": 224, "vwma": 50}

NEW_LOCAL_FAMILIES = ("wma", "hma", "dema", "kama", "vwma")
FAMILIES = ("sma", "ema", *NEW_LOCAL_FAMILIES)

ABOVE_COLUMNS = {
    "sma": "above_sma_50",
    "ema": "above_ema_50",
    **{family: f"above_{family}_matched" for family in NEW_LOCAL_FAMILIES},
}

# DESIGN's own literal kill wording: "if no family beats EMA by > 0.1% at
# matched lag after Reality Check, declare MA family selection a
# non-question."
KILL_THRESHOLD = 0.001
REALITY_CHECK_ALPHA = 0.10  # this study's own standard significance convention, reused here


def add_family_columns(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `above_{family}_matched` for each of `NEW_LOCAL_FAMILIES` to
    `panel` (module-local, not the shared panel). Each family's raw
    (un-lagged) matched-period value is computed from the panel's own raw
    `close`/`volume` columns (never lagged by `build_panel` itself, per
    `features/panel.py`'s own `_NON_FEATURE_COLUMNS` convention), compared
    against raw `close` via `features/distance.py::above` (the same
    NaN-preserving above/below construction the shared panel itself uses
    for `above_sma_*`/`above_ema_*` -- CLAUDE.md invariant #9), and the
    resulting boolean state column is lagged once, exactly mirroring
    `features/panel.py`'s own "compute on raw same-day values, lag the
    state column once" order -- not lagging `close` and the matched value
    separately and then comparing (mathematically equivalent for a plain
    comparison, but this order matches the shared panel's own convention
    exactly, so a reader comparing the two code paths doesn't have to
    verify the two orderings are actually equivalent). `sma`/`ema` need no
    new column: `above_sma_50`/`above_ema_50` already exist, already
    correctly lagged, in the cached panel itself.
    """
    working = panel.sort_values(["ticker", "date"]).reset_index(drop=True)

    raw_above_cols = []
    for family in NEW_LOCAL_FAMILIES:
        if family == "kama":
            raw_value = working.groupby("ticker")["close"].transform(lambda s: kernels.kama(s))
        elif family == "vwma":
            # Not `.groupby().apply(...)`: with exactly one ticker group,
            # pandas' apply-then-concat inference returns a 1-row DataFrame
            # instead of a concatenated Series (a real edge case hit while
            # building this module's own tests) -- an explicit per-group
            # loop with index-based assignment sidesteps that inference
            # entirely, the same pattern `modules/volume_liquidity.py::
            # _is_reclaim` already uses for its own per-ticker computation.
            period = MATCHED_PERIODS["vwma"]
            raw_value = pd.Series(index=working.index, dtype=float)
            for _, group in working.groupby("ticker", sort=False):
                raw_value.loc[group.index] = kernels.vwma(group["close"], group["volume"], period).to_numpy()
        else:
            period = MATCHED_PERIODS[family]
            kernel_fn = getattr(kernels, family)
            raw_value = working.groupby("ticker")["close"].transform(lambda s, fn=kernel_fn, p=period: fn(s, p))

        raw_above_col = f"_raw_above_{family}"
        working[raw_above_col] = distance.above(working["close"], raw_value)
        raw_above_cols.append(raw_above_col)

    working = apply_lag(working, raw_above_cols)
    for family, raw_above_col in zip(NEW_LOCAL_FAMILIES, raw_above_cols):
        working[ABOVE_COLUMNS[family]] = working[raw_above_col]
    working = working.drop(columns=raw_above_cols)
    return working


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds the 5 new local family columns, `fwd_ret_21`, and the C2 match
    buckets to `panel`. Returns a new frame; `panel` itself is not
    mutated.
    """
    working = add_family_columns(panel)
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    return working


def family_table(working: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """The 7 primary cells: one per family, "above" state only (DESIGN's
    own "identical event definitions" wording -- one clean definition
    reused across every family, not fragmented into above+below x 7).
    Reuses `modules/baseline_state.py::_cell_row` directly, unchanged --
    the same C0/C1/C2/bootstrap/row-loss construction M1's own
    `state_table` already validated, applied to each family's own
    `above_{family}` column instead of only SMA's.
    """
    rows = []
    for family in FAMILIES:
        rows.append(_cell_row(working, ABOVE_COLUMNS[family], {"family": family}, match_cols=match_cols))
    return pd.DataFrame(rows)


def per_date_deltas(
    working: pd.DataFrame, group_col: str, match_cols: tuple[str, ...] = C2_MATCH_COLS, date_col: str = "date"
) -> pd.Series:
    """Per-date average C2-style stratum delta on `fwd_ret_21` -- the
    per-date time series `white_reality_check` needs (one value per date,
    pre-averaged across whatever `match_cols` strata exist that date).
    Distinct from `block_bootstrap_delta`'s own per-(date,stratum)-row
    reweighting in `stats/inference.py`, which resamples at the row level,
    not a pre-averaged per-date series -- Reality Check's own null
    resamples dates over a fixed per-date statistic per candidate.
    """
    deltas = stratum_deltas(working, group_col, "fwd_ret_21", [date_col, *match_cols])
    return deltas.groupby(date_col)["delta"].mean()


def reality_check_input(working: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """Wide per-date frame of each non-benchmark family's `fwd_ret_21`
    delta minus the benchmark's (`ema`) own same-date delta -- exactly the
    "candidate minus benchmark" shape `white_reality_check` expects.
    """
    per_family = {family: per_date_deltas(working, ABOVE_COLUMNS[family], match_cols) for family in FAMILIES}
    wide = pd.DataFrame(per_family)
    benchmark = wide[BENCHMARK_FAMILY]
    diffs = wide.drop(columns=[BENCHMARK_FAMILY]).sub(benchmark, axis=0)
    return diffs.reset_index()


def run_reality_check(
    working: pd.DataFrame,
    match_cols: tuple[str, ...] = C2_MATCH_COLS,
    block_length: int = 42,
    n_boot: int = 1000,
    seed: int = 0,
) -> dict:
    diffs = reality_check_input(working, match_cols)
    return white_reality_check(diffs, block_length=block_length, n_boot=n_boot, seed=seed)


def evaluate_kill_criterion(reality_check_result: dict) -> dict:
    """DESIGN's own literal kill wording, applied precisely: "if no family
    beats EMA by > 0.1% at matched lag after Reality Check, declare MA
    family selection a non-question." `reality_check_result["p_value"]` is
    the Reality Check's own p-value on the best-of-6 (non-EMA) candidates'
    edge over EMA; `REALITY_CHECK_ALPHA` (0.10) is this study's own
    standard significance convention, reused here rather than inventing a
    second threshold. The module is killed (declared a non-question)
    unless the best candidate's own edge *both* exceeds the 0.10%
    magnitude floor *and* the Reality Check itself rejects the null that
    this is data-snooping luck.
    """
    best_candidate = reality_check_result["best_candidate"]
    best_mean = reality_check_result["candidate_means"][best_candidate]
    exceeds_magnitude = abs(best_mean) > KILL_THRESHOLD
    reality_check_significant = reality_check_result["p_value"] < REALITY_CHECK_ALPHA
    return {
        "best_candidate": best_candidate,
        "best_mean_vs_ema": best_mean,
        "reality_check_p_value": reality_check_result["p_value"],
        "exceeds_magnitude_floor": exceeds_magnitude,
        "reality_check_significant": reality_check_significant,
        "module_killed": not (exceeds_magnitude and reality_check_significant),
    }

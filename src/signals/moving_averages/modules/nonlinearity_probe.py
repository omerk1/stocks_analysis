"""M17 -- Nonlinearity probe: does path composition matter? (DESIGN.md
lines ~867-887; PREREGISTRATION.md, 2026-09-25).

Track B. DESIGN's own framing, restated in this module's own terms: M16
(a sibling Batch-4 module, run in parallel, not sequenced before this one)
establishes that MA rules are linear filters of past returns. That has a
blind spot -- any information carried by the *asymmetry* or *composition*
of a return path, not just its net displacement, is invisible to every
M1-M16 feature. This module tests three distinct mathematical operations
on a return window that no MA feature can represent: gain/loss
decomposition (MACD, M17.1), gain/loss asymmetry (RSI, M17.2), and
rank-within-range (stochastics %K, M17.3) -- DESIGN's own explicit framing
for the report: "a structured test of three distinct mathematical
operations," not "we also tested some oscillators."

**Deferred, not silently dropped**: M17.1's own DESIGN text asks whether
`ppo`/MACD "clusters with the MA-spread features in kernel space" -- that
specific cross-check needs M16's own kernel-clustering output, which does
not exist yet (M16 runs in parallel, in its own worktree, not landed
before this module). Substituted here with a direct per-date median
Spearman correlation against two representative MA-spread features
(`dist_pct_sma_50`, `slope_log_21_sma_50`) against this study's own 0.89
non-redundancy bar -- a proxy for "same cluster," not the kernel-space
comparison DESIGN's own text literally asks for. Revisit once M16 lands.

**Scope simplification, named not hidden**: DESIGN's text says "MACD/PPO"
together. PPO (percentage MACD) would just be MACD normalized by price
level for cross-ticker comparability -- not separately computed here;
MACD's own line/signal/histogram (already comparable in log-return terms
via this study's own `close`-based construction) are used directly for
every M17.1 test.

**"Full MA feature set" control block, a documented scope choice, not
literally every M1-M18 feature (that regression would be badly
multicollinear and uninterpretable)**: `dist_pct_sma_50` (distance),
`slope_log_21_sma_50` (slope), `mom_12_1` (momentum) -- one representative
feature from each of this study's three main MA-derived predictor
families, at the SMA50 lookback this study already uses as its own
frequent "primary" reference (M3's classic pair, M6.2's own focus, M8's
own matched-lag reference).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.feature_sweep import per_date_median_corr
from src.signals.moving_averages.features.oscillators import macd_components, rsi, stochastic_k
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.features.regime import efficiency_ratio
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta, block_bootstrap_series

MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZONS = (21, 63)
INCREMENTAL_IC_FLOOR = 0.005
NONREDUNDANCY_BAR = 0.89
CONTROL_COLS = ("dist_pct_sma_50", "slope_log_21_sma_50", "mom_12_1")
NEW_HIGH_WINDOW = 21
DIVERGENCE_LOOKBACK_DAYS = 126
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds the three oscillator families (lagged, module-local, not
    written to the shared panel), `fwd_ret_{21,63}`, the C2 match buckets,
    and the `is_new_high`/`divergence` flags used by the M17.1 event test.
    Returns a new frame; `panel` itself is not mutated.
    """
    working = panel.sort_values(["ticker", "date"]).reset_index(drop=True).copy()

    macd_lines, signal_lines, histograms, rsis, stoch_ks, ers = [], [], [], [], [], []
    for _, group in working.groupby("ticker", sort=False):
        m_line, m_signal, m_hist = macd_components(group["close"])
        macd_lines.append(m_line)
        signal_lines.append(m_signal)
        histograms.append(m_hist)
        rsis.append(rsi(group["close"]))
        stoch_ks.append(stochastic_k(group["high"], group["low"], group["close"]))
        ers.append(efficiency_ratio(group["close"]))
    working["macd_line_raw"] = pd.concat(macd_lines)
    working["macd_signal_raw"] = pd.concat(signal_lines)
    working["macd_histogram_raw"] = pd.concat(histograms)
    working["rsi_raw"] = pd.concat(rsis)
    working["stochastic_k_raw"] = pd.concat(stoch_ks)
    working["efficiency_ratio_raw"] = pd.concat(ers)
    working["rsi_er_interaction_raw"] = working["rsi_raw"] * working["efficiency_ratio_raw"]

    raw_cols = [
        "macd_line_raw", "macd_signal_raw", "macd_histogram_raw",
        "rsi_raw", "stochastic_k_raw", "efficiency_ratio_raw", "rsi_er_interaction_raw",
    ]
    working = apply_lag(working, raw_cols)
    for col in raw_cols:
        working[col.removesuffix("_raw")] = working[col]
    working["rsi_slope"] = working.groupby("ticker")["rsi"].diff(5)

    for h in HORIZONS:
        working[f"fwd_ret_{h}"] = forward_return(working, horizon=h)

    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)

    working["is_new_high"] = working["close"] >= working.groupby("ticker")["close"].transform(
        lambda s: s.rolling(NEW_HIGH_WINDOW).max()
    )

    def _divergence_for_ticker(group: pd.DataFrame) -> pd.Series:
        result = pd.Series(pd.NA, index=group.index, dtype="boolean")
        highs = group[group["is_new_high"]]
        if len(highs) < 2:
            return result
        hist_diff = highs["macd_histogram"].diff()
        day_gap = highs["date"].diff().dt.days
        eligible = hist_diff.notna() & day_gap.notna() & (day_gap <= DIVERGENCE_LOOKBACK_DAYS)
        flag = (hist_diff < 0) & eligible
        result.loc[flag.index[eligible]] = flag[eligible]
        return result

    working["divergence"] = pd.concat(
        [_divergence_for_ticker(g) for _, g in working.groupby("ticker", sort=False)]
    )

    return working


def _daily_incremental_ic(
    panel: pd.DataFrame, feature_col: str, control_cols: tuple[str, ...], return_col: str,
    date_col: str = "date",
) -> pd.Series:
    """Per-date cross-sectional partial correlation: residualize
    `feature_col` against ALL of `control_cols` via one OLS per date (no
    look-ahead, each date's regression uses only that date's own
    cross-section), then Spearman rank-IC of the residual against
    `return_col`. Generalizes M6.1's own single-control
    `_daily_incremental_ic` to the multi-control "full MA feature set"
    DESIGN's own M17.2 text asks for.
    """
    needed = [feature_col, *control_cols, return_col]

    def _one_date(group: pd.DataFrame) -> float:
        sub = group[needed].dropna()
        if len(sub) < MIN_TICKERS:
            return float("nan")
        x = sub[list(control_cols)].to_numpy()
        y = sub[feature_col].to_numpy()
        design = np.column_stack([np.ones(len(sub)), x])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        resid = pd.Series(y - design @ coef, index=sub.index)
        return resid.corr(sub[return_col], method="spearman")

    return panel.groupby(date_col, sort=False).apply(_one_date, include_groups=False)


def incremental_ic_table(
    panel: pd.DataFrame, feature_col: str, horizons: tuple[int, ...] = HORIZONS,
    control_cols: tuple[str, ...] = CONTROL_COLS,
) -> pd.DataFrame:
    """The decisive test for M17.2/M17.3 (and M17.1's histogram cell):
    per-date partial correlation of `feature_col` (residualized against
    the full `control_cols` MA feature set) with `fwd_ret_{h}`, for every
    horizon -- DESIGN's own kill wording ("at every horizon") makes each
    horizon its own cell, same convention M6.1 used for its own lookback
    grid.
    """
    rows = []
    for h in horizons:
        return_col = f"fwd_ret_{h}"
        ic_series = _daily_incremental_ic(panel, feature_col, control_cols, return_col)
        boot = block_bootstrap_series(ic_series, block_length=42, n_boot=500, ci=0.90, seed=0)
        valid = panel.dropna(subset=[feature_col, *control_cols, return_col])
        n_events, n_tickers = len(valid), valid["ticker"].nunique()
        edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
        rows.append({
            "feature": feature_col, "horizon": h,
            "incremental_ic": boot["point_estimate"], "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
            "n_dates": boot["n_dates"], "n_events": n_events, "n_tickers": n_tickers, "edge": edge,
            "below_threshold": (
                n_events < MIN_EVENTS or boot["n_dates"] < MIN_DATES or n_tickers < MIN_TICKERS
                or pd.isna(edge)
            ),
        })
    return pd.DataFrame(rows)


def kill_verdict(table: pd.DataFrame, floor: float = INCREMENTAL_IC_FLOOR) -> bool:
    """DESIGN's own kill rule for M17.2/M17.3 (and applied to M17.1's
    histogram cell too, DESIGN's own '< 0.005 incremental IC' wording):
    killed iff every row's edge is below `floor`.
    """
    return bool((table["edge"] < floor).all())


def redundancy_correlation_table(panel: pd.DataFrame) -> pd.DataFrame:
    """M17.1's substitute for the deferred kernel-space cross-check (see
    module docstring): per-date median Spearman between `macd_histogram`
    and two representative MA-spread features, against this study's own
    0.89 non-redundancy bar.
    """
    rows = []
    for other in ("dist_pct_sma_50", "slope_log_21_sma_50"):
        corr = per_date_median_corr(panel, "macd_histogram", other)
        rows.append({"pair": f"macd_histogram_vs_{other}", "median_spearman": corr})
    return pd.DataFrame(rows)


def zero_vs_signal_diagnostic(panel: pd.DataFrame) -> dict:
    """Descriptive only (no CI, not counted toward N_tests): does the
    zero-line condition (`macd_line > 0`, a level condition on the spread)
    behave differently from the signal-line condition (`macd_line >
    macd_signal`, an acceleration condition) -- DESIGN's own question,
    "are these empirically distinguishable, or does the second collapse
    into M6's slope work?" Proxied here via each condition's own
    agreement rate with a rising-vs-falling slope read: zero-line vs.
    `slope_log_21_sma_50 > 0` (trend-state), signal-line vs.
    `slope_log_5_sma_50 > 0` (short-horizon acceleration proxy -- the
    5-day slope is this study's own shortest cached slope window).
    """
    valid = panel.dropna(subset=["macd_line", "macd_signal", "slope_log_21_sma_50", "slope_log_5_sma_50"])
    zero_line = valid["macd_line"] > 0
    trend_state = valid["slope_log_21_sma_50"] > 0
    signal_line = valid["macd_line"] > valid["macd_signal"]
    accel_state = valid["slope_log_5_sma_50"] > 0
    return {
        "zero_line_vs_trend_state_agreement": float((zero_line == trend_state).mean()),
        "signal_line_vs_accel_state_agreement": float((signal_line == accel_state).mean()),
        "n_rows": int(len(valid)),
    }


def histogram_divergence_delta(panel: pd.DataFrame) -> dict:
    """M17.1's own decisive event test: among new-`NEW_HIGH_WINDOW`-day-high
    rows with an eligible prior high to compare against, does a bearish
    MACD-histogram divergence (`divergence=True`) predict a different
    `fwd_ret_21` than a non-divergent new high, C2-matched -- the same
    restrict-then-delta construction M3/M6.2 already established.
    """
    population = panel.dropna(subset=["divergence", "fwd_ret_21", *C2_MATCH_COLS])
    population = population[population["is_new_high"]]
    n_events, n_dates, n_tickers = len(population), population["date"].nunique(), population["ticker"].nunique()
    try:
        boot = block_bootstrap_delta(population, "divergence", "fwd_ret_21", match_cols=list(C2_MATCH_COLS))
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "point_estimate": float("nan"), "n_dates": 0}
    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    return {
        "point_estimate": boot["point_estimate"], "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
        "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers, "edge": edge,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(edge)
        ),
    }


def rsi_reverse_correlation(panel: pd.DataFrame) -> float:
    """M17.2's reverse check: how much of RSI's own standalone predictive
    content is already captured by `dist_z` at a "matched" lookback?
    RSI's own period is 14; the closest cached SMA lookback is 20 (this
    study has no 14-day SMA) -- the mismatch is named here, not hidden,
    per-date median Spearman(`rsi`, `dist_z_sma_20`).
    """
    return per_date_median_corr(panel, "rsi", "dist_z_sma_20")


def ambiguous_region_table(panel: pd.DataFrame, horizon: int = 21) -> pd.DataFrame:
    """M17.2's own targeted sub-question: does RSI add signal specifically
    where MA features are ambiguous (price near its own MA, linear
    features silent)? Restricts to the bottom tercile of
    `abs(dist_pct_sma_50)` per date (closest-to-the-MA third) and re-runs
    RSI's own incremental IC there, for direct comparison against the
    unrestricted reading in `incremental_ic_table`.
    """
    working = panel.copy()
    working["_abs_dist"] = working["dist_pct_sma_50"].abs()
    working["_abs_dist_tercile"] = cross_sectional_bucket(working, "_abs_dist", n_buckets=3)
    restricted = working[working["_abs_dist_tercile"] == 0]
    return incremental_ic_table(restricted, "rsi", horizons=(horizon,))

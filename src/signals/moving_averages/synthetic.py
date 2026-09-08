"""Synthetic panel generator for the Phase 1 pipeline-validation gate
(DESIGN.md §10.2 / CLAUDE.md's `validate-synth`). Not used by real
analysis -- exists purely to exercise `features/panel.py`'s lag,
`labels/forward_returns.py`, and `stats/controls.py` against a dataset
with a precisely known ground truth, so a broken lag or a leaked signal
shows up as a specific, checkable number rather than a subtle drift in a
real-data result months later.

Deliberately uses a 5-day SMA, not a folklore lookback like 20/50/200: a
short window flips its above/below state often under a random walk, which
is what makes the look-ahead shift test below actually discriminating (see
`shift_extra_day`'s docstring). Phase 2 golden-fixture tests the real
lookback grid separately -- this module doesn't need to.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c1_delta

SMA_WINDOW = 5
HORIZON = 21
# +3% additive to the 21-day forward return whenever the correctly-lagged
# feature is True -- "by construction," per DESIGN.md §10.2's own phrasing.
PLANT_MAGNITUDE = 0.03

# Phase 1 gate tolerances, shared by the CLI report and the pytest
# assertions (tests/test_moving_averages_synthetic_validation.py) via
# `gate_verdict` below, so the two can't silently diverge.
RECOVERY_TOLERANCE = 0.005        # planted/null recovered deltas must land within this absolute distance of their target
SHIFT_DEGRADATION_RATIO = 0.7     # shifted recovery must fall below this fraction of the correctly-lagged recovery


def _price_panel(n_tickers: int, n_days: int, daily_sigma: float, seed: int) -> pd.DataFrame:
    """iid gaussian daily log-returns per ticker, zero drift -- a pure
    random walk with, by construction, no genuine autocorrelation between
    past state and future return. `above_sma` computed on this baseline is
    therefore an honestly-derived feature with no organic relationship to
    forward returns; any recovered effect beyond noise has to come from
    what's explicitly injected on top.
    """
    rng = np.random.default_rng(seed)
    tickers = [f"SYN{i:04d}" for i in range(n_tickers)]
    dates = pd.bdate_range("2020-01-01", periods=n_days)

    log_returns = rng.normal(0.0, daily_sigma, size=(n_days, n_tickers))
    log_prices = np.cumsum(log_returns, axis=0)
    prices = 100.0 * np.exp(log_prices)

    frame = pd.DataFrame(prices, index=dates, columns=tickers)
    panel = frame.stack().rename("close").rename_axis(["date", "ticker"]).reset_index()
    return panel.sort_values(["ticker", "date"]).reset_index(drop=True)


def build_synthetic_panels(
    n_tickers: int = 300, n_days: int = 300, daily_sigma: float = 0.02, seed: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (planted, null) event panels, each with columns `ticker,
    date, close, above_sma, above_sma_lagged, fwd_ret`. Both share the
    identical underlying price path and feature -- the only difference is
    whether `PLANT_MAGNITUDE` was added to `fwd_ret` conditional on
    `above_sma_lagged`.
    """
    panel = _price_panel(n_tickers, n_days, daily_sigma, seed)
    sma = panel.groupby("ticker")["close"].transform(lambda s: s.rolling(SMA_WINDOW).mean())
    panel["above_sma"] = panel["close"] > sma
    panel["fwd_ret"] = forward_return(panel, horizon=HORIZON)
    panel["above_sma_lagged"] = apply_lag(panel, columns=["above_sma"])["above_sma"]

    null_panel = panel.copy()

    planted_panel = panel.copy()
    plant = PLANT_MAGNITUDE * planted_panel["above_sma_lagged"].fillna(False).astype(float)
    planted_panel["fwd_ret"] = planted_panel["fwd_ret"] + plant

    return planted_panel, null_panel


def shift_extra_day(panel: pd.DataFrame, column: str = "above_sma_lagged") -> pd.Series:
    """The look-ahead shift test (DESIGN.md §7.2): shift `column` forward
    by one MORE day than the correct lag already applied to it. On the
    planted panel, this misaligns the feature from the label it was
    actually keyed to when the effect was injected -- if the recovered
    effect doesn't degrade, the pipeline isn't actually sensitive to
    alignment, which is the bug this test exists to catch. Using a fast
    5-day SMA (see module docstring) means this misalignment changes a
    real fraction of rows' feature value, not a rare edge case.
    """
    return apply_lag(panel, columns=[column])[column]


def run_validation(
    n_tickers: int = 300, n_days: int = 300, daily_sigma: float = 0.02, seed: int = 0
) -> dict[str, float]:
    """Runs all three Phase 1 gate checks against one generated pair of
    panels and returns the raw numbers -- shared by the CLI report and the
    pytest assertions so they can't drift apart.
    """
    planted, null = build_synthetic_panels(n_tickers, n_days, daily_sigma, seed)

    recovered_planted = c1_delta(planted, group_col="above_sma_lagged", value_col="fwd_ret")
    recovered_null = c1_delta(null, group_col="above_sma_lagged", value_col="fwd_ret")

    shifted = planted.assign(above_sma_shifted=shift_extra_day(planted))
    recovered_shifted = c1_delta(shifted, group_col="above_sma_shifted", value_col="fwd_ret")

    return {
        "planted_magnitude": PLANT_MAGNITUDE,
        "recovered_planted": recovered_planted,
        "recovered_null": recovered_null,
        "recovered_shifted": recovered_shifted,
    }


def gate_verdict(results: dict[str, float]) -> dict[str, bool]:
    """The three Phase 1 gate checks (DESIGN.md §10.2), as booleans, from
    `run_validation`'s output. Kept separate from `run_validation` so the
    CLI report and the pytest assertions both call this one function
    rather than each re-deriving the pass/fail logic.
    """
    planted_recovered = abs(results["recovered_planted"] - results["planted_magnitude"]) < RECOVERY_TOLERANCE
    null_reports_nothing = abs(results["recovered_null"]) < RECOVERY_TOLERANCE
    shift_degrades = abs(results["recovered_shifted"]) < abs(results["recovered_planted"]) * SHIFT_DEGRADATION_RATIO
    return {
        "planted_recovered": planted_recovered,
        "null_reports_nothing": null_reports_nothing,
        "shift_degrades": shift_degrades,
    }

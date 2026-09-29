"""Generic leakage test (CLAUDE.md invariants #2 and #3) over the feature panel
and every module's `prepare()`.

Method: build the panel from synthetic bars through the production code path
(`features.panel.assemble_panel`), then rebuild it from the same bars with
every bar from `CUT` onward perturbed -- a large one-day shock on `CUT`
itself (so any same-bar comparison flips) followed by a new random walk.
Every non-label output column at dates <= `CUT` must be identical. A row at
date t may only use information up to close(t-1), so bars at t and later
must not move it. Forward labels (`fwd_*`, `hold_*`) are exempt: they look
forward by definition.

DB-backed inputs (VIX for M13, relative strength for M2) are stubbed with
series computed from the same synthetic bars, so they are perturbed too.
M14's pattern table is a fixed input here; it only exercises the flag logic,
not the pattern detector.
"""

from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import resample as resample_mod
from src.signals.moving_averages.features.panel import apply_lag, assemble_panel
from src.signals.moving_averages.modules import (
    baseline_state,
    context_conditioning,
    cross_sectional,
    crossover_state,
    distance_from_ma,
    high_low_52w,
    kernel_horse_race,
    nonlinearity_probe,
    pattern_context,
    placebo_levels,
    regime_conditional_lookback,
    ribbon_compression,
    ribbon_slope_agreement,
    slope_conditioner,
    slope_magnitude,
    slope_persistence,
    slope_vs_momentum,
    sma_dropoff,
    stack_minervini,
    timeframe_sampling,
    touch_bounce,
    volume_liquidity,
)

N_TICKERS = 9
N_DAYS = 700
CUT = 560
DATES = pd.bdate_range("2012-01-02", periods=N_DAYS)
TICKERS = [f"T{i:02d}" for i in range(N_TICKERS)]
RAW_COLUMNS = {"ticker", "date", "open", "high", "low", "close", "volume"}
LABEL_PATTERN = re.compile(r"^(fwd_|hold_)")
SECTORS = pd.DataFrame({"ticker": TICKERS, "sector": ["tech", "energy", "health"] * (N_TICKERS // 3)})
PATTERNS = pd.DataFrame({
    "ticker": ["T00", "T03", "T05"],
    "formation_end": [DATES[300], DATES[500], DATES[540]],
    "breakout_date": [DATES[305], DATES[505], DATES[548]],
    "pattern_type": "vcp",
})

SINGLE_ARG_MODULES = [
    baseline_state, crossover_state, distance_from_ma, high_low_52w, kernel_horse_race, nonlinearity_probe,
    placebo_levels, regime_conditional_lookback, ribbon_compression, ribbon_slope_agreement, slope_conditioner,
    slope_magnitude, slope_persistence, slope_vs_momentum, sma_dropoff, touch_bounce, volume_liquidity,
]


def _synthetic_bars(seed: int = 0) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    bars = {}
    for i, ticker in enumerate(TICKERS):
        returns = rng.normal(0.0004 * (i - N_TICKERS / 2) / N_TICKERS, 0.014 + 0.001 * i, N_DAYS)
        close = 50 * np.exp(np.cumsum(returns))
        open_ = close * np.exp(rng.normal(0, 0.004, N_DAYS))
        high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.006, N_DAYS)))
        low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.006, N_DAYS)))
        volume = rng.lognormal(14, 0.4, N_DAYS)
        bars[ticker] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=pd.DatetimeIndex(DATES, name="timestamp"),
        )
    return bars


def _perturb_from_cut(bars: dict[str, pd.DataFrame], seed: int = 99) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    out = {}
    for i, (ticker, frame) in enumerate(bars.items()):
        frame = frame.copy()
        after = frame.index >= DATES[CUT]
        n = int(after.sum())
        shock = 0.5 if i % 2 else 2.0
        factor = shock * np.exp(np.cumsum(rng.normal(0.002, 0.03, n)))
        for col in ("open", "high", "low", "close"):
            frame.loc[after, col] = frame.loc[after, col].to_numpy() * factor
        frame.loc[after, "volume"] = frame.loc[after, "volume"].to_numpy() * rng.lognormal(0, 0.5, n)
        out[ticker] = frame
    return out


def _weekly_panel(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    weekly = {
        t: resample_mod.to_weekly(b.assign(is_partial=False)).drop(columns=["is_partial"], errors="ignore")
        for t, b in bars.items()
    }
    return assemble_panel(weekly, SECTORS)


def _vix_stub(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    level = pd.concat([b["close"] for b in bars.values()], axis=1).mean(axis=1)
    return pd.DataFrame({"date": level.index.strftime("%Y-%m-%d"), "value": 20 * level / level.iloc[0]})


def _relative_strength_stub(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = [pd.DataFrame({"ticker": t, "date": b.index, "ret": b["close"].pct_change(63)}) for t, b in bars.items()]
    rs = pd.concat(frames, ignore_index=True)
    rs["rs_rating"] = rs.groupby("date")["ret"].rank(pct=True) * 99
    return rs[["ticker", "date", "rs_rating"]]


def _prepared_outputs(bars: dict[str, pd.DataFrame], monkeypatch) -> dict[str, pd.DataFrame]:
    monkeypatch.setattr(context_conditioning.db, "read_macro_series", lambda conn, series_id: _vix_stub(bars))
    monkeypatch.setattr(stack_minervini, "compute_stock_vs_market", lambda *a, **k: _relative_strength_stub(bars))
    panel = assemble_panel(bars, SECTORS)
    outputs = {"panel": panel}
    for module in SINGLE_ARG_MODULES:
        outputs[module.__name__.rsplit(".", 1)[-1]] = module.prepare(panel)
    outputs["cross_sectional"] = cross_sectional.prepare(panel, horizons=(5, 21))
    outputs["context_conditioning"] = context_conditioning.prepare(panel, conn=None)
    outputs["stack_minervini"] = stack_minervini.prepare(panel, conn=None)
    outputs["pattern_context"] = pattern_context.prepare(panel, PATTERNS)
    daily = timeframe_sampling.prepare_daily(panel)
    outputs["timeframe_sampling_daily"] = daily
    outputs["timeframe_sampling_weekly"] = timeframe_sampling.prepare_weekly(_weekly_panel(bars), daily)
    return outputs


def _leaking_columns(before: pd.DataFrame, after: pd.DataFrame) -> dict[str, int]:
    """Non-label columns whose value at any row dated <= CUT differs."""
    cutoff = DATES[CUT]
    left = before[before["date"] <= cutoff]
    right = after[after["date"] <= cutoff]
    merged = left.merge(right, on=["ticker", "date"], suffixes=("_a", "_b"), validate="one_to_one")
    assert len(merged) == len(left) == len(right), "row set before the cut changed"
    leaks = {}
    for col in left.columns:
        if col in RAW_COLUMNS or LABEL_PATTERN.match(col):
            continue
        a, b = merged[f"{col}_a"], merged[f"{col}_b"]
        try:
            fa = pd.to_numeric(a, errors="raise").astype(float)
            fb = pd.to_numeric(b, errors="raise").astype(float)
            same = (fa.isna() & fb.isna()) | np.isclose(fa, fb, rtol=1e-9, atol=1e-12, equal_nan=True)
        except (TypeError, ValueError):
            same = (a.isna() & b.isna()) | (a.astype(str) == b.astype(str))
        n_diff = int((~same).sum())
        if n_diff:
            leaks[col] = n_diff
    return leaks


@pytest.fixture(scope="module")
def outputs_before_and_after():
    warnings.filterwarnings("ignore")
    mp = pytest.MonkeyPatch()
    bars = _synthetic_bars()
    try:
        before = _prepared_outputs(bars, mp)
        after = _prepared_outputs(_perturb_from_cut(bars), mp)
    finally:
        mp.undo()
    return before, after


OUTPUT_NAMES = (
    ["panel"]
    + [m.__name__.rsplit(".", 1)[-1] for m in SINGLE_ARG_MODULES]
    + ["cross_sectional", "context_conditioning", "stack_minervini", "pattern_context",
       "timeframe_sampling_daily", "timeframe_sampling_weekly"]
)


@pytest.mark.parametrize("name", OUTPUT_NAMES)
def test_features_at_or_before_the_cut_ignore_bars_from_the_cut_onward(outputs_before_and_after, name):
    before, after = outputs_before_and_after
    leaks = _leaking_columns(before[name], after[name])
    assert not leaks, f"{name}: columns use data from date t or later at row t: {leaks}"


def test_perturbation_actually_moves_the_labels(outputs_before_and_after):
    """Guards against a vacuous pass: the forward labels just before the cut
    look across it, so they must change."""
    before, after = outputs_before_and_after
    cutoff = DATES[CUT]
    a = before["baseline_state"].set_index(["ticker", "date"])["fwd_ret_21"]
    b = after["baseline_state"].set_index(["ticker", "date"])["fwd_ret_21"]
    window = a.index.get_level_values("date") < cutoff
    assert not np.allclose(a[window].fillna(0), b[window].fillna(0))


def test_detects_a_planted_same_bar_feature(outputs_before_and_after):
    """A feature comparing today's raw close with a lagged MA must be caught;
    the same comparison against yesterday's close must not."""
    before, after = outputs_before_and_after

    def add(panel: pd.DataFrame) -> pd.DataFrame:
        out = panel.copy()
        out["same_bar"] = (out["close"] > out["sma_20"]).astype("boolean").mask(out["sma_20"].isna())
        prior = apply_lag(out[["ticker", "close"]], ["close"])["close"]
        out["prior_bar"] = (prior > out["sma_20"]).astype("boolean").mask(out["sma_20"].isna() | prior.isna())
        return out

    leaks = _leaking_columns(add(before["panel"]), add(after["panel"]))
    assert "same_bar" in leaks
    assert "prior_bar" not in leaks

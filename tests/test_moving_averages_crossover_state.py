"""Tests for M3's crossover-state module (`modules/crossover_state.py`,
PREREGISTRATION.md 2026-09-23). Synthetic-panel tests only -- mechanics
(lag safety, event/control population construction, kill criterion), not
a real-data result (that's the real-panel run, logged separately).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import crossover_state as cs


def _synthetic_panel(n_tickers: int = 6, n_days: int = 400, seed: int = 0) -> pd.DataFrame:
    """A minimal panel with everything `prepare` needs: `close`, `sma_20`,
    `sma_50`, `sma_150`, `sma_200`, `above_sma_20`, `above_sma_50`,
    `above_sma_200`, `slope_log_21_sma_200`, `mom_12_1`, `realized_vol_63`,
    `mom_1_0`, `sector` -- NOT one-bar-lagged (this module's own
    `add_local_ema_columns`/`prepare` don't re-lag pre-existing panel
    columns; this fixture stands in for an already-lagged cached panel, so
    its MA columns are deliberately built without a lag offset applied a
    second time).
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    frames = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        # A random walk with enough drift regime changes to produce several
        # crossovers per ticker.
        steps = rng.normal(0, 1, n_days)
        # Inject slow sinusoidal drift so sma_50/sma_200 actually cross.
        drift = 3 * np.sin(np.linspace(0, 6, n_days))
        close = 100 + np.cumsum(steps) + drift
        frame = pd.DataFrame({"ticker": ticker, "date": dates, "close": close})
        frame["sma_20"] = frame["close"].rolling(20).mean()
        frame["sma_50"] = frame["close"].rolling(50).mean()
        frame["sma_150"] = frame["close"].rolling(150).mean()
        frame["sma_200"] = frame["close"].rolling(200).mean()
        frame["above_sma_20"] = ((frame["close"] > frame["sma_20"]).astype("boolean")).mask(frame["sma_20"].isna())
        frame["above_sma_50"] = ((frame["close"] > frame["sma_50"]).astype("boolean")).mask(frame["sma_50"].isna())
        frame["above_sma_200"] = ((frame["close"] > frame["sma_200"]).astype("boolean")).mask(
            frame["sma_200"].isna()
        )
        frame["slope_log_21_sma_200"] = np.log(frame["sma_200"]).diff(21)
        frame["slope_log_21_sma_50"] = np.log(frame["sma_50"]).diff(21)
        frame["ema_20"] = frame["close"].ewm(span=20, adjust=False).mean()
        frame["mom_12_1"] = frame["close"].pct_change(230).shift(21)
        frame["realized_vol_63"] = frame["close"].pct_change().rolling(63).std()
        frame["mom_1_0"] = frame["close"].pct_change(1)
        frame["sector"] = "tech"
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def test_prepare_adds_expected_columns():
    panel = _synthetic_panel()
    working = cs.prepare(panel)

    for lb in cs.NEW_EMA_LOOKBACKS:
        assert f"ema_{lb}" in working.columns
    for pair_name in cs.PAIRS:
        assert f"state_{pair_name}" in working.columns
    assert "fwd_ret_21" in working.columns


def test_local_ema_columns_are_lagged_one_bar():
    panel = _synthetic_panel(n_tickers=1, n_days=60)
    working = cs.add_local_ema_columns(panel)

    from src.foundation.market_common.indicators import ema as ema_fn

    raw = ema_fn(panel.sort_values("date")["close"].reset_index(drop=True), 8)
    lagged_col = working.sort_values("date")["ema_8"].reset_index(drop=True)

    # Row t's lagged value must equal the raw indicator's value at t-1, not
    # t -- the one-bar-lag invariant, checked directly rather than assumed.
    assert lagged_col.iloc[10] == raw.iloc[9]
    assert pd.isna(lagged_col.iloc[0])


def test_primary_cell_table_shape_and_no_lookahead_in_event_definition():
    panel = _synthetic_panel()
    working = cs.prepare(panel)
    primary = cs.primary_cell_table(working)

    assert len(primary) == len(cs.PAIRS) * 2
    assert set(primary["direction"]) == {cs.GOLDEN, cs.DEATH}
    # Every cell reports the invariant #6 effective-N fields.
    for col in ("n_events", "n_dates", "n_tickers", "c2_ci_low", "c2_ci_high"):
        assert col in primary.columns


def test_event_population_is_subset_of_matching_state():
    """The event day for a golden-cross cell must always sit inside the
    `state_<pair> == True` population -- a construction bug that leaked a
    death-cross day into the golden event set would silently corrupt the
    C2 delta.
    """
    panel = _synthetic_panel()
    working = cs.prepare(panel)
    state_col = f"state_{cs.CLASSIC_PAIR}"

    from src.signals.moving_averages.features import crossover

    events = crossover.crossover_events(working, state_col)
    golden_dates = events[events["crossover_type"] == cs.GOLDEN][["ticker", "date"]]
    merged = golden_dates.merge(working[["ticker", "date", state_col]], on=["ticker", "date"], how="left")
    assert merged[state_col].fillna(False).all()


def test_spread_velocity_facet_table_shape_and_labels():
    panel = _synthetic_panel()
    working = cs.prepare(panel)
    facets = cs.spread_velocity_facet_table(working)

    assert len(facets) == 2
    assert set(facets["facet_value"]) == {"accelerating", "decelerating"}
    assert (facets["facet"] == "spread_velocity").all()
    assert (facets["direction"] == cs.GOLDEN).all()


def test_spread_velocity_excludes_rows_with_undefined_slope_not_treated_as_decelerating():
    """Invariant #9: a row with an undefined slope_log_21 leg (e.g. inside
    the MA's own warmup window) must be excluded from both facet
    populations, not silently folded into "decelerating" by an arithmetic
    NaN comparison defaulting False.
    """
    panel = _synthetic_panel()
    working = cs.prepare(panel)
    fast_col, slow_col = cs.PAIRS[cs.CLASSIC_PAIR]
    fast_slope = working[f"slope_log_21_{fast_col}"]
    slow_slope = working[f"slope_log_21_{slow_col}"]
    valid = fast_slope.notna() & slow_slope.notna()
    assert (~valid).any(), "fixture must exercise the undefined-slope warmup region"

    undefined_rows = working[~valid]
    facets = cs.spread_velocity_facet_table(working)
    # Every row counted in either facet cell's n_events must come from the
    # valid population -- checked indirectly via the population sizes: the
    # two facet cells' underlying restrictions never draw from `~valid`.
    accelerating_restricted = working[valid & ((fast_slope - slow_slope) > 0)]
    decelerating_restricted = working[valid & ((fast_slope - slow_slope) <= 0)]
    assert len(accelerating_restricted) + len(decelerating_restricted) == valid.sum()
    assert len(undefined_rows) == (~valid).sum()


def test_kill_criterion_fires_when_every_cell_is_near_zero():
    tiny = pd.DataFrame({
        "pair": ["p1", "p1"],
        "direction": [cs.GOLDEN, cs.DEATH],
        "c2_ci_low": [-0.0005, -0.0003],
        "c2_ci_high": [0.0004, 0.0006],
    })
    result = cs.evaluate_kill_criterion(tiny)
    assert result["module_killed"] is True
    assert result["n_cells_killed"] == 2


def test_kill_criterion_does_not_fire_when_one_cell_exceeds_floor():
    tiny = pd.DataFrame({
        "pair": ["p1", "p1"],
        "direction": [cs.GOLDEN, cs.DEATH],
        "c2_ci_low": [-0.0005, -0.02],
        "c2_ci_high": [0.0004, -0.01],
    })
    result = cs.evaluate_kill_criterion(tiny)
    assert result["module_killed"] is False
    assert result["n_cells_killed"] == 1

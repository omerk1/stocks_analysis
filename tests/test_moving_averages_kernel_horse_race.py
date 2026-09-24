"""Tests for M8's kernel horse race module (`modules/kernel_horse_race.py`,
PREREGISTRATION.md 2026-09-24). Synthetic-panel tests only -- mechanics
(family-column construction, one-bar lag safety, NA propagation, the
Reality Check input's shape), not a real-data result (that's the
real-panel run, logged separately).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import kernel_horse_race as khr


def _synthetic_panel(n_tickers: int = 6, n_days: int = 400, seed: int = 0) -> pd.DataFrame:
    """A minimal panel with everything `prepare` needs: `close`, `volume`,
    `sma_50`, `ema_50`, `above_sma_50`, `above_ema_50` (standing in for the
    shared cached panel's own already-lagged columns -- built here without
    a second lag applied, since this fixture represents the panel *after*
    `build_panel`'s own lag has already run), `mom_12_1`, `realized_vol_63`,
    `sector`.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    frames = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        steps = rng.normal(0, 1, n_days)
        close = 100 + np.cumsum(steps)
        volume = rng.uniform(1e5, 1e6, n_days)
        frame = pd.DataFrame({"ticker": ticker, "date": dates, "close": close, "volume": volume})
        sma_50_raw = frame["close"].rolling(50).mean()
        ema_50_raw = frame["close"].ewm(span=50, adjust=False).mean()
        # Simulate the shared panel's own already-applied one-bar lag:
        # shift both the value AND the above-state by one day relative to
        # a same-day comparison, matching `features/panel.py`'s own
        # convention exactly.
        above_sma_raw = (frame["close"] > sma_50_raw).astype("boolean").mask(sma_50_raw.isna())
        above_ema_raw = (frame["close"] > ema_50_raw).astype("boolean").mask(ema_50_raw.isna())
        frame["sma_50"] = sma_50_raw.shift(1)
        frame["ema_50"] = ema_50_raw.shift(1)
        frame["above_sma_50"] = above_sma_raw.shift(1)
        frame["above_ema_50"] = above_ema_raw.shift(1)
        frame["mom_12_1"] = frame["close"].pct_change(230).shift(21)
        frame["realized_vol_63"] = frame["close"].pct_change().rolling(63).std()
        frame["sector"] = "tech"
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def test_add_family_columns_adds_expected_columns():
    panel = _synthetic_panel()
    working = khr.add_family_columns(panel)
    for family in khr.NEW_LOCAL_FAMILIES:
        assert khr.ABOVE_COLUMNS[family] in working.columns


def test_new_local_family_columns_are_lagged_one_bar():
    panel = _synthetic_panel(n_tickers=1, n_days=300)
    working = khr.add_family_columns(panel)

    from src.signals.moving_averages.features import distance, kernels

    raw_close = panel.sort_values("date")["close"].reset_index(drop=True)
    raw_wma = kernels.wma(raw_close, khr.MATCHED_PERIODS["wma"])
    raw_above_wma = distance.above(raw_close, raw_wma)

    lagged_col = working.sort_values("date")["above_wma_matched"].reset_index(drop=True)
    # Row t's lagged state must equal the raw same-day comparison at t-1,
    # not t -- the one-bar-lag invariant, checked directly.
    assert lagged_col.iloc[100] == raw_above_wma.iloc[99]
    assert pd.isna(lagged_col.iloc[0])


def test_above_columns_are_na_during_warmup_not_false():
    # Invariant #9: a family's own warmup window (before its matched
    # window has enough history) must read NA, not silently False.
    panel = _synthetic_panel(n_tickers=1, n_days=60)
    working = khr.add_family_columns(panel)
    assert pd.isna(working["above_dema_matched"].iloc[0])


def test_prepare_adds_expected_columns():
    panel = _synthetic_panel()
    working = khr.prepare(panel)
    assert "fwd_ret_21" in working.columns
    assert "mom_tercile" in working.columns
    assert "vol_tercile" in working.columns


def test_family_table_shape_and_effective_n_fields():
    panel = _synthetic_panel()
    working = khr.prepare(panel)
    table = khr.family_table(working)

    assert len(table) == len(khr.FAMILIES)
    assert set(table["family"]) == set(khr.FAMILIES)
    for col in ("n_events", "n_dates", "n_tickers", "c2_ci_low", "c2_ci_high"):
        assert col in table.columns


def test_reality_check_input_excludes_the_benchmark_family_and_is_relative_to_it():
    panel = _synthetic_panel()
    working = khr.prepare(panel)
    diffs = khr.reality_check_input(working)

    assert khr.BENCHMARK_FAMILY not in diffs.columns
    assert "date" in diffs.columns
    assert set(diffs.columns) == {"date", *[f for f in khr.FAMILIES if f != khr.BENCHMARK_FAMILY]}


def test_evaluate_kill_criterion_fires_when_best_edge_is_tiny():
    result = {"best_candidate": "wma", "candidate_means": {"wma": 0.0002}, "p_value": 0.5}
    verdict = khr.evaluate_kill_criterion(result)
    assert verdict["module_killed"] is True


def test_evaluate_kill_criterion_does_not_fire_when_edge_is_large_and_significant():
    result = {"best_candidate": "wma", "candidate_means": {"wma": 0.005}, "p_value": 0.01}
    verdict = khr.evaluate_kill_criterion(result)
    assert verdict["module_killed"] is False


def test_evaluate_kill_criterion_fires_when_edge_is_large_but_not_significant():
    # Large point estimate alone isn't enough -- Reality Check must also
    # reject the null that this is the best-of-K's own data-snooping luck.
    result = {"best_candidate": "wma", "candidate_means": {"wma": 0.005}, "p_value": 0.5}
    verdict = khr.evaluate_kill_criterion(result)
    assert verdict["module_killed"] is True

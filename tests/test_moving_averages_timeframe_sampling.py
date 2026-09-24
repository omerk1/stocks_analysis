"""Tests for M10's timeframe/sampling module (`modules/timeframe_sampling.py`,
PREREGISTRATION.md 2026-09-24). Synthetic-panel tests only -- mechanics
(lag safety, cell construction, decomposition arithmetic, kill criterion),
not a real-data result (that's the real-panel run, logged separately).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.modules import timeframe_sampling as ts


def _synthetic_daily(n_tickers: int = 6, n_days: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    frames = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        steps = rng.normal(0, 1, n_days)
        close = 100 + np.cumsum(steps)
        frame = pd.DataFrame({"ticker": ticker, "date": dates, "close": close})
        for lb in ts.DAILY_LOOKBACKS:
            frame[f"sma_{lb}"] = frame["close"].rolling(lb).mean()
            frame[f"above_sma_{lb}"] = (
                (frame["close"] > frame[f"sma_{lb}"]).astype("boolean").mask(frame[f"sma_{lb}"].isna())
            )
        frame["mom_12_1"] = frame["close"].pct_change(230).shift(21)
        frame["realized_vol_63"] = frame["close"].pct_change().rolling(63).std()
        frame["sector"] = "tech"
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def _synthetic_weekly(n_tickers: int = 6, n_weeks: int = 120, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-06", periods=n_weeks, freq="W-MON")
    frames = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        steps = rng.normal(0, 1, n_weeks)
        close = 100 + np.cumsum(steps)
        # `build_panel` always joins `sector` regardless of timeframe --
        # included here so `prepare_weekly`'s own controls join (which
        # must NOT also bring in a `sector` column) is exercised the same
        # way the real weekly panel exercises it, not a lucky-fixture pass.
        frames.append(pd.DataFrame({"ticker": ticker, "date": dates, "close": close, "sector": "tech"}))
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def test_prepare_daily_adds_expected_columns():
    panel = _synthetic_daily()
    working = ts.prepare_daily(panel)

    assert "fwd_ret_21" in working.columns
    assert "mom_tercile" in working.columns
    assert "is_friday" in working.columns
    assert working["is_friday"].dtype == bool


def test_prepare_daily_is_friday_matches_calendar_weekday():
    panel = _synthetic_daily(n_tickers=1, n_days=10)
    working = ts.prepare_daily(panel)
    expected = pd.to_datetime(working["date"]).dt.weekday == 4
    assert (working["is_friday"] == expected).all()


def test_prepare_weekly_adds_local_lookbacks_and_lags_them():
    daily = ts.prepare_daily(_synthetic_daily())
    weekly = _synthetic_weekly()
    working = ts.prepare_weekly(weekly, daily)

    for lb in ts.WEEKLY_LOOKBACKS:
        assert f"sma_{lb}" in working.columns
        assert f"above_sma_{lb}" in working.columns
    assert "fwd_ret_4" in working.columns
    assert "mom_tercile" in working.columns  # joined from daily_working


def test_prepare_weekly_does_not_collide_with_its_own_sector_column():
    """Regression: `build_panel` joins `sector` onto both the daily and
    weekly panels independently -- `prepare_weekly`'s controls join must
    not also bring in `daily_working`'s `sector`, which `merge_asof`
    would otherwise resolve by silently renaming both to
    `sector_x`/`sector_y` (found against the real panel).
    """
    daily = ts.prepare_daily(_synthetic_daily())
    weekly = ts.prepare_weekly(_synthetic_weekly(), daily)

    assert "sector" in weekly.columns
    assert "sector_x" not in weekly.columns
    assert "sector_y" not in weekly.columns
    assert (weekly["sector"] == "tech").all()


def test_prepare_weekly_one_bar_lag_is_one_week():
    weekly = _synthetic_weekly(n_tickers=1, n_weeks=60)
    daily = ts.prepare_daily(_synthetic_daily(n_tickers=1, n_days=400))
    working = ts.prepare_weekly(weekly, daily).sort_values("date").reset_index(drop=True)

    raw_sma10 = weekly.sort_values("date")["close"].rolling(10).mean().reset_index(drop=True)
    lagged_sma10 = working["sma_10"].reset_index(drop=True)
    # Row t's lagged value must equal the raw value at t-1, not t.
    assert lagged_sma10.iloc[15] == raw_sma10.iloc[14]
    assert pd.isna(lagged_sma10.iloc[0])


def test_prepare_weekly_above_is_na_during_warmup_not_false():
    """Invariant #9: a row inside the SMA's own warmup window must stay
    NA, not silently read as "not above" by an unguarded `>` comparison.
    """
    weekly = _synthetic_weekly(n_tickers=1, n_weeks=15)
    daily = ts.prepare_daily(_synthetic_daily(n_tickers=1, n_days=400))
    working = ts.prepare_weekly(weekly, daily)

    # sma_40 needs 40 weekly rows; only 15 exist here -- every row's sma_40
    # (and therefore above_sma_40, pre- and post-lag) must be NA throughout.
    assert working["sma_40"].isna().all()
    assert working["above_sma_40"].isna().all()


def test_primary_cell_table_shape():
    daily = ts.prepare_daily(_synthetic_daily())
    weekly = ts.prepare_weekly(_synthetic_weekly(), ts.prepare_daily(_synthetic_daily()))
    primary = ts.primary_cell_table(daily, weekly)

    assert len(primary) == 2 * len(ts.DAILY_LOOKBACKS) + len(ts.WEEKLY_LOOKBACKS)
    assert set(primary["construction"]) == {"a_daily_alldays", "c_daily_fridays_only", "b_weekly_native"}
    for col in ("n_events", "n_dates", "n_tickers", "c2_ci_low", "c2_ci_high"):
        assert col in primary.columns


def test_decomposition_table_computes_gaps_correctly():
    primary = pd.DataFrame([
        {"construction": "a_daily_alldays", "lookback": 50, "c2": 0.01, "c2_ci_low": 0.005, "c2_ci_high": 0.015},
        {"construction": "c_daily_fridays_only", "lookback": 50, "c2": 0.02, "c2_ci_low": 0.01, "c2_ci_high": 0.03},
        {"construction": "b_weekly_native", "lookback": 10, "c2": 0.03, "c2_ci_low": 0.02, "c2_ci_high": 0.04},
        {"construction": "a_daily_alldays", "lookback": 150, "c2": 0.0, "c2_ci_low": -0.005, "c2_ci_high": 0.005},
        {"construction": "c_daily_fridays_only", "lookback": 150, "c2": 0.0, "c2_ci_low": -0.005, "c2_ci_high": 0.005},
        {"construction": "b_weekly_native", "lookback": 30, "c2": 0.0, "c2_ci_low": -0.005, "c2_ci_high": 0.005},
        {"construction": "a_daily_alldays", "lookback": 200, "c2": 0.0, "c2_ci_low": -0.005, "c2_ci_high": 0.005},
        {"construction": "c_daily_fridays_only", "lookback": 200, "c2": 0.0, "c2_ci_low": -0.005, "c2_ci_high": 0.005},
        {"construction": "b_weekly_native", "lookback": 40, "c2": 0.0, "c2_ci_low": -0.005, "c2_ci_high": 0.005},
    ])
    decomposition = ts.decomposition_table(primary)
    row_50 = decomposition[decomposition["daily_lookback"] == 50].iloc[0]

    assert row_50["sampling_frequency_gap_c_minus_a"] == pytest.approx(0.01)
    assert row_50["bar_aggregation_gap_b_minus_c"] == pytest.approx(0.01)
    assert row_50["naive_gap_b_minus_a"] == pytest.approx(0.02)


def test_kill_criterion_fires_when_no_lookback_shows_a_detectable_gap():
    decomposition = pd.DataFrame([
        {"sampling_frequency_gap_c_minus_a": 0.0001, "a_ci": (-0.01, 0.01), "c_ci": (-0.01, 0.01)},
        {"sampling_frequency_gap_c_minus_a": 0.0002, "a_ci": (-0.01, 0.01), "c_ci": (-0.01, 0.01)},
        {"sampling_frequency_gap_c_minus_a": 0.0003, "a_ci": (-0.01, 0.01), "c_ci": (-0.01, 0.01)},
    ])
    result = ts.evaluate_kill_criterion(decomposition)
    assert result["module_killed"] is True
    assert result["n_detectable_sampling_effect"] == 0


def test_kill_criterion_does_not_fire_when_one_lookback_shows_a_clear_gap():
    decomposition = pd.DataFrame([
        {"sampling_frequency_gap_c_minus_a": 0.02, "a_ci": (0.09, 0.11), "c_ci": (-0.01, 0.01)},
        {"sampling_frequency_gap_c_minus_a": 0.0002, "a_ci": (-0.01, 0.01), "c_ci": (-0.01, 0.01)},
        {"sampling_frequency_gap_c_minus_a": 0.0003, "a_ci": (-0.01, 0.01), "c_ci": (-0.01, 0.01)},
    ])
    result = ts.evaluate_kill_criterion(decomposition)
    assert result["module_killed"] is False
    assert result["n_detectable_sampling_effect"] == 1

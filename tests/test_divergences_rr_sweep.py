"""Walker semantics for the Track-A R/R sweep
(src/analysis/divergence_rr_sweep.py): entry lag, stop/target fills with
gaps, same-bar tie, censoring vs delisting-terminal, invalid/degenerate R,
fail-closed data_end, and the cost-in-R conversion. Synthetic bars with a
constant true range so ATR is exact."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.divergence_rr_sweep import (
    COST_RT_PRIMARY,
    net_returns,
    variant_names,
    variant_spec,
    walk_ticker,
)

DATA_END = "2015-12-31"


def make_bars(n: int = 100, start: str = "2015-01-02") -> pd.DataFrame:
    """Flat synthetic series: open/close 100, high 101, low 99 -> true
    range 2 every bar, so ATR(14) == 2 exactly after warmup."""
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}, index=idx
    )


def trade(direction: str, p1: float, p2: float, conf_pos: int, bars: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "confirmed_at": [bars.index[conf_pos].isoformat()],
            "direction": [direction],
            "p1_price": [p1],
            "p2_price": [p2],
        }
    )


CONF = 30  # bar position of confirmation; far past ATR warmup


def walk_one(bars, trades, delisted=False, data_end=DATA_END):
    return walk_ticker(bars, trades, delisted, data_end).iloc[0]


def test_entry_is_next_bar_open_one_bar_lag():
    bars = make_bars()
    bars.iloc[CONF + 1, bars.columns.get_loc("open")] = 102.0
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    assert out["entry_date"] == bars.index[CONF + 1]
    assert out["entry"] == 102.0


def test_bullish_stop_and_R_from_pair_extreme_plus_epsilon():
    bars = make_bars()
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    # min(p1, p2) = 95, eps 0.25 * ATR 2 = 0.5 below -> 94.5; R = 100 - 94.5.
    assert out["stop"] == pytest.approx(94.5)
    assert out["R"] == pytest.approx(5.5)
    assert out["risk_frac"] == pytest.approx(5.5 / 100.0)


def test_time_exit_when_nothing_hits():
    bars = make_bars()
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    assert out["res_tX_h21"] == "time"
    assert out["bars_tX_h21"] == 21
    # exit at close 100 == entry -> 0 R gross
    assert out["ret_R_tX_h21"] == pytest.approx(0.0)


def test_target_hit_fills_at_target():
    bars = make_bars()
    bars.iloc[CONF + 3, bars.columns.get_loc("high")] = 106.0  # > 100 + 1R (105.5)
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    assert out["res_t1_h21"] == "target"
    assert out["ret_R_t1_h21"] == pytest.approx(1.0)
    assert out["bars_t1_h21"] == 3  # entry bar is held bar 1
    # 2R target (111) not reached -> that variant times out
    assert out["res_t2_h21"] == "time"


def test_stop_hit_fills_at_stop_for_minus_one_R():
    bars = make_bars()
    bars.iloc[CONF + 4, bars.columns.get_loc("low")] = 94.0  # through 94.5
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    assert out["res_t1_h21"] == "stop"
    assert out["ret_R_t1_h21"] == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_open_worse_than_minus_one_R():
    bars = make_bars()
    loc = {c: bars.columns.get_loc(c) for c in ("open", "high", "low", "close")}
    bars.iloc[CONF + 4, loc["open"]] = 90.0
    bars.iloc[CONF + 4, loc["low"]] = 89.0
    bars.iloc[CONF + 4, loc["high"]] = 91.0
    bars.iloc[CONF + 4, loc["close"]] = 90.5
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    assert out["res_t1_h21"] == "stop"
    assert out["ret_R_t1_h21"] == pytest.approx((90.0 - 100.0) / 5.5)


def test_same_bar_target_and_stop_resolves_to_stop():
    bars = make_bars()
    loc = {c: bars.columns.get_loc(c) for c in ("high", "low")}
    bars.iloc[CONF + 2, loc["high"]] = 106.0  # covers the 1R target
    bars.iloc[CONF + 2, loc["low"]] = 94.0    # and the stop; open 100 between
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    assert out["res_t1_h21"] == "stop"
    assert out["ret_R_t1_h21"] == pytest.approx(-1.0)


def test_bearish_mirrors():
    bars = make_bars()
    bars.iloc[CONF + 5, bars.columns.get_loc("low")] = 94.0  # 1R target = 94.5
    out = walk_one(bars, trade("bearish", 104.0, 105.0, CONF, bars))
    # max(p1, p2) = 105, stop 105.5, R = 5.5, short from 100
    assert out["stop"] == pytest.approx(105.5)
    assert out["R"] == pytest.approx(5.5)
    assert out["res_t1_h21"] == "target"
    assert out["ret_R_t1_h21"] == pytest.approx(1.0)


def test_incomplete_window_on_live_ticker_is_censored_even_with_early_hit():
    # Series ends at data_end with fewer than 21 bars after entry; the 1R
    # target is hit on the second held bar -- still censored (keeping only
    # early hits would bias hit rates near the boundary; barriers.py rule).
    bars = make_bars(n=CONF + 11)
    bars.iloc[CONF + 2, bars.columns.get_loc("high")] = 106.0
    data_end = bars.index[-1].isoformat()
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars), delisted=False, data_end=data_end)
    assert out["res_t1_h21"] == "censored"
    assert np.isnan(out["ret_R_t1_h21"])


def test_delisted_ticker_resolves_terminal_return():
    bars = make_bars(n=CONF + 11)  # ends ~June, data_end December
    bars.iloc[-1, bars.columns.get_loc("close")] = 97.0
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars), delisted=True)
    assert out["res_t1_h21"] == "delisted"
    assert out["ret_R_t1_h21"] == pytest.approx((97.0 - 100.0) / 5.5)
    # ... and a pre-delisting hit still resolves normally
    bars2 = bars.copy()
    bars2.iloc[CONF + 2, bars2.columns.get_loc("high")] = 106.0
    out2 = walk_one(bars2, trade("bullish", 95.0, 96.0, CONF, bars2), delisted=True)
    assert out2["res_t1_h21"] == "target"


def test_delisted_inference_when_flag_unknown():
    bars = make_bars(n=CONF + 11)  # last bar months before data_end
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars), delisted=None)
    assert out["res_t1_h21"] == "delisted"


def test_entry_beyond_stop_is_invalid():
    bars = make_bars()
    # Bullish with the pair extreme far above the entry: stop > entry, R <= 0.
    out = walk_one(bars, trade("bullish", 120.0, 119.0, CONF, bars))
    assert out["res_t2_h63"] == "invalid"
    assert np.isnan(out["ret_R_t2_h63"])


def test_tiny_R_is_degenerate():
    bars = make_bars()
    # stop = 100.4 - 0.5 = 99.9 -> R = 0.1 < 0.1 * ATR(2) = 0.2
    out = walk_one(bars, trade("bullish", 100.4, 100.45, CONF, bars))
    assert out["res_t2_h63"] == "degenerate"


def test_data_end_is_fail_closed():
    # Bars extend past data_end; a window that would resolve there censors.
    bars = make_bars(n=200)
    data_end = bars.index[CONF + 10].isoformat()
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars), delisted=False, data_end=data_end)
    assert out["res_t1_h21"] == "censored"


def test_confirmation_after_last_bar_never_enters():
    bars = make_bars(n=CONF + 1)
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    assert out["res_t2_h63"] == "never_entered"


def test_epsilon_sensitivity_variants_change_the_stop():
    bars = make_bars()
    bars.iloc[CONF + 4, bars.columns.get_loc("low")] = 94.9  # between eps .10 (94.8) and .50 (94.0) stops... hits 95.2?
    # eps 0.10 -> stop 94.8 (not hit by low 94.9); eps 0.50 -> stop 94.0 (not hit);
    # primary eps 0.25 -> stop 94.5 (not hit). Use low 94.7: hits only eps 0.10.
    bars.iloc[CONF + 4, bars.columns.get_loc("low")] = 94.7
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    assert out["res_e10_t2_h63"] == "stop"
    assert out["res_t2_h63"] == "time"
    assert out["res_e50_t2_h63"] == "time"


def test_net_returns_cost_in_R_units():
    frame = pd.DataFrame({"ret_R_t2_h63": [1.0], "risk_frac": [0.05]})
    net = net_returns(frame, "t2_h63", COST_RT_PRIMARY)
    # 20 bps on the entry notional = 0.002 / 0.05 = 0.04 R
    assert net.iloc[0] == pytest.approx(1.0 - 0.04)


def test_net_returns_eps_variant_uses_its_own_risk_fraction():
    frame = pd.DataFrame(
        {"ret_R_e10_t2_h63": [1.0], "risk_frac": [0.05], "risk_frac_e10": [0.04]}
    )
    net = net_returns(frame, "e10_t2_h63", COST_RT_PRIMARY)
    assert net.iloc[0] == pytest.approx(1.0 - 0.002 / 0.04)


def test_walker_emits_eps_risk_fractions():
    bars = make_bars()
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    # eps 0.10 -> stop 94.8 -> R 5.2; eps 0.50 -> stop 94.0 -> R 6.0
    assert out["risk_frac_e10"] == pytest.approx(5.2 / 100.0)
    assert out["risk_frac_e50"] == pytest.approx(6.0 / 100.0)


def test_variant_names_round_trip():
    for v in variant_names():
        mult, hold, eps = variant_spec(v)
        assert hold in (21, 63)
        assert mult in (1.0, 2.0, 3.0, None)
        assert eps in (0.25, 0.10, 0.50)

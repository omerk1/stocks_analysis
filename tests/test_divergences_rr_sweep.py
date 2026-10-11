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
    add_bins,
    control_form,
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


def test_same_bar_open_gapped_through_target_decides_target():
    # barriers.py's same-bar refinement: an open already beyond one barrier
    # decides that barrier; only a genuinely undecidable bar goes to the stop.
    bars = make_bars()
    loc = {c: bars.columns.get_loc(c) for c in ("open", "high", "low", "close")}
    bars.iloc[CONF + 2, loc["open"]] = 107.0  # gapped above the 1R target 105.5
    bars.iloc[CONF + 2, loc["high"]] = 108.0
    bars.iloc[CONF + 2, loc["low"]] = 94.0    # the bar also covers the stop
    bars.iloc[CONF + 2, loc["close"]] = 100.0
    out = walk_one(bars, trade("bullish", 95.0, 96.0, CONF, bars))
    assert out["res_t1_h21"] == "target"
    assert out["ret_R_t1_h21"] == pytest.approx((107.0 - 100.0) / 5.5)  # fill at the open


def test_dur_bin_preserves_na_and_bins_fixed_edges():
    frame = pd.DataFrame({
        "dur": [10.0, 30.0, 60.0, np.nan],
        "form": "regular", "indicator": "rsi", "direction": "bearish",
        "strength": [0.1, 0.5, 0.9, 0.5],
        "is_divergence": True,
    })
    out = add_bins(frame)
    assert list(out["dur_bin"][:3]) == [1.0, 2.0, 3.0]
    assert np.isnan(out["dur_bin"].iloc[3])  # invariant #9: NaN never lands in a bin
    assert np.isnan(out.loc[3, "strength_t"]) or out.loc[3, "strength_t"] in (1.0, 2.0, 3.0)


def test_control_form_preserves_na_geometry():
    geom = pd.Series([1, 0, None], dtype="object")
    form = control_form(geom)
    assert list(form[:2]) == ["regular", "hidden"]
    assert pd.isna(form.iloc[2])  # invariant #9: NULL geometry is not "hidden"


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


@pytest.mark.parametrize("list_sources", [False, True], ids=["probe", "source_listing"])
def test_walk_sources_routes_fallback_tickers_and_drops_flagged(monkeypatch, list_sources):
    """The walk reads each ticker on its detected vendor: a Tiingo-only
    (delisted) ticker gets its Tiingo source, never an empty primary read;
    whole-history-disputed and vendor-stale tickers are dropped and counted
    by events/controls."""
    import json

    from src.analysis.divergence_rr_sweep import walk_sources
    from src.foundation.data_processing import db
    from src.foundation.market_common import derived_db, price_disputes
    from src.foundation.market_common.price_basis import PriceBasis
    from src.foundation.market_common.price_disputes import DisputedDay

    from src.signals.divergences import store

    monkeypatch.setattr(price_disputes, "DISPUTED_DAYS",
                        (DisputedDay("BAD", None, "yfinance", "synthetic"),))
    listed = []
    real_members = store.source_members
    monkeypatch.setattr(store, "source_members",
                        lambda *a, **k: listed.append(1) or real_members(*a, **k))
    if list_sources:  # the production path: thousands of tickers -> list each source once
        monkeypatch.setattr(store, "MEMBERS_THRESHOLD", 0)
    raw = db.get_connection(":memory:")
    db.create_tables(raw)
    bars = make_bars(5).assign(volume=1000, is_partial=0)
    bars.index.name = "timestamp"
    db.upsert_bars(raw, "bars_1d", "LIVE", db.YFINANCE_SPLIT_ONLY, bars)
    db.upsert_bars(raw, "bars_1d", "GONE", db.TIINGO_SPLIT_ONLY, bars)
    db.upsert_bars(raw, "bars_1d", "BAD", db.YFINANCE_SPLIT_ONLY, bars)
    db.upsert_bars(raw, "bars_1d", "STALE", db.TIINGO_SPLIT_ONLY, bars)
    db.upsert_bars(raw, "bars_1d", "LEGACY", db.YFINANCE_SPLIT_ONLY, bars)
    db.upsert_bars(raw, "bars_1d", "OLDTIINGO", db.TIINGO_SPLIT_ONLY, bars)
    derived = db.get_connection(":memory:")
    derived_db.create_runs_table(derived)
    for t, src in (("LIVE", db.YFINANCE_SPLIT_ONLY), ("GONE", db.TIINGO_SPLIT_ONLY),
                   ("BAD", db.YFINANCE_SPLIT_ONLY), ("STALE", db.YFINANCE_SPLIT_ONLY)):
        derived_db.record_run(derived, "divergences", t, "daily", None,
                              json.dumps({"bar_source": src}), 0, False)
    # Legacy runs (no bar_source recorded) count as the primary vendor: kept
    # if it still resolves there, vendor-stale if it now resolves elsewhere.
    for t in ("LEGACY", "OLDTIINGO"):
        derived_db.record_run(derived, "divergences", t, "daily", None, json.dumps({}), 0, False)
    frame = pd.DataFrame({
        "ticker": ["LIVE", "GONE", "BAD", "BAD", "STALE", "LEGACY", "OLDTIINGO"],
        "is_divergence": [True, True, True, False, False, True, True],
    })
    kept, sources, dropped = walk_sources(raw, derived, frame, PriceBasis.TRADED)
    assert sorted(kept["ticker"]) == ["GONE", "LEGACY", "LIVE"]
    assert sources["GONE"] == db.TIINGO_SPLIT_ONLY
    assert sources["LIVE"] == db.YFINANCE_SPLIT_ONLY
    assert sources["LEGACY"] == db.YFINANCE_SPLIT_ONLY
    assert dropped == {"unresolved": (1, 1, 1), "vendor_stale": (1, 1, 2)}
    assert bool(listed) == list_sources  # the path under test actually ran

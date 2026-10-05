"""Context scalars (exact values on hand-built geometry, NaN discipline,
calendar-drift skips) and PIT confluence re-clustering."""

import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common import indicators
from src.signals.divergences.context import (
    IMPULSE_LOOKBACK_BARS,
    compute_context_for_ticker,
    pit_confluence,
)


def _bars(closes: list[float], start: str = "2018-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=idx,
    )


def _event(bars: pd.DataFrame, i1: int, i2: int, direction: str, **overrides) -> dict:
    ev = {
        "id": f"ev-{i1}-{i2}-{direction}",
        "ticker": "TST",
        "timeframe": "daily",
        "indicator": "rsi",
        "direction": direction,
        "form": "regular",
        "p1_date": bars.index[i1].isoformat(),
        "p2_date": bars.index[i2].isoformat(),
        "confirmed_at": bars.index[min(i2 + 2, len(bars) - 1)].isoformat(),
    }
    ev.update(overrides)
    return ev


# Impulse: 64 bars rising 50 -> 100 (p1 at index 63); retrace to 80 over 5
# bars; leg 2 back up to 95 over 5 bars (p2 at index 73).
_IMPULSE = list(np.linspace(50.0, 100.0, 64))
_BEARISH_CLOSES = _IMPULSE + [96.0, 92.0, 88.0, 84.0, 80.0, 83.0, 86.0, 89.0, 92.0, 95.0]
_I1, _I2 = 63, 73


def test_bearish_pair_scalars_match_hand_computed_geometry():
    bars = _bars(_BEARISH_CLOSES)
    atr = indicators.atr(bars, 14)
    events = pd.DataFrame([_event(bars, _I1, _I2, "bearish")])

    rows = compute_context_for_ticker(bars, events, atr)

    assert len(rows) == 1
    r = rows[0]
    assert r["impulse_gain_pct"] == pytest.approx((100 - 50) / 50)
    assert r["interpeak_retrace_pct"] == pytest.approx(20 / 100)
    assert r["interpeak_retrace_frac"] == pytest.approx(20 / 50)
    assert r["leg2_gain_pct"] == pytest.approx((95 - 80) / 80)
    assert r["leg2_bars"] == 5
    assert r["atr_contraction"] is not None and r["atr_contraction"] > 0


def test_bullish_pair_mirrors_the_bearish_geometry():
    closes = [200.0 - c for c in _BEARISH_CLOSES]  # decline into p1, bounce, retest down
    bars = _bars(closes)
    atr = indicators.atr(bars, 14)
    events = pd.DataFrame([_event(bars, _I1, _I2, "bullish")])

    rows = compute_context_for_ticker(bars, events, atr)

    assert len(rows) == 1
    r = rows[0]
    # Impulse window max = 150 (200-50), p1 close = 100 -> (150-100)/150.
    assert r["impulse_gain_pct"] == pytest.approx(50 / 150)
    # Interpeak bounce to 120 (200-80): retrace 20 off p1's 100.
    assert r["interpeak_retrace_pct"] == pytest.approx(20 / 100)
    assert r["interpeak_retrace_frac"] == pytest.approx(20 / 50)
    # Leg 2: from the 120 bounce down to p2's 105 -> (120-105)/120.
    assert r["leg2_gain_pct"] == pytest.approx(15 / 120)
    assert r["leg2_bars"] == 5


def test_insufficient_impulse_lookback_yields_nan_not_a_shorter_window():
    # p1 at bar 10 << IMPULSE_LOOKBACK_BARS: impulse scalars (and the
    # retrace fraction that divides by the impulse) must be None, while
    # the purely-between-the-pivots scalars still compute.
    closes = [100.0] * 10 + [100.0, 96.0, 92.0, 88.0, 84.0, 80.0, 83.0, 86.0, 89.0, 92.0, 95.0]
    bars = _bars(closes)
    atr = indicators.atr(bars, 5)
    events = pd.DataFrame([_event(bars, 10, 20, "bearish")])

    rows = compute_context_for_ticker(bars, events, atr)

    assert len(rows) == 1
    r = rows[0]
    assert r["impulse_gain_pct"] is None
    assert r["interpeak_retrace_frac"] is None
    assert r["interpeak_retrace_pct"] == pytest.approx(20 / 100)
    assert r["leg2_gain_pct"] == pytest.approx(15 / 80)
    assert IMPULSE_LOOKBACK_BARS > 10  # the premise of this fixture


def test_event_dates_missing_from_bars_are_skipped():
    bars = _bars(_BEARISH_CLOSES)
    atr = indicators.atr(bars, 14)
    stale = _event(bars, _I1, _I2, "bearish")
    stale["p2_date"] = "1999-01-04T00:00:00"  # predates the bars index entirely

    rows = compute_context_for_ticker(bars, pd.DataFrame([stale]), atr)

    assert rows == []


# ---- pit_confluence ----


def _conf_event(i: int, bar_index: pd.DatetimeIndex, indicator: str, pos: int, form: str = "regular") -> dict:
    return {
        "id": f"c{i}",
        "indicator": indicator,
        "direction": "bearish",
        "form": form,
        "p2_date": bar_index[pos].isoformat(),
    }


def test_pit_confluence_matches_apply_confluence_semantics():
    bar_index = pd.bdate_range("2020-01-01", periods=60)
    events = pd.DataFrame(
        [
            _conf_event(0, bar_index, "rsi", 20),           # clusters with the next row
            _conf_event(1, bar_index, "macd_hist", 21),
            _conf_event(2, bar_index, "obv", 21, form="hidden"),  # same bar, other form: alone
            _conf_event(3, bar_index, "macd_hist", 30),     # beyond the window: alone
        ]
    )

    counts = pit_confluence(events, bar_index, pairing_window=3)

    assert counts.tolist() == [2, 2, 1, 1]


def test_pit_confluence_counts_distinct_indicators_not_rows():
    # Two chained same-indicator rows in one cluster corroborate nothing:
    # distinct-indicator count stays 1 (same as _flush_confluence_cluster's
    # set-of-indicators semantics).
    bar_index = pd.bdate_range("2020-01-01", periods=60)
    events = pd.DataFrame(
        [
            _conf_event(0, bar_index, "rsi", 20),
            _conf_event(1, bar_index, "rsi", 22),
        ]
    )

    counts = pit_confluence(events, bar_index, pairing_window=3)

    assert counts.tolist() == [1, 1]


def test_pit_confluence_empty_frame_returns_empty():
    bar_index = pd.bdate_range("2020-01-01", periods=10)
    counts = pit_confluence(pd.DataFrame(columns=["indicator", "direction", "form", "p2_date"]), bar_index)
    assert counts.empty

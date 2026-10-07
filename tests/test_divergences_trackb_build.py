"""Track-B build prerequisites: control-pair extraction, forward returns,
matching + balance report (PREREGISTRATION.md "Prerequisites")."""

import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common import derived_db, indicators
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.context import (
    compute_context_for_ticker,
    create_context_table,
)
from src.signals.divergences.controls import extract_pairs_for_ticker, flag_divergences
from src.signals.divergences.forward_returns import compute_forward_returns
from src.signals.divergences.matching import (
    balance_report,
    classify_context,
    match_controls,
)


def _bars(closes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
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


def _config(**overrides) -> DivergenceConfig:
    cfg = DivergenceConfig(atr_period=3, min_bars=0, warmup_bars=5, min_pivot_span_bars=5)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


# Price highs at bar 6 and 16; higher-high variant (120 -> 130) and
# lower-high variant (130 -> 120), same shapes the divergence test
# fixtures use.
_HH_CLOSES = [100, 101, 102, 103, 104, 105, 120, 115, 110, 105, 100, 95, 90, 100, 110, 120, 130, 125, 115, 105, 95, 90, 85, 80]
_LH_CLOSES = [100, 101, 102, 103, 104, 105, 130, 115, 110, 105, 100, 95, 90, 96, 102, 110, 120, 112, 104, 96, 90, 85, 80, 75]


# ---- control-pair extraction ----


def test_higher_high_pair_extracted_with_regular_geometry():
    bars = _bars(_HH_CLOSES)
    pairs = extract_pairs_for_ticker(bars, _config(), "TST")

    bearish = pairs[pairs["direction"] == "bearish"]
    assert len(bearish) == 1
    row = bearish.iloc[0]
    assert (row["p1_price"], row["p2_price"]) == (120.0, 130.0)
    assert row["regular_geometry"] == 1
    assert row["span_bars"] == 10
    # Price-only confirmation: strictly after p2's own bar (a bar can
    # never confirm its own pivot).
    assert pd.Timestamp(row["confirmed_at"]) > pd.Timestamp(row["p2_date"])
    # The initial rise also confirms a LOW at the sliced series' first bar
    # (105), pairing with the interior low (90): a legitimate lower-low
    # bullish pair. (The divergence tests never surface it because it
    # would also need paired indicator pivots.)
    bullish = pairs[pairs["direction"] == "bullish"]
    assert len(bullish) == 1
    assert (bullish.iloc[0]["p1_price"], bullish.iloc[0]["p2_price"]) == (105.0, 90.0)
    assert bullish.iloc[0]["regular_geometry"] == 1


def test_lower_high_pair_extracted_with_regular_geometry_zero():
    bars = _bars(_LH_CLOSES)
    pairs = extract_pairs_for_ticker(bars, _config(), "TST")

    bearish = pairs[pairs["direction"] == "bearish"]
    assert len(bearish) == 1
    assert bearish.iloc[0]["regular_geometry"] == 0  # 120 < 130: not a higher high


def test_flag_divergences_uses_bar_distance_on_the_ticker_calendar():
    bar_index = pd.bdate_range("2020-01-01", periods=60)
    pairs = pd.DataFrame(
        [
            {"p2_date": bar_index[20].isoformat()},
            {"p2_date": bar_index[40].isoformat()},
        ]
    )
    stored = pd.DatetimeIndex(
        [bar_index[22], bar_index[46], pd.Timestamp("1999-01-04")]  # 2 bars; 6 bars; off-calendar
    )

    flagged = flag_divergences(pairs, stored, bar_index)

    assert flagged.iloc[0]["has_divergence"] == 1
    assert flagged.iloc[0]["nearest_divergence_bars"] == 2
    assert flagged.iloc[1]["has_divergence"] == 0  # 6 bars > DIVERGENCE_MATCH_BARS
    assert flagged.iloc[1]["nearest_divergence_bars"] == 6


def test_context_rows_now_carry_realized_vol_63_with_nan_discipline():
    # 64-bar impulse + 10 more bars: p2 at bar 73 has a full 63-return
    # window (vol defined); a p2 at bar 20 does not (vol None).
    closes = list(np.linspace(50.0, 100.0, 64)) + [96.0, 92.0, 88.0, 84.0, 80.0, 83.0, 86.0, 89.0, 92.0, 95.0]
    bars = _bars(closes)
    atr = indicators.atr(bars, 14)
    events = pd.DataFrame(
        [
            {
                "id": "long", "ticker": "T", "timeframe": "daily", "indicator": "rsi",
                "direction": "bearish", "form": "regular",
                "p1_date": bars.index[63].isoformat(), "p2_date": bars.index[73].isoformat(),
                "confirmed_at": bars.index[73].isoformat(),
            },
            {
                "id": "short", "ticker": "T", "timeframe": "daily", "indicator": "rsi",
                "direction": "bearish", "form": "regular",
                "p1_date": bars.index[10].isoformat(), "p2_date": bars.index[20].isoformat(),
                "confirmed_at": bars.index[20].isoformat(),
            },
        ]
    )

    rows = {r["divergence_id"]: r for r in compute_context_for_ticker(bars, events, atr)}

    assert rows["long"]["realized_vol_63"] is not None and rows["long"]["realized_vol_63"] > 0
    assert rows["short"]["realized_vol_63"] is None


def test_context_table_migration_adds_realized_vol_63():
    conn = derived_db.get_connection(":memory:")
    conn.execute(
        """
        CREATE TABLE divergence_context (
            divergence_id TEXT PRIMARY KEY,
            ticker TEXT, timeframe TEXT, p2_date TEXT, confirmed_at TEXT,
            impulse_gain_pct REAL, interpeak_retrace_pct REAL,
            interpeak_retrace_frac REAL, leg2_gain_pct REAL,
            leg2_bars INTEGER, atr_contraction REAL, run_id TEXT
        );
        """
    )
    create_context_table(conn)
    have = {row[1] for row in conn.execute("PRAGMA table_info(divergence_context)")}
    assert "realized_vol_63" in have
    conn.close()


# ---- forward returns ----


def test_forward_returns_exact_values_and_one_bar_lag():
    closes = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 116.0, 118.0]
    bars = _bars(closes)
    bars["open"] = [c - 1.0 for c in closes]  # distinct opens so entry uses OPEN
    confirmed = pd.Series([bars.index[2].isoformat()])

    out = compute_forward_returns(bars, confirmed, horizons=(2,))

    row = out.iloc[0]
    assert row["entry_date"] == bars.index[3].isoformat()  # first bar AFTER confirmation
    assert row["entry_price"] == 105.0  # open of entry bar
    # h=2: entry bar is held bar 1, exit at close of bar index 4.
    assert row["fwd_log_ret_2"] == pytest.approx(np.log(108.0 / 105.0))
    assert not row["truncated_2"]  # numpy bool: truthiness, not identity


def test_forward_returns_delisting_truncation_and_last_bar_entry():
    closes = [100.0, 90.0, 80.0, 40.0, 10.0]
    bars = _bars(closes)
    confirmed = pd.Series([bars.index[1].isoformat(), bars.index[4].isoformat()])

    out = compute_forward_returns(bars, confirmed, horizons=(21,))

    # Entry at open of bar 2; series ends at bar 4 -> return to the final
    # close, flagged truncated: the delisting terminal return is KEPT.
    row = out.iloc[0]
    assert row["truncated_21"]
    assert row["fwd_log_ret_21"] == pytest.approx(np.log(10.0 / bars["open"].iloc[2]))
    # Confirmed on the data's last bar: no bar to enter on. (pandas
    # coerces None to NaN in float columns -- test for missing, not None.)
    assert pd.isna(out.iloc[1]["entry_price"])
    assert pd.isna(out.iloc[1]["fwd_log_ret_21"])


# ---- matching ----


def test_classify_context_poles_buffer_and_nan():
    assert classify_context(0.20, 2) == "extension"
    assert classify_context(0.40, 6) == "pullback_rebuild"
    assert classify_context(0.40, 3) is None  # deep-fast
    assert classify_context(0.29, 10) is None  # buffer band
    assert classify_context(float("nan"), 6) is None


def _frame(rows: list[dict]) -> pd.DataFrame:
    base = {
        "direction": "bearish", "context_class": "pullback_rebuild", "p2_month": "2015-03",
        "interpeak_retrace_frac": 0.5, "leg2_bars": 8,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def test_match_controls_nearest_without_replacement_and_deterministic():
    events = _frame(
        [
            {"id": "e1", "impulse_gain_pct": 0.50, "realized_vol_63": 0.020},
            {"id": "e2", "impulse_gain_pct": 0.52, "realized_vol_63": 0.020},
        ]
    )
    controls = _frame(
        [
            {"id": f"c{i}", "impulse_gain_pct": g, "realized_vol_63": 0.020}
            for i, g in enumerate([0.49, 0.51, 0.53, 0.55, 0.57], start=1)
        ]
        + [{"id": "other_month", "impulse_gain_pct": 0.50, "realized_vol_63": 0.020, "p2_month": "2015-04"}]
    )

    m1 = match_controls(events, controls, seed=7)
    m2 = match_controls(events, controls, seed=7)

    assert m1.equals(m2)  # reproducible from the seed
    assert set(m1["event_id"]) == {"e1", "e2"}
    per_event = m1.groupby("event_id")["control_id"].apply(set)
    # Without replacement: no control serves two events.
    assert per_event["e1"].isdisjoint(per_event["e2"])
    assert (m1.groupby("event_id").size() <= 3).all()
    # Month is part of the cell: the other-month control is never used.
    assert "other_month" not in set(m1["control_id"])


def test_balance_report_smd_shrinks_on_a_constructed_example():
    # A realistically-sized pool: quantile bins over a handful of points
    # are degenerate, so the pool carries 16 filler controls offset ABOVE
    # the event (biasing the pre-match pool mean upward) plus one control
    # right next to the event. Matching must pick the near one; the
    # matched SMD must then shrink vs the full-pool SMD.
    # Two events (SMD needs a variance on both sides -- ddof=1 on a
    # single event is honestly NaN). Whichever event the shuffle serves
    # first takes `near`; the other takes the nearest filler -- the SET
    # of matched controls is deterministic either way.
    events = _frame(
        [
            {"id": "e1", "impulse_gain_pct": 0.50, "realized_vol_63": 0.020},
            {"id": "e2", "impulse_gain_pct": 0.51, "realized_vol_63": 0.020},
        ]
    )
    controls = _frame(
        [{"id": "near", "impulse_gain_pct": 0.505, "realized_vol_63": 0.020}]
        + [
            {"id": f"filler{i}", "impulse_gain_pct": 0.54 + 0.01 * i, "realized_vol_63": 0.020}
            for i in range(16)
        ]
    )
    matches = match_controls(events, controls, seed=1, max_per_event=1)

    assert set(matches["control_id"]) == {"near", "filler0"}
    report = balance_report(events, controls, matches)
    imp = report[report["covariate"] == "impulse_gain_pct"].iloc[0]
    assert abs(imp["smd_after"]) < abs(imp["smd_before"])
    assert imp["n_events"] == 2 and imp["n_pool"] == 17 and imp["n_matched"] == 2

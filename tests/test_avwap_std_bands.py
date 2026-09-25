import math
import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.signals.avwap import store
from src.signals.avwap.compute import anchored_vwap, anchored_vwap_std
from src.signals.avwap.config import AvwapConfig
from src.signals.avwap.lifecycle import apply_interaction_tracking
from src.signals.avwap.models import AnchoredVwap, AnchorStatus, AnchorType
from src.signals.avwap.plotting import render_avwap_chart
from src.foundation.market_common.models import Timeframe


def _bars(rows, start: str = "2020-01-01"):
    """rows: list of (close, volume); open/high/low all equal close, so
    hlc3 == close and hand-computed values hold for either price_source."""
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(
        [(c, c, c, c, v) for c, v in rows],
        columns=["open", "high", "low", "close", "volume"], index=idx,
    )


def _anchor(anchor_date: str) -> AnchoredVwap:
    return AnchoredVwap(
        id="a1", ticker="TEST", timeframe=Timeframe.DAILY, anchor_date=anchor_date,
        anchor_types=frozenset({AnchorType.ATH}), status=AnchorStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# compute.anchored_vwap_std
# ---------------------------------------------------------------------------

def test_equal_volume_two_prices_std_is_half_the_spread():
    bars = _bars([(10, 100), (20, 100)])
    out = anchored_vwap_std(bars, bars.index[0])

    assert out["vwap"].tolist() == pytest.approx([10.0, 15.0])
    # bar 0: one price, no dispersion; bar 1: 10 and 20 equally weighted
    assert out["std"].tolist() == pytest.approx([0.0, 5.0])


def test_unequal_volume_std_is_volume_weighted():
    bars = _bars([(10, 300), (20, 100)])
    out = anchored_vwap_std(bars, bars.index[0])

    # vwap = (3000 + 2000) / 400 = 12.5
    # E[p^2] = (300*100 + 100*400) / 400 = 175 -> var = 175 - 156.25 = 18.75
    assert out["vwap"].iloc[-1] == pytest.approx(12.5)
    assert out["std"].iloc[-1] == pytest.approx(math.sqrt(18.75))


def test_constant_price_has_zero_std():
    bars = _bars([(50, 100)] * 5)
    out = anchored_vwap_std(bars, bars.index[0])
    assert (out["std"] == 0.0).all()


def test_pre_anchor_bars_are_nan_and_anchor_resets_the_accumulators():
    bars = _bars([(1000, 1_000_000), (10, 100), (20, 100)])
    out = anchored_vwap_std(bars, bars.index[1])

    assert out["vwap"].iloc[:1].isna().all()
    assert out["std"].iloc[:1].isna().all()
    # the huge pre-anchor bar contributes nothing
    assert out["std"].iloc[-1] == pytest.approx(5.0)


def test_zero_volume_stretch_after_anchor_is_nan_not_zero():
    bars = _bars([(10, 0), (10, 0), (20, 100)])
    out = anchored_vwap_std(bars, bars.index[0])
    assert out["std"].iloc[:2].isna().all()
    assert out["std"].iloc[2] == pytest.approx(0.0)


def test_vwap_column_matches_anchored_vwap():
    rng = np.random.default_rng(0)
    closes = 100 + rng.normal(0, 3, 300).cumsum()
    vols = rng.integers(1_000, 100_000, 300).astype(float)
    bars = _bars(list(zip(closes, vols)))
    anchor = bars.index[40]

    out = anchored_vwap_std(bars, anchor)
    expected = anchored_vwap(bars, anchor)
    pd.testing.assert_series_equal(out["vwap"], expected, check_names=False, rtol=1e-10)


def test_std_is_precise_at_large_price_levels():
    # Naive E[p^2] - E[p]^2 at p ~ 1e8 subtracts two ~1e16 numbers and loses
    # the 0.25 variance entirely; the shifted computation must not.
    bars = _bars([(1e8, 100), (1e8 + 1, 100)] * 50)
    out = anchored_vwap_std(bars, bars.index[0])
    assert out["std"].iloc[-1] == pytest.approx(0.5, rel=1e-9)


def test_no_lookahead_truncating_future_bars_leaves_past_values_unchanged():
    rng = np.random.default_rng(1)
    closes = 50 + rng.normal(0, 1, 200).cumsum()
    vols = rng.integers(100, 10_000, 200).astype(float)
    bars = _bars(list(zip(closes, vols)))
    anchor = bars.index[20]

    full = anchored_vwap_std(bars, anchor)
    for cut in (21, 60, 150):
        partial = anchored_vwap_std(bars.iloc[:cut], anchor)
        pd.testing.assert_frame_equal(partial, full.iloc[:cut])


# ---------------------------------------------------------------------------
# lifecycle: current_std / distance_std snapshot
# ---------------------------------------------------------------------------

def test_distance_std_is_signed_close_minus_avwap_over_std():
    bars = _bars([(10, 100), (20, 100)])
    atr = pd.Series(1.0, index=bars.index)
    anchor = _anchor(bars.index[0].isoformat())

    apply_interaction_tracking(bars, atr, anchor, AvwapConfig(price_source="close"))

    assert anchor.current_std == pytest.approx(5.0)
    assert anchor.distance_std == pytest.approx((20 - 15) / 5.0)


def test_distance_std_is_negative_below_the_line():
    bars = _bars([(20, 100), (10, 100)])
    atr = pd.Series(1.0, index=bars.index)
    anchor = _anchor(bars.index[0].isoformat())

    apply_interaction_tracking(bars, atr, anchor, AvwapConfig(price_source="close"))

    assert anchor.distance_std == pytest.approx(-1.0)


def test_distance_std_is_none_when_std_is_zero():
    bars = _bars([(50, 100)] * 4)
    atr = pd.Series(1.0, index=bars.index)
    anchor = _anchor(bars.index[0].isoformat())

    apply_interaction_tracking(bars, atr, anchor, AvwapConfig(price_source="close"))

    assert anchor.current_std == 0.0
    assert anchor.distance_std is None


# ---------------------------------------------------------------------------
# store: migration + round trip
# ---------------------------------------------------------------------------

# avwap_anchors exactly as it was created before current_std/distance_std.
_PRE_STD_SCHEMA = """
CREATE TABLE avwap_anchors (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT,
    anchor_date TEXT,
    anchor_types TEXT,
    status TEXT,
    current_value REAL, updated_through TEXT,
    distance_atr REAL, n_crosses INTEGER,
    pct_bars_above REAL, pct_bars_below REAL,
    last_cross_date TEXT, avg_reaction_atr_on_touch REAL,
    run_id TEXT,
    UNIQUE (ticker, timeframe, anchor_date)
);
"""


def _stored_anchor(**overrides) -> AnchoredVwap:
    anchor = _anchor("2020-01-01T00:00:00")
    anchor.current_value = 15.0
    anchor.current_std = 5.0
    anchor.distance_std = 1.0
    for k, v in overrides.items():
        setattr(anchor, k, v)
    return anchor


def test_migration_adds_std_columns_to_a_pre_existing_table_and_keeps_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute(_PRE_STD_SCHEMA)
    conn.execute(
        "INSERT INTO avwap_anchors (id, ticker, timeframe, anchor_date, anchor_types, status, current_value)"
        " VALUES ('old', 'TEST', 'daily', '2019-01-01T00:00:00', '[\"ath\"]', 'active', 42.0)"
    )
    conn.commit()

    store.create_avwap_table(conn)
    store.create_avwap_table(conn)  # idempotent: second call must not re-ALTER

    columns = {row[1] for row in conn.execute("PRAGMA table_info(avwap_anchors)").fetchall()}
    assert {"current_std", "distance_std"} <= columns
    old = conn.execute(
        "SELECT current_value, current_std, distance_std FROM avwap_anchors WHERE id = 'old'"
    ).fetchone()
    assert old == (42.0, None, None)

    store.upsert_anchors(conn, [_stored_anchor()], "run-1")
    assert conn.execute("SELECT COUNT(*) FROM avwap_anchors").fetchone()[0] == 2


def test_std_fields_round_trip_and_update_on_conflict():
    conn = sqlite3.connect(":memory:")
    store.create_avwap_table(conn)

    store.upsert_anchors(conn, [_stored_anchor()], "run-1")
    assert conn.execute("SELECT current_std, distance_std FROM avwap_anchors").fetchone() == (5.0, 1.0)

    store.upsert_anchors(conn, [_stored_anchor(current_std=4.0, distance_std=None)], "run-2")
    assert conn.execute("SELECT current_std, distance_std FROM avwap_anchors").fetchone() == (4.0, None)


# ---------------------------------------------------------------------------
# plotting
# ---------------------------------------------------------------------------

def test_chart_draws_two_bands_per_multiplier_per_line():
    rng = np.random.default_rng(2)
    closes = 100 + rng.normal(0, 1, 60).cumsum()
    bars = _bars(list(zip(closes, [1000.0] * 60)))
    anchor = _anchor(bars.index[10].isoformat())

    base = render_avwap_chart(bars, [anchor], "TEST", Timeframe.DAILY, AvwapConfig(band_multipliers=()))
    banded = render_avwap_chart(bars, [anchor], "TEST", Timeframe.DAILY, AvwapConfig(band_multipliers=(1.0, 2.0)))

    assert len(banded.data) - len(base.data) == 4

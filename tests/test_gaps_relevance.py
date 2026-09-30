import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db as raw_db
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe
from src.signals.gaps import relevance, store
from src.signals.gaps.config import GapConfig
from src.signals.gaps.detect import detect
from src.signals.gaps.models import Direction, Gap, GapKind

REAL_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "market_data.sqlite"
CFG = GapConfig(min_bars=60, warmup_bars=20)


def _random_walk_bars(n=600, seed=3):
    """A jumpy random walk: frequent overnight gaps, some filled, some not."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    close = 50 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n)))
    open_ = close * np.exp(rng.normal(0, 0.015, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.integers(1_000, 5_000, n).astype(float), "is_partial": 0}, index=idx)


@pytest.fixture
def raw_conn():
    c = raw_db.get_connection(":memory:")
    raw_db.create_tables(c)
    raw_db.upsert_bars(c, "bars_1d", "RW", raw_db.YFINANCE, _random_walk_bars())
    yield c
    c.close()


def _key(kind, direction, created_at):
    return (kind, direction, str(created_at)[:10])


def _assert_matches_as_of_run(conn, ticker, as_of_dates, config):
    full, _, reason = detect(conn, ticker, Timeframe.DAILY, config)
    assert reason is None
    from src.foundation.market_common import data as data_mod
    bars, _ = data_mod.load_and_validate(conn, ticker, Timeframe.DAILY)
    states = relevance.gap_states(bars, full, as_of_dates, config, include_closed=True)
    checked = 0
    for as_of in as_of_dates:
        pit, _, _ = detect(conn, ticker, Timeframe.DAILY, config, as_of=as_of)
        expected = {_key(g.kind.value, g.direction.value, g.created_at): (g.max_fill_pct, g.status.value) for g in pit}
        day = states[states["date"] == states["date"][states["date"] <= pd.Timestamp(as_of)].max()]
        got = {_key(r.kind, r.direction, r.created_at): (r.max_fill_pct, r.status) for r in day.itertuples()}
        assert got.keys() == expected.keys()
        for k, (fill, status) in expected.items():
            assert got[k][0] == pytest.approx(fill, abs=1e-9)
            assert got[k][1] == status
            checked += 1
    return checked


def test_gap_states_match_a_real_as_of_detection_run(raw_conn):
    dates = ["2015-06-30", "2016-03-15", "2016-11-01", "2017-04-20"]
    assert _assert_matches_as_of_run(raw_conn, "RW", dates, CFG) > 50


def test_gap_states_match_as_of_runs_on_real_aapl():
    if not REAL_DB_PATH.exists():
        pytest.skip(f"real DB not found at {REAL_DB_PATH}")
    conn = sqlite3.connect(f"file:{REAL_DB_PATH}?mode=ro", uri=True)
    try:
        assert _assert_matches_as_of_run(conn, "AAPL", ["2008-10-10", "2015-06-01", "2020-03-23"], GapConfig()) > 100
    finally:
        conn.close()


def _gap(bottom, top, created, direction=Direction.BULLISH):
    return Gap(id=f"g{created}", ticker="X", timeframe=Timeframe.DAILY, kind=GapKind.CLASSIC,
               direction=direction, created_at=pd.Timestamp(created).isoformat(),
               zone_top=top, zone_bottom=bottom, size_atr=1.0)


def _flat(closes, start="2020-01-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    c = pd.Series(closes, index=idx, dtype="float64")
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1000.0})


def test_in_reach_is_judged_against_that_dates_close():
    bars = _flat([100.0] * 5 + [45.0] * 5 + [60.0] * 5)
    g = _gap(95.0, 105.0, bars.index[0])  # midpoint 100
    # the drop to 45 fills the gap; include_closed keeps it so distance is what's tested
    s = relevance.gap_states(bars, [g], [bars.index[4], bars.index[9], bars.index[14]], GapConfig(), include_closed=True)
    assert s["in_reach"].tolist() == [True, False, True]   # 1x, 2.2x, 1.67x
    assert s["distance_x"].round(2).tolist() == [1.0, 2.22, 1.67]


def test_a_gap_is_absent_before_it_exists_and_fills_only_from_later_bars():
    bars = _flat([100.0] * 3 + [110.0] * 3 + [104.0] * 3)   # falls back into a 102-108 bullish gap
    g = _gap(102.0, 108.0, bars.index[3])
    s = relevance.gap_states(bars, [g], list(bars.index), GapConfig(), include_closed=True)
    assert s["date"].min() == bars.index[3]                   # nothing before creation
    first = s.set_index("date")
    assert first.loc[bars.index[3], "max_fill_pct"] == 0.0     # creation bar itself doesn't fill
    assert first.loc[bars.index[5], "max_fill_pct"] == 0.0
    assert first.loc[bars.index[6], "max_fill_pct"] == pytest.approx(66.667, abs=0.01)  # low 104
    assert first.loc[bars.index[6], "status"] == "partial"


def test_distance_ignores_direction_and_handles_bad_prices():
    assert relevance.distance_x(9.0, 11.0, 5.0) == 2.0
    assert relevance.distance_x(9.0, 11.0, 20.0) == 2.0
    assert relevance.distance_x(0.0, 0.0, 20.0) == float("inf")


def test_detect_fills_the_snapshot_flag_and_it_round_trips_through_the_store(raw_conn):
    gaps, _, _ = detect(raw_conn, "RW", Timeframe.DAILY, CFG)
    assert all(g.distance_x is not None and g.in_reach is not None for g in gaps)
    assert any(g.in_reach for g in gaps)

    derived = derived_db.get_connection(":memory:")
    store.create_gaps_table(derived)
    store.upsert_gaps(derived, gaps, run_id="r1")
    n_in, n = derived.execute("SELECT SUM(in_reach), COUNT(*) FROM gaps").fetchone()
    assert n == len(gaps) and n_in == sum(bool(g.in_reach) for g in gaps)


def test_old_gaps_table_gains_the_new_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE gaps (id TEXT PRIMARY KEY, ticker TEXT, timeframe TEXT, kind TEXT, direction TEXT, "
                 "created_at TEXT, zone_top REAL, zone_bottom REAL, size_atr REAL, status TEXT, max_fill_pct REAL, "
                 "first_touch_date TEXT, soft_closed_date TEXT, closed_date TEXT, bars_to_first_touch INTEGER, "
                 "bars_to_soft_closed INTEGER, bars_to_closed INTEGER, n_approaches INTEGER, "
                 "volume_ratio_at_creation REAL, reaction_atr_after_close REAL, bars_to_reaction_peak INTEGER, "
                 "related_id TEXT, run_id TEXT, UNIQUE (ticker, timeframe, kind, created_at, direction))")
    store.create_gaps_table(conn)
    store.create_gaps_table(conn)  # idempotent
    cols = {r[1] for r in conn.execute("PRAGMA table_info(gaps)")}
    assert {"distance_x", "in_reach"} <= cols


def test_closed_gaps_are_left_out_by_default_and_never_come_back():
    bars = _flat([100.0] * 3 + [110.0] * 3 + [101.0] * 2 + [110.0] * 3)   # fully fills a 102-108 gap
    g = _gap(102.0, 108.0, bars.index[3])
    live = relevance.gap_states(bars, [g], list(bars.index), GapConfig())
    full = relevance.gap_states(bars, [g], list(bars.index), GapConfig(), include_closed=True)
    assert set(full["status"]) >= {"open", "closed"}
    assert "closed" not in set(live["status"])
    assert live["date"].max() < bars.index[6]   # gone from the close onward, even after price leaves

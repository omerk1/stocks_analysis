import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.foundation.data_processing import db as raw_db
from src.foundation.market_common import derived_db
from src.foundation.market_common.anchors import AnchorConfig, AnchorStatus, AnchorType
from src.foundation.market_common.models import Timeframe
from src.signals.avwap.config import AvwapConfig
from src.signals.volume_profile import store
from src.signals.volume_profile.config import VolumeProfileConfig
from src.signals.volume_profile.detect import detect, discover_profiles
from src.signals.volume_profile.plotting import render_volume_profile_chart

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_DB_PATH = REPO_ROOT / "data" / "raw" / "market_data.sqlite"


@pytest.fixture
def raw_conn():
    connection = raw_db.get_connection(":memory:")
    raw_db.create_tables(connection)
    yield connection
    connection.close()


@pytest.fixture
def derived_conn():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    store.create_volume_profile_table(connection)
    yield connection
    connection.close()


def _seed(raw_conn, ticker="TEST", n=200, extra_future=0):
    idx = pd.bdate_range("2020-01-01", periods=n + extra_future)
    rows = []
    for i, d in enumerate(idx):
        price = 100.0 + (i % 7)
        rows.append((d.strftime("%Y-%m-%d"), price, price + 1.0, price - 1.0, price + 0.5, 1000.0 + 10 * i, 0))
    # A lone spike-high and dip-low well inside the series -> guaranteed ath/atl anchors.
    if n > 100:
        rows[50] = (idx[50].strftime("%Y-%m-%d"), 100.0, 500.0, 99.5, 100.0, 1000.0, 0)
        rows[100] = (idx[100].strftime("%Y-%m-%d"), 100.0, 100.5, 1.0, 100.0, 1000.0, 0)
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "is_partial"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    raw_db.upsert_bars(raw_conn, "bars_1d", ticker, raw_db.YFINANCE, df.set_index("timestamp"))
    return idx


def _config():
    return VolumeProfileConfig(min_bars=1, warmup_bars=0, row_count=50)


def test_both_consumer_configs_are_anchor_configs_with_the_same_defaults():
    base = AnchorConfig()
    for cfg in (AvwapConfig(), VolumeProfileConfig()):
        assert isinstance(cfg, AnchorConfig)
        assert cfg.max_anchors_total == base.max_anchors_total
        assert cfg.trailing_window_bars == base.trailing_window_bars


def test_detect_snapshots_every_anchor_consistently(raw_conn):
    _seed(raw_conn)
    profiles, _, skip = detect(raw_conn, "TEST", Timeframe.DAILY, _config())
    assert skip is None
    roles = {r for p in profiles for r in p.anchor_types}
    assert {AnchorType.ATH, AnchorType.ATL} <= roles
    for p in profiles:
        assert p.val <= p.poc <= p.vah
        assert p.total_volume == pytest.approx(p.up_volume + p.down_volume)
        assert p.value_area_position in {"above", "inside", "below"}
        assert p.n_bars >= 1
        assert p.distance_to_poc_atr is not None


def test_snapshot_at_as_of_ignores_later_bars(raw_conn):
    idx = _seed(raw_conn, n=200, extra_future=60)
    as_of = idx[199].strftime("%Y-%m-%d")

    truncated_conn = raw_db.get_connection(":memory:")
    raw_db.create_tables(truncated_conn)
    _seed(truncated_conn, n=200)

    with_future, _, _ = detect(raw_conn, "TEST", Timeframe.DAILY, _config(), as_of=as_of)
    without, _, _ = detect(truncated_conn, "TEST", Timeframe.DAILY, _config())
    truncated_conn.close()

    def _snapshots(profiles):
        return [{k: v for k, v in p.to_dict().items() if k != "id"} for p in profiles]

    assert _snapshots(with_future) == _snapshots(without)


def test_upsert_is_idempotent_and_preserves_ids(raw_conn, derived_conn):
    _seed(raw_conn)
    config = _config()
    profiles_1, _, _ = detect(raw_conn, "TEST", Timeframe.DAILY, config)
    store.upsert_profiles(derived_conn, profiles_1, "run-1")
    ids_1 = {r[0] for r in derived_conn.execute("SELECT id FROM volume_profiles")}
    assert len(ids_1) == len(profiles_1)

    previous = store.get_anchor_types(derived_conn, "TEST", "daily")
    profiles_2, _, _ = detect(raw_conn, "TEST", Timeframe.DAILY, config, previous_anchor_types=previous)
    store.upsert_profiles(derived_conn, profiles_2, "run-2")
    ids_2 = {r[0] for r in derived_conn.execute("SELECT id FROM volume_profiles")}
    assert ids_2 == ids_1
    assert {r[0] for r in derived_conn.execute("SELECT run_id FROM volume_profiles")} == {"run-2"}

    row = derived_conn.execute(
        "SELECT poc, vah, val, value_area_position FROM volume_profiles WHERE anchor_date = ?",
        (profiles_2[0].anchor_date,),
    ).fetchone()
    assert row[:3] == pytest.approx((profiles_2[0].poc, profiles_2[0].vah, profiles_2[0].val))
    assert row[3] == profiles_2[0].value_area_position


def test_anchor_no_longer_qualifying_goes_stale_against_this_modules_own_table(raw_conn, derived_conn):
    _seed(raw_conn)
    config = _config()
    old_date = "2019-06-03T00:00:00"
    previous = {old_date: frozenset({AnchorType.CYCLE_LOW})}

    profiles, _, _ = detect(raw_conn, "TEST", Timeframe.DAILY, config, previous_anchor_types=previous)
    stale = [p for p in profiles if p.anchor_date == old_date]
    assert len(stale) == 1
    assert stale[0].status == AnchorStatus.STALE
    assert stale[0].anchor_types == frozenset({AnchorType.CYCLE_LOW})

    store.upsert_profiles(derived_conn, profiles, "run-1")
    assert store.get_anchor_types(derived_conn, "TEST", "daily")[old_date] == frozenset({AnchorType.CYCLE_LOW})


def test_discover_profiles_matches_avwap_anchor_dates(raw_conn):
    from src.foundation.market_common import data as data_mod
    from src.signals.avwap.anchors import discover_anchor_dates

    _seed(raw_conn)
    bars, _ = data_mod.load_and_validate(raw_conn, "TEST", Timeframe.DAILY)
    vp = discover_profiles(bars, "TEST", Timeframe.DAILY, VolumeProfileConfig(warmup_bars=0))
    av = discover_anchor_dates(bars, "TEST", Timeframe.DAILY, AvwapConfig(warmup_bars=0))
    assert [(p.anchor_date, p.anchor_types, p.status) for p in vp] == [
        (a.anchor_date, a.anchor_types, a.status) for a in av
    ]


def test_too_few_bars_is_skipped(raw_conn):
    _seed(raw_conn, n=20)
    profiles, _, skip = detect(raw_conn, "TEST", Timeframe.DAILY, VolumeProfileConfig())
    assert profiles == [] and "min_bars" in skip


@pytest.mark.parametrize("mode", ["up_down", "total", "delta"])
def test_chart_renders_for_every_volume_mode(raw_conn, mode):
    _seed(raw_conn)
    from src.foundation.market_common import data as data_mod

    config = VolumeProfileConfig(min_bars=1, warmup_bars=0, volume_mode=mode)
    profiles, _, _ = detect(raw_conn, "TEST", Timeframe.DAILY, config)
    bars, _ = data_mod.load_and_validate(raw_conn, "TEST", Timeframe.DAILY)
    fig = render_volume_profile_chart(bars, profiles, "TEST", Timeframe.DAILY, config)
    names = {t.name for t in fig.data}
    assert any(n and n.startswith("POC") for n in names)


def test_smoke_real_aapl_daily():
    if not REAL_DB_PATH.exists():
        pytest.skip(f"real DB not found at {REAL_DB_PATH}")
    conn = sqlite3.connect(f"file:{REAL_DB_PATH}?mode=ro", uri=True)
    profiles, _, skip = detect(conn, "AAPL", Timeframe.DAILY, VolumeProfileConfig())
    conn.close()
    assert skip is None and profiles
    for p in profiles:
        assert p.val <= p.poc <= p.vah
        assert p.poc > 0

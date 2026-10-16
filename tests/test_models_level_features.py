"""The LRP level features (`src/models/features/level_features.py`): the
definitions on a hand-built day, trailing-only weights, missingness kept
(invariant 9), nothing on a day depending on a later bar, and the snapshot
cache as a speed copy of the same columns."""

import numpy as np
import pandas as pd
import pytest

from src.models.features import cache, level_cache, level_features as lf, level_snapshots, levels, registry
from tests.test_models_levels import _bars

TICKER = "RW"


def _flat_bars(n=40):
    """Close 100, high 101, low 99 every day: ATR(14) is 2 once defined."""
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e5}, index=idx)


def _level(date, source, lo, hi, strength=0.5, touches=np.nan, state="active", formed=None):
    return {"date": date, "source": source, "kind": source, "lo": lo, "hi": hi, "strength_raw": strength,
            "formed": formed if formed is not None else date, "touches": touches, "state": state}


@pytest.fixture(scope="module")
def hand_day():
    """One day's levels, each its source's only row (percentile 0.5), formed
    that day (no decay): w = 0.5 x state factor, or the fixed strength."""
    bars = _flat_bars()
    day = bars.index[30]
    daily = pd.DataFrame([
        _level(day, "avwap", 99.5, 100.5),                 # contains the close: d = 0, both sides, w 0.5
        _level(day, "sr_line", 103.0, 104.0, touches=3),    # d = +1.5, tested: w 0.6
        _level(day, "gap", 103.5, 104.0, state="open"),     # d = +1.75, w 0.5
        _level(day, "round", 110.0, 110.0),                 # d = +5, fixed 0.25
        _level(day, "ma", 96.0, 96.0),                      # d = -2, fixed 0.5
    ], columns=levels.DAILY_COLUMNS)
    daily["formed"] = pd.to_datetime(daily["formed"])
    out = lf.features(bars, daily, [bars.index[29]], levels.default_configs())  # snapshot the day before
    return out, day


def test_distances_and_weights_on_a_hand_built_day(hand_day):
    out, day = hand_day
    row = out.loc[day]
    assert row["near_up_avwap"] == 0 and row["near_dn_avwap"] == 0
    assert row["near_up_sr_line"] == pytest.approx(1.5) and np.isnan(row["near_dn_sr_line"])
    assert row["near_up_w_sr_line"] == pytest.approx(0.6) and row["near_up_w_gap"] == pytest.approx(0.5)
    assert row["near_up_round"] == pytest.approx(5.0) and row["near_dn_ma"] == pytest.approx(2.0)
    assert np.isnan(row["near_up_hi52"]) and np.isnan(row["near_up_vp"])


def test_the_aggregates_on_a_hand_built_day(hand_day):
    out, day = hand_day
    row = out.loc[day]
    assert row["clear_up_0p5"] == 0                       # the AVWAP around the close is 0.5 already
    assert row["clear_up_1p5"] == pytest.approx(1.75)     # 0.5 + 0.6 + 0.5 at the gap
    assert row["clear_dn_1p5"] == lf.CAP                  # 0.5 + 0.5 below never reaches 1.5
    assert row["density_up_1"] == pytest.approx(0.5) and row["density_up_2"] == pytest.approx(1.6)
    assert row["density_up_5"] == pytest.approx(1.85) and row["density_dn_2"] == pytest.approx(1.0)
    assert row["lrp_dir"] == pytest.approx(np.log((1.75 + 0.25) / (10 + 0.25)))
    assert row["lrp_pressure_2"] == pytest.approx(1.0 - 1.6)
    assert row["confluence_up"] == pytest.approx(1.1) and row["confluence_up_dist"] == pytest.approx(1.5)
    assert row["confluence_dn"] == 0 and np.isnan(row["confluence_dn_dist"])  # one source per window


def test_the_barrier_columns_on_a_hand_built_day(hand_day):
    out, day = hand_day
    row = out.loc[day]
    assert row["target_on_wall_2"] == pytest.approx(0.5)   # the gap at 1.75
    assert row["target_on_wall_5"] == pytest.approx(0.25) and row["target_on_wall_3"] == 0
    assert row["stop_below_floor_2"] == 1 and row["stop_below_floor_1"] == 0  # the MA at -2
    assert np.isnan(row["vp_ease_up_2"])                   # no volume profile held


def test_columns_are_na_before_the_first_snapshot_and_during_the_atr_warmup(hand_day):
    out, day = hand_day
    assert out.loc[out.index < day].isna().all().all()     # not zeros: the levels aren't known yet
    assert out.loc[day].notna().sum() > 20
    bars = _flat_bars()
    early = bars.index[5]                                  # inside ATR(14)'s warmup
    daily = pd.DataFrame([_level(early, "ma", 96.0, 96.0)], columns=levels.DAILY_COLUMNS)
    daily["formed"] = pd.to_datetime(daily["formed"])
    warm = lf.features(bars, daily, [bars.index[4]], levels.default_configs())
    assert warm.loc[early].isna().all()                    # density would read 0, not "undefined"


def test_strength_percentile_is_trailing_and_windowed():
    day = np.array([0, 0, 1, 2, 10])
    strength = np.array([1.0, 3.0, 2.0, 100.0, 0.5])
    pct = lf.strength_percentile(day, strength, window=5)
    assert pct[0] == pytest.approx(0.25) and pct[1] == pytest.approx(0.75)   # day 0: among {1, 3}
    assert pct[2] == pytest.approx(0.5)                                      # day 1: among {1, 3, 2}
    later = lf.strength_percentile(day[:3], strength[:3], window=5)
    assert np.allclose(pct[:3], later)                                       # a later row moves nothing earlier
    assert pct[4] == pytest.approx(0.5)                                      # day 10: days 0-2 are out of the window
    assert lf.strength_percentile(np.array([0]), np.array([np.nan]))[0] == 0.5


def test_weights_decay_and_state_factors():
    idx = pd.bdate_range("2020-01-01", periods=300)
    day = idx[-1]
    daily = pd.DataFrame([
        _level(day, "ma", 1, 1),                                              # fixed 0.5, no decay
        _level(day, "sr_line", 1, 1, touches=2, state="flipped", formed=idx[-1 - lf.HALF_LIFE]),
        _level(day, "gap", 1, 1, state="partial"),
        _level(day, "avwap", 1, 1, strength=np.nan),                          # untouched AVWAP: 0.5
    ], columns=levels.DAILY_COLUMNS)
    daily["formed"] = pd.to_datetime(daily["formed"])
    w = lf.weights(daily, idx)
    assert w == pytest.approx([0.5, 0.5 * 0.5 * 0.8, 0.5 * 1.2, 0.5])


@pytest.fixture(scope="module")
def walk():
    return _bars(n=700, seed=3)


def _late_start(bars, weeks=6):
    return bars.index[-1] - pd.Timedelta(weeks=weeks)


def test_no_column_on_a_day_depends_on_a_later_bar(walk):
    start = _late_start(walk)
    full = lf.ticker_features(walk, None, TICKER, root=None, snapshot_start=start)
    cut = walk.index[-12]
    part = lf.ticker_features(walk.loc[:cut], None, TICKER, root=None, snapshot_start=start)
    assert full.loc[start:cut].notna().any().all(), "fixture should define every column somewhere"
    pd.testing.assert_frame_equal(full.loc[:cut], part, check_freq=False)


def test_the_snapshot_cache_is_a_speed_copy(tmp_path, walk, monkeypatch):
    start = _late_start(walk)
    clean = levels.prepare(walk)
    taken = levels.snapshot_dates(clean.index, start)
    configs = levels.default_configs()
    for s in levels.SNAPSHOT_SOURCES:
        level_cache.cached_snapshots(tmp_path, s, TICKER, clean, None, taken, configs[s], store=True)
    fresh = lf.ticker_features(walk, None, TICKER, root=None, snapshot_start=start)

    def no_detectors(*a, **k):
        raise AssertionError("a matching cache must not rerun the detectors")
    monkeypatch.setattr(level_snapshots, "snapshots", no_detectors)
    cached = lf.ticker_features(walk, None, TICKER, root=tmp_path, snapshot_start=start)
    pd.testing.assert_frame_equal(fresh, cached)


def test_every_level_column_is_registered_with_a_null_prior():
    specs = [s for s in registry.REGISTRY if s.source == "levels"]
    assert [s.name for s in specs] == list(lf.COLUMNS)
    assert {s.group for s in specs} == {"levels_nearest", "levels_aggregate", "levels_barrier"}
    assert all(s.prior == "null" and s.shape == "level_set" and s.role == registry.MODEL for s in specs)
    assert set(lf.COLUMNS) <= registry.model_columns()
    assert registry.SOURCES["levels"].detector and registry.SOURCES["levels"].basis == levels_basis()


def levels_basis():
    from src.models import dataset
    return dataset.UNIVERSE_BASIS  # the snapshot cache's basis


def test_workers_give_the_same_columns():
    bars = pd.concat([_bars(n=320, seed=s).rename_axis("date").reset_index().assign(ticker=f"T{s}")
                      for s in range(3)], ignore_index=True)
    specs = tuple(s for s in registry.REGISTRY if s.source in ("baseline", "indicators"))
    basis = {registry.SOURCES[s.source].basis for s in specs}
    one = registry.compute_registered({b: bars for b in basis}, {}, specs, rank=False)
    many = registry.compute_registered({b: bars for b in basis}, {}, specs, rank=False, workers=2)
    pd.testing.assert_frame_equal(one, many)


def test_since_drops_early_rows_after_a_warm_computation():
    bars = _bars(n=320, seed=1).rename_axis("date").reset_index().assign(ticker="T")
    specs = tuple(s for s in registry.REGISTRY if s.source == "baseline")
    basis = registry.SOURCES["baseline"].basis
    every = registry.compute_registered({basis: bars}, {}, specs, rank=False)
    since = bars["date"].iloc[260]
    late = registry.compute_registered({basis: bars}, {}, specs, rank=False, since=since)
    pd.testing.assert_frame_equal(late, every[every["date"] >= since].reset_index(drop=True))
    assert late["mom_12_1"].notna().any()   # warm: computed on the whole frame, then cut


def test_the_feature_cache_reads_a_snapshot_cache_built_by_build_levels(tmp_path, monkeypatch):
    """End to end: `build_level_cache` (build-levels) then `build_feature_cache`
    with every registered column. The feature cache's full-history read must
    match the snapshot build's, so nothing misses and no detector reruns."""
    from src.foundation.data_processing import db
    from src.models import dataset
    conn = db.get_connection(":memory:")
    db.create_tables(conn)
    tickers = ["AAA", "BBB"]
    for i, t in enumerate(tickers):
        b = _bars(n=560, seed=20 + i, start="2019-11-01").assign(volume=1e6, is_partial=0)
        for source in (db.YFINANCE, db.YFINANCE_SPLIT_ONLY):
            db.upsert_bars(conn, "bars_1d", t, source, b)
    db.replace_index_membership(conn, "sp500", pd.DataFrame(
        [(t, "2015-01-01", None) for t in tickers], columns=["ticker", "start_date", "end_date"]))
    end = "2021-12-31"
    levels_root = tmp_path / "levels"
    level_cache.build_level_cache(conn, tickers, levels_root, end, workers=1, progress=lambda s: None)

    def no_detectors(*a, **k):
        raise AssertionError("the feature cache must read the snapshot cache, not rerun the detectors")
    monkeypatch.setattr(level_snapshots, "snapshots", no_detectors)
    universe = dataset.universe_mask(conn, "2021-06-01", end)
    cache.build_feature_cache(conn, universe, tmp_path / "features", levels_root=levels_root)
    f = cache.read_feature_cache(tmp_path / "features")
    assert f.attrs["manifest"]["level_cache_misses"] == [] and set(f["ticker"]) == set(tickers)
    assert len(f) == int(universe["eligible"].sum())
    assert f["density_up_2"].notna().all() and f["near_up_round"].notna().all()
    conn.close()


def test_the_feature_cache_finds_tickers_the_snapshot_cache_misses(tmp_path):
    short = _bars(n=160, seed=5, start="2010-01-01")
    long = short.rename_axis("date").reset_index().assign(ticker=TICKER)
    assert cache._level_misses(long, {}, tmp_path) == [TICKER]
    clean = levels.prepare(short)
    taken = levels.snapshot_dates(clean.index)
    configs = levels.default_configs()
    for s in levels.SNAPSHOT_SOURCES:
        level_cache.cached_snapshots(tmp_path, s, TICKER, clean, None, taken, configs[s], store=True)
    assert cache._level_misses(long, {}, tmp_path) == []
    other = long.assign(close=long["close"] * 1.01)        # other bars: a miss again
    assert cache._level_misses(other, {}, tmp_path) == [TICKER]

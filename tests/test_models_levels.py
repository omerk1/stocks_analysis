"""Point-in-time LRP levels (`src/models/features/levels.py`) and their snapshot
cache (`level_cache.py`): each snapshot source equals its detector's own
`as_of` run, nothing on a day depends on a later bar, and the cache is a
speed copy of the same function."""

import ast
import dataclasses
import fcntl
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db as raw_db
from src.foundation.market_common.models import Timeframe
from src.models import dataset
from src.models.features import level_cache, level_snapshots, levels
from src.signals.avwap.anchors import detect as avwap_detect
from src.signals.avwap.compute import anchored_vwap_std
from src.signals.sr_lines import engine as sr_engine
from src.signals.volume_profile.detect import detect as vp_detect

TICKER = "RW"


def _bars(n=900, seed=7, start="2015-01-01"):
    """A trending, gappy random walk with volume -- enough pivots, anchors and gaps."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = 40 * np.exp(np.cumsum(rng.normal(0.0004, 0.018, n)))
    open_ = close * np.exp(rng.normal(0, 0.012, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.008, n)))
    vol = rng.integers(10_000, 50_000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


@pytest.fixture(scope="module")
def bars():
    return levels.prepare(_bars())


@pytest.fixture(scope="module")
def conn(bars):
    c = raw_db.get_connection(":memory:")
    raw_db.create_tables(c)
    raw_db.upsert_bars(c, "bars_1d", TICKER, raw_db.YFINANCE_SPLIT_ONLY, bars.assign(is_partial=0))
    yield c
    c.close()


@pytest.fixture(scope="module")
def configs():
    return levels.default_configs()


def _as_of_dates(bars):
    return levels.snapshot_dates(bars.index, bars.index[0])[[-60, -25, -1]]


# ---------------------------------------------------------- equal to the detectors


def test_sr_snapshot_equals_the_detectors_as_of_run(conn, bars, configs):
    cfg = configs["sr_line"]
    for t in _as_of_dates(bars):
        lines = sr_engine.detect(conn, TICKER, cfg, as_of=t).lines
        expected = sorted((round(l.center - l.half_width, 9), round(l.strength, 12))
                          for l in lines if l.state.value != "broken")
        snap = levels.sr_snapshots(bars, [t], cfg)
        assert expected, "fixture should produce S/R lines"
        assert sorted(zip(snap["lo"].round(9), snap["strength_raw"].round(12))) == expected


def test_avwap_snapshot_equals_the_detectors_as_of_run(conn, bars, configs):
    cfg = configs["avwap"]
    for t in _as_of_dates(bars):
        anchors, _, skip = avwap_detect(conn, TICKER, Timeframe.DAILY, cfg, as_of=t)
        assert skip is None and anchors
        expected = sorted((pd.Timestamp(a.anchor_date), round(a.current_value, 9), a.status.value) for a in anchors)
        snap = levels.avwap_snapshots(bars, None, [t], cfg, TICKER)
        mid = (snap["lo"] + snap["hi"]) / 2
        assert sorted(zip(snap["anchor_date"], mid.round(9), snap["state"])) == expected


def test_vp_snapshot_equals_the_detectors_as_of_run(conn, bars, configs):
    cfg = configs["vp"]
    for t in _as_of_dates(bars):
        profiles, _, skip = vp_detect(conn, TICKER, Timeframe.DAILY, cfg, as_of=t)
        assert skip is None and profiles
        snap = levels.vp_snapshots(bars, None, [t], cfg, TICKER)
        for kind, attr in (("vah", "vah"), ("val", "val")):
            got = sorted(snap.loc[snap["kind"] == kind, "lo"].round(9))
            assert got == sorted(round(getattr(p, attr), 9) for p in profiles)
        pocs = snap[snap["kind"] == "poc"]
        for p in profiles:  # the POC's row band contains the detector's POC price
            assert ((pocs["lo"] <= p.poc + 1e-9) & (pocs["hi"] >= p.poc - 1e-9)).any()
        assert snap["strength_raw"].between(0, 1).all()


# ---------------------------------------------------------- point in time


def _perturb_after(bars, cut, seed=1):
    """A different future: every bar after `cut` follows another walk."""
    out = bars.copy()
    after = out.index > cut
    rng = np.random.default_rng(seed)
    shock = np.exp(np.cumsum(rng.normal(0, 0.03, after.sum())))
    for col in ("open", "high", "low", "close"):
        out.loc[after, col] = out.loc[after, col] * shock
    out.loc[after, "volume"] = out.loc[after, "volume"] * rng.uniform(0.2, 5, after.sum())
    return levels.prepare(out)


def _all_levels(bars, configs, dates=None):
    dates = levels.snapshot_dates(bars.index, bars.index[0]) if dates is None else dates
    snaps = pd.concat([levels.snapshots(s, bars, None, dates, configs[s], TICKER) for s in levels.SNAPSHOT_SOURCES],
                      ignore_index=True)
    return levels.daily_levels(bars, None, snaps, bars.index, dates, configs)


def test_no_level_on_or_before_the_cut_depends_on_a_later_bar(bars, configs):
    cut = bars.index[-120]
    dates = levels.snapshot_dates(bars.index, bars.index[0])
    dates = dates[(dates > cut - pd.Timedelta(days=60)) & (dates <= cut + pd.Timedelta(days=60))]
    days = bars.index[bars.index >= dates[0]]
    before = _all_levels(bars, configs, dates)
    after = _all_levels(_perturb_after(bars, cut), configs, dates)
    a = before[(before["date"] >= days[0]) & (before["date"] <= cut)].reset_index(drop=True)
    b = after[(after["date"] >= days[0]) & (after["date"] <= cut)].reset_index(drop=True)
    assert set(a["source"]) >= {"sr_line", "avwap", "vp", "gap", "ma", "round"}
    pd.testing.assert_frame_equal(a, b)
    # ... and the perturbation did reach the levels after the cut.
    assert not before[before["date"] > cut].reset_index(drop=True).equals(after[after["date"] > cut].reset_index(drop=True))


def test_a_snapshot_equals_one_taken_on_bars_truncated_there(bars, configs):
    t = _as_of_dates(bars)[1]
    for s in levels.SNAPSHOT_SOURCES:
        full = levels.snapshots(s, bars, None, [t], configs[s], TICKER).reset_index(drop=True)
        cut = levels.snapshots(s, bars.loc[:t], None, [t], configs[s], TICKER).reset_index(drop=True)
        pd.testing.assert_frame_equal(full, cut)


def test_days_hold_the_latest_snapshot_and_avwap_moves_daily(bars, configs):
    dates = _as_of_dates(bars)[1:2]
    t = dates[0]
    snaps = levels.avwap_snapshots(bars, None, dates, configs["avwap"], TICKER)
    days = bars.index[(bars.index >= t - pd.Timedelta(days=10)) & (bars.index <= t + pd.Timedelta(days=10))]
    out = levels.daily_levels(bars, None, snaps, days, dates, configs)
    av = out[out["source"] == "avwap"]
    assert av["date"].min() == t  # nothing before the snapshot was taken
    anchor = snaps["anchor_date"].iloc[0]
    for d in av["date"].unique():
        band = anchored_vwap_std(bars.loc[:d], anchor).iloc[-1]
        lo = band["vwap"] - 0.5 * band["std"]
        assert np.isclose(av.loc[av["date"] == d, "lo"], lo).any()
    assert av.groupby("date")["lo"].first().nunique() > 1


def test_stale_anchors_are_dropped(bars, configs):
    t = _as_of_dates(bars)[-1]
    snaps = levels.avwap_snapshots(bars, None, [t], configs["avwap"], TICKER)
    snaps.loc[snaps.index[0], "state"] = "stale"
    out = levels.daily_levels(bars, None, snaps, [t], [t], configs)
    assert (out["source"] == "avwap").sum() == len(snaps) - 1


# ---------------------------------------------------------- bar-only sources


def test_bar_levels_are_absent_not_zero_during_their_warmup(bars):
    out = levels.bar_levels(bars, None, bars.index)
    sma200 = out[out["kind"] == "sma_200"]
    assert sma200["date"].min() == bars.index[199]
    assert out[out["source"] == "hi52"]["date"].min() == bars.index[levels.HI_LO_WINDOW - 1]
    assert out["lo"].gt(0).all()


def test_round_numbers_sit_on_the_traded_price_not_the_adjusted_one():
    raw = _bars(n=300)
    split_day = raw.index[150]
    adjusted = raw.copy()
    for col in ("open", "high", "low", "close"):  # a later 2-for-1: earlier prices adjusted x 0.5
        adjusted.loc[adjusted.index < split_day, col] /= 2
    splits = pd.DataFrame({"execution_date": [split_day], "ratio": [2.0]})
    out = levels.bar_levels(levels.prepare(adjusted), splits, adjusted.index)
    rnd = out[out["source"] == "round"].merge(
        pd.DataFrame({"date": adjusted.index, "factor": np.where(adjusted.index < split_day, 0.5, 1.0),
                      "traded": raw["close"].to_numpy()}), on="date")
    traded_level = rnd["lo"] / rnd["factor"]
    step = levels.round_step(traded_level.to_numpy() * (1 - 1e-9))  # each level on its own bracket's step
    assert np.allclose(traded_level / step, np.round(traded_level / step))
    up1 = rnd[rnd["kind"] == "round_up_1"]
    assert (up1["lo"] / up1["factor"] > up1["traded"]).all()


def test_snapshot_dates_are_each_weeks_last_bar():
    idx = pd.bdate_range("2021-03-29", "2021-04-09").drop(pd.Timestamp("2021-04-02"))  # Good Friday
    got = levels.snapshot_dates(idx, idx[0])
    assert list(got) == [pd.Timestamp("2021-04-01"), pd.Timestamp("2021-04-09")]


def test_round_step_brackets():
    assert list(levels.round_step(np.array([5.0, 50.0, 250.0, 900.0]))) == [1.0, 5.0, 10.0, 50.0]


# ---------------------------------------------------------- the cache


def test_cache_returns_stored_rows_and_recomputes_when_inputs_change(tmp_path, bars, configs, monkeypatch):
    dates = _as_of_dates(bars)
    first = level_cache.cached_snapshots(tmp_path, "sr_line", TICKER, bars, None, dates, configs["sr_line"],
                                         store=True)
    calls = []
    real = level_snapshots.snapshots
    monkeypatch.setattr(level_snapshots, "snapshots", lambda *a, **k: calls.append(1) or real(*a, **k))
    again = level_cache.cached_snapshots(tmp_path, "sr_line", TICKER, bars, None, dates, configs["sr_line"])
    pd.testing.assert_frame_equal(first, again)
    assert calls == []
    changed = bars.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] *= 1.01
    level_cache.cached_snapshots(tmp_path, "sr_line", TICKER, changed, None, dates, configs["sr_line"])
    assert calls == [1]
    splits = pd.DataFrame({"execution_date": [bars.index[10]], "ratio": [2.0]})
    level_cache.cached_snapshots(tmp_path, "sr_line", TICKER, changed, splits, dates, configs["sr_line"])
    assert calls == [1, 1]
    # Equivalent inputs of other dtypes are the same inputs: a hit.
    as_strings = splits.assign(execution_date=splits["execution_date"].dt.strftime("%Y-%m-%d"))
    changed["volume"] = changed["volume"].round()
    key = level_cache.fingerprint("sr_line", TICKER, changed, splits, dates, configs["sr_line"])
    assert level_cache.fingerprint("sr_line", TICKER, changed.assign(volume=changed["volume"].astype("int64")), as_strings,
                                   dates, configs["sr_line"]) == key


def test_config_key_is_the_same_in_every_process():
    code = ("from src.models.features import level_cache, levels; "
            "print(level_cache.config_key(levels.default_configs()['avwap']))")
    keys = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                           env={**os.environ, "PYTHONHASHSEED": seed}).stdout for seed in ("1", "2", "3")}
    assert len(keys) == 1


def test_build_refuses_the_holdout(tmp_path):
    with pytest.raises(dataset.HoldoutError):
        level_cache.build_level_cache(None, ["X"], tmp_path, "2022-06-30")


def test_a_week_with_no_rows_does_not_fall_back_to_the_week_before(bars, configs):
    dates = levels.snapshot_dates(bars.index, bars.index[0])[-3:]
    snaps = levels.avwap_snapshots(bars, None, dates[:1], configs["avwap"], TICKER)  # only the first week has rows
    out = levels.daily_levels(bars, None, snaps, bars.index[bars.index >= dates[0]], dates, configs)
    av = out[out["source"] == "avwap"]
    assert av["date"].max() < dates[1]


def test_avwap_rolls_forward_on_the_configs_price_source(bars, configs):
    t = _as_of_dates(bars)[1]
    cfg = {**configs, "avwap": dataclasses.replace(configs["avwap"], price_source="close")}
    snaps = levels.avwap_snapshots(bars, None, [t], cfg["avwap"], TICKER)
    day = bars.index[bars.index > t][3]
    out = levels.daily_levels(bars, None, snaps, [day], [t], cfg)
    anchor = snaps["anchor_date"].iloc[0]
    band = anchored_vwap_std(bars.loc[:day], anchor, "close").iloc[-1]
    assert np.isclose(out.loc[out["source"] == "avwap", "lo"], band["vwap"] - 0.5 * band["std"]).any()


def test_gap_strength_falls_with_fill_and_is_never_negative(bars, configs):
    out = levels.gap_levels(bars, bars.index, configs["gaps"])
    assert len(out) and (out["strength_raw"] >= 0).all()
    from src.signals.gaps.detect import detect_on_bars
    from src.signals.gaps.relevance import gap_states
    gaps, _ = detect_on_bars(bars, TICKER, Timeframe.DAILY, configs["gaps"])
    st = gap_states(bars, gaps, bars.index, configs["gaps"])
    st = st[st["in_reach"].astype(bool)].reset_index(drop=True)
    vol = pd.to_numeric(st["volume_ratio_at_creation"], errors="coerce").fillna(1.0)
    expected = st["size_atr"] * (100 - st["max_fill_pct"]) / 100 * vol
    assert np.allclose(out["strength_raw"].to_numpy(), expected.to_numpy())


@pytest.mark.parametrize("price, up, dn", [(98.0, [100, 110], [95, 90]), (21.0, [25, 30], [20, 19]),
                                           (480.0, [490, 500], [480, 470]), (505.0, [550, 600], [500, 490]),
                                           (12.3, [13, 14], [12, 11])])
def test_each_round_number_uses_its_own_brackets_step(price, up, dn):
    idx = pd.bdate_range("2020-01-01", periods=3)
    b = pd.DataFrame({"open": price, "high": price, "low": price, "close": price, "volume": 1.0}, index=idx)
    out = levels.bar_levels(b, None, idx)
    day = out[out["date"] == idx[-1]].set_index("kind")["lo"]
    assert [day["round_up_1"], day["round_up_2"]] == up
    assert [day["round_dn_1"], day["round_dn_2"]] == dn


def test_only_the_build_stores_so_other_inputs_never_replace_the_real_entry(tmp_path, bars, configs):
    dates = _as_of_dates(bars)
    real = level_cache.cached_snapshots(tmp_path, "sr_line", TICKER, bars, None, dates, configs["sr_line"],
                                        store=True)
    perturbed = bars.copy()
    perturbed["close"] *= 1.0001
    level_cache.cached_snapshots(tmp_path, "sr_line", TICKER, levels.prepare(perturbed), None, dates,
                                 configs["sr_line"])  # the default doesn't store
    key = level_cache.fingerprint("sr_line", TICKER, bars, None, dates, configs["sr_line"])
    pd.testing.assert_frame_equal(level_cache.read_cached(tmp_path, "sr_line", TICKER, key), real)


def test_a_corrupt_file_is_a_miss_and_heals(tmp_path, bars, configs):
    dates = _as_of_dates(bars)
    level_cache.cached_snapshots(tmp_path, "sr_line", TICKER, bars, None, dates, configs["sr_line"], store=True)
    level_cache.snapshot_path(tmp_path, "sr_line", TICKER).write_bytes(b"PAR1 truncated")
    key = level_cache.fingerprint("sr_line", TICKER, bars, None, dates, configs["sr_line"])
    assert level_cache.read_cached(tmp_path, "sr_line", TICKER, key) is None
    assert level_cache.cached_rows(tmp_path, "sr_line", TICKER, key) is None
    level_cache.cached_snapshots(tmp_path, "sr_line", TICKER, bars, None, dates, configs["sr_line"], store=True)
    assert level_cache.read_cached(tmp_path, "sr_line", TICKER, key) is not None
    assert level_cache.cached_rows(tmp_path, "sr_line", TICKER, key) == len(
        level_cache.read_cached(tmp_path, "sr_line", TICKER, key))
    assert not list((tmp_path / "sr_line").glob("*.tmp*"))


def test_dotted_tickers_get_their_own_files(tmp_path, bars, configs):
    dates = _as_of_dates(bars)[-1:]
    for t in ("BF.A", "BF.B", "BF"):
        level_cache.cached_snapshots(tmp_path, "sr_line", t, bars, None, dates, configs["sr_line"], store=True)
    assert sorted(f.name for f in (tmp_path / "sr_line").iterdir()) == ["BF.A.parquet", "BF.B.parquet", "BF.parquet"]


def test_the_code_hash_ignores_comments_and_docstrings_but_not_code():
    src = 'def f(x):\n    """doc"""\n    return x + 1  # note\n'
    dump = lambda text: ast.dump(level_cache._strip_docstrings(ast.parse(text)))  # noqa: E731
    assert dump(src) == dump('def f(x):\n    """other doc"""\n    return x + 1\n')
    assert dump(src) != dump('def f(x):\n    return x + 2\n')
    assert all(f.exists() for f in level_cache.CODE_FILES + level_cache.CODE_EXCLUDED)


def test_the_code_hash_covers_every_module_a_snapshot_imports():
    # In a fresh process: every src module `level_snapshots` loads is hashed or
    # deliberately excluded -- a new dependency can't silently skip the hash.
    code = ("import sys, os; import src.models.features.level_snapshots; "
            "print('\\n'.join(os.path.abspath(m.__file__) for m in list(sys.modules.values()) "
            "if getattr(m, '__file__', None)))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
    src = Path(level_cache.__file__).resolve().parents[2]
    loaded = {Path(f).resolve() for f in out if Path(f).resolve().is_relative_to(src) and Path(f).name != "__init__.py"}
    assert loaded == set(level_cache.CODE_FILES) | set(level_cache.CODE_EXCLUDED)
    assert Path(levels.__file__).resolve() not in loaded  # the daily sources don't invalidate snapshots


def test_sr_snapshot_matches_the_detector_on_a_young_ticker(configs):
    young = levels.prepare(_bars(n=40, seed=3))
    c = raw_db.get_connection(":memory:")
    raw_db.create_tables(c)
    raw_db.upsert_bars(c, "bars_1d", "YNG", raw_db.YFINANCE_SPLIT_ONLY, young.assign(is_partial=0))
    t = young.index[-1]
    expected = sorted(round(l.center - l.half_width, 9) for l in sr_engine.detect(c, "YNG", configs["sr_line"],
                                                                                    as_of=t).lines
                      if l.state.value != "broken")
    c.close()
    assert sorted(levels.sr_snapshots(young, [t], configs["sr_line"])["lo"].round(9)) == expected


def test_a_price_a_hair_under_a_bracket_edge_counts_as_the_edge():
    idx = pd.bdate_range("2020-01-01", periods=3)
    b = pd.DataFrame({"open": 20.0, "high": 20.0, "low": 20.0, "close": 20.0, "volume": 1.0}, index=idx)
    b["close"] = 19.9999995  # float32 storage / an inexact split ratio (7.000007) leave about this much
    out = levels.bar_levels(b, None, idx)
    day = out[out["date"] == idx[-1]].set_index("kind")["lo"]
    assert np.isclose(day["round_dn_1"], 20) and np.isclose(day["round_up_1"], 25) and np.isclose(day["round_up_2"], 30)


@pytest.mark.parametrize("price, dn, up", [(99.99999995, 100, 110), (19.99999999, 20, 25), (499.99999975, 500, 550),
                                           (95.00001, 95, 100), (20.00001, 20, 25), (19.99, 19, 20)])
def test_the_step_and_the_level_snap_alike(price, dn, up):
    assert np.isclose(levels.round_below(np.array([price]))[0], dn)
    assert np.isclose(levels.round_above(np.array([price]))[0], up)



def test_the_fingerprint_covers_the_tickers_history_override(bars, configs, monkeypatch):
    dates = _as_of_dates(bars)
    before = level_cache.fingerprint("avwap", TICKER, bars, None, dates, configs["avwap"])
    monkeypatch.delitem(level_cache.HISTORY_RESET_OVERRIDES, TICKER, raising=False)
    none = level_cache.fingerprint("avwap", TICKER, bars, None, dates, configs["avwap"])
    monkeypatch.setitem(level_cache.HISTORY_RESET_OVERRIDES, TICKER, None)  # "never reset" isn't "no entry"
    assert level_cache.fingerprint("avwap", TICKER, bars, None, dates, configs["avwap"]) != none
    monkeypatch.setitem(level_cache.HISTORY_RESET_OVERRIDES, TICKER, "2015-06-01")
    assert level_cache.fingerprint("avwap", TICKER, bars, None, dates, configs["avwap"]) != before


def test_build_is_resumable_and_reruns_merge_into_the_manifest(tmp_path):
    c = raw_db.get_connection(":memory:")
    raw_db.create_tables(c)
    for i, t in enumerate(("AAA", "BBB")):
        raw_db.upsert_bars(c, "bars_1d", t, raw_db.YFINANCE_SPLIT_ONLY,
                           _bars(n=260, seed=20 + i, start="2020-01-01").assign(is_partial=0))
    first = level_cache.build_level_cache(c, ["AAA"], tmp_path, "2021-12-31", workers=1, progress=None)
    stamp = level_cache.snapshot_path(tmp_path, "sr_line", "AAA").stat().st_mtime_ns
    second = level_cache.build_level_cache(c, ["AAA", "BBB", "ZZZ"], tmp_path, "2021-12-31", workers=1,
                                           progress=None)
    c.close()
    assert first["n_tickers"] == 1 and set(second["tickers"]) == {"AAA", "BBB"}
    assert second["tickers"]["AAA"] == first["tickers"]["AAA"]
    assert level_cache.snapshot_path(tmp_path, "sr_line", "AAA").stat().st_mtime_ns == stamp  # a hit, not rewritten
    assert second["no_bars"] == ["ZZZ"] and second["failed"] == {}
    assert sum(second["rows"].values()) > 0


def test_the_manifest_merge_holds_the_lock_under_its_existing_name(tmp_path, monkeypatch):
    # Builds agree on the lock by its file name: a build running older code locks this one.
    lock_path = tmp_path / "manifest.json.lock"
    held = []
    merge = level_cache._merge_manifest

    def checked_merge(*a):
        with lock_path.open("w") as other:  # as another process would try it
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
                fcntl.flock(other, fcntl.LOCK_UN)
            except BlockingIOError:
                held.append(True)
        return merge(*a)

    monkeypatch.setattr(level_cache, "_merge_manifest", checked_merge)
    c = raw_db.get_connection(":memory:")
    raw_db.create_tables(c)
    raw_db.upsert_bars(c, "bars_1d", "AAA", raw_db.YFINANCE_SPLIT_ONLY,
                       _bars(n=260, seed=20, start="2020-01-01").assign(is_partial=0))
    level_cache.build_level_cache(c, ["AAA"], tmp_path, "2021-12-31", workers=1, progress=None)
    c.close()
    assert held == [True]  # the merge ran under that lock


def test_a_run_of_some_sources_keeps_the_others_records(tmp_path, monkeypatch):
    c = raw_db.get_connection(":memory:")
    raw_db.create_tables(c)
    raw_db.upsert_bars(c, "bars_1d", "AAA", raw_db.YFINANCE_SPLIT_ONLY,
                       _bars(n=260, seed=20, start="2020-01-01").assign(is_partial=0))
    full = level_cache.build_level_cache(c, ["AAA"], tmp_path, "2021-12-31", workers=1, progress=None)
    some = level_cache.build_level_cache(c, ["AAA"], tmp_path, "2021-12-31", workers=1, progress=None,
                                         sources=("avwap",))
    assert some["tickers"]["AAA"] == full["tickers"]["AAA"] and some["rows"] == full["rows"]
    assert some["sources"] == sorted(full["sources"]) and some["last_run"]["sources"] == ["avwap"]
    # A ticker failing now loses its old record, and a version bump drops every old record.
    monkeypatch.setattr(level_cache, "_build_one", _boom)
    failed = level_cache.build_level_cache(c, ["AAA"], tmp_path, "2021-12-31", workers=1, progress=None)
    assert "AAA" not in failed["tickers"] and "AAA" in failed["failed"]
    monkeypatch.setattr(level_cache, "SNAPSHOT_VERSION", level_cache.SNAPSHOT_VERSION + 1)
    monkeypatch.setattr(level_cache, "_build_one", lambda root, t, *a: (t, {"avwap": 1}, 0.0))
    bumped = level_cache.build_level_cache(c, ["AAA"], tmp_path, "2021-12-31", workers=1, progress=None,
                                           sources=("avwap",))
    c.close()
    assert bumped["tickers"] == {"AAA": {"avwap": 1}} and bumped["failed"] == {}
    # A changed config drops that source's old records, not the others'.
    monkeypatch.setattr(level_cache, "_build_one", lambda root, t, *a: (t, {"vp": 2}, 0.0))
    level_cache.build_level_cache(c2 := _one_ticker_db(), ["AAA"], tmp_path, "2021-12-31", workers=1,
                                  progress=None, sources=("vp",))
    real = levels.default_configs
    monkeypatch.setattr(levels, "default_configs",
                        lambda: {**real(), "avwap": dataclasses.replace(real()["avwap"], min_bars=7)})
    monkeypatch.setattr(level_cache, "_build_one", lambda root, t, *a: (t, {"avwap": 3}, 0.0))
    swapped = level_cache.build_level_cache(c2, ["AAA"], tmp_path, "2021-12-31", workers=1,
                                            progress=None, sources=("avwap",))
    c2.close()
    assert swapped["tickers"] == {"AAA": {"avwap": 3, "vp": 2}}


def _one_ticker_db():
    c = raw_db.get_connection(":memory:")
    raw_db.create_tables(c)
    raw_db.upsert_bars(c, "bars_1d", "AAA", raw_db.YFINANCE_SPLIT_ONLY,
                       _bars(n=260, seed=20, start="2020-01-01").assign(is_partial=0))
    return c


def _boom(*a):
    raise RuntimeError("boom")

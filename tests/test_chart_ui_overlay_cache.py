import logging

import numpy as np
import pandas as pd

from src.foundation.market_common.models import Timeframe
from src.ui.chart import overlay_cache
from src.ui.chart.overlays import Guide, Overlay

DAILY = Timeframe.DAILY


def _items():
    idx = pd.bdate_range("2024-01-01", periods=5)
    return [
        Overlay("avwap", "2024-01-01", "AVWAP", "series", idx[0], 10.0, 10.0, None, True,
                hover={"value": 10.0}, series=pd.Series(np.arange(5.0), index=idx)),
        Overlay("patterns", "dbl", "Double top", "segment", idx[0], 9.0, 11.0, 0.7, True,
                points=((idx[0], 11.0), (idx[2], 11.0)), guides=(Guide(idx[1], 9.0, None, 9.0, "dash", "target"),),
                age_bars=2, same_key="k", bullish=False),
    ]


def test_saved_overlays_come_back_whole_under_their_key(tmp_path):
    cache = overlay_cache.OverlayCache(tmp_path / "saved")
    cache.write("ABC", DAILY, "avwap", "key1", _items())
    back = cache.read("ABC", DAILY, "avwap", "key1")
    assert [(o.family, o.item_id, o.lo, o.hi, o.points, o.guides, o.hover) for o in back] == \
           [(o.family, o.item_id, o.lo, o.hi, o.points, o.guides, o.hover) for o in _items()]
    pd.testing.assert_series_equal(back[0].series, _items()[0].series)
    assert cache.read("ABC", DAILY, "avwap", "key2") is None  # another key: a miss
    assert cache.read("ABC", Timeframe.WEEKLY, "avwap", "key1") is None  # never saved
    cache.write("ABC", DAILY, "avwap", "key2", [])
    assert cache.read("ABC", DAILY, "avwap", "key2") == [] and cache.read("ABC", DAILY, "avwap", "key1") is None
    assert [p.name for p in (tmp_path / "saved").iterdir()] == ["ABC_daily_avwap.pkl"]  # one file, no temp left


def test_a_bad_file_is_a_miss_and_a_failed_write_is_only_logged(tmp_path, caplog):
    cache = overlay_cache.OverlayCache(tmp_path)
    cache.path("ABC", DAILY, "gaps").write_bytes(b"not a pickle")
    assert cache.read("ABC", DAILY, "gaps", "key") is None
    blocked = overlay_cache.OverlayCache(tmp_path / "file")
    (tmp_path / "file").write_text("a file where the folder should be")
    with caplog.at_level(logging.WARNING):
        blocked.write("ABC", DAILY, "gaps", "key", [])
    assert "couldn't save overlays" in caplog.text


def test_file_names_are_safe_for_any_ticker(tmp_path):
    cache = overlay_cache.OverlayCache(tmp_path)
    assert cache.path("BRK.B", DAILY, "sr_lines").name == "BRK.B_daily_sr_lines.pkl"
    assert cache.path("../X/Y", DAILY, "sr_lines").parent == tmp_path


def test_the_key_changes_with_the_bars_the_splits_the_vendor_and_the_code():
    idx = pd.bdate_range("2024-01-01", periods=5)
    bars = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}, index=idx)
    splits = pd.DataFrame({"execution_date": ["2024-01-02"], "ratio": [0.5]})
    base = overlay_cache.inputs_digest(bars, None)
    assert overlay_cache.inputs_digest(bars.copy(), None) == base
    assert overlay_cache.inputs_digest(bars.assign(close=1.6), None) != base
    assert overlay_cache.inputs_digest(bars.iloc[:-1], None) != base  # a bar fewer
    assert overlay_cache.inputs_digest(bars, splits) != base
    key = overlay_cache.family_key("gaps", "ABC", DAILY, "yfinance_split_only", base, code="c1")
    assert key != overlay_cache.family_key("gaps", "ABC", DAILY, "tiingo_split_only", base, code="c1")
    assert key != overlay_cache.family_key("gaps", "ABC", DAILY, "yfinance_split_only", base, code="c2")
    assert key != overlay_cache.family_key("fibonacci", "ABC", DAILY, "yfinance_split_only", base, code="c1")
    assert key != overlay_cache.family_key("gaps", "ABC", Timeframe.WEEKLY, "yfinance_split_only", base, code="c1")


def test_the_code_hash_changes_with_any_detector_or_adapter_file(monkeypatch, tmp_path):
    files = ["signals/gaps/detect.py", "foundation/market_common/data.py", "ui/chart/overlays.py", "ui/chart/bars.py"]
    for f in files:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x = 1\n")
    (tmp_path / "ui/chart/app.py").write_text("x = 1\n")
    monkeypatch.setattr(overlay_cache, "_SRC", tmp_path)

    def fresh():
        overlay_cache.code_hash.cache_clear()
        return overlay_cache.code_hash()

    try:
        base = fresh()
        (tmp_path / "ui/chart/app.py").write_text("x = 2\n")  # not a detector: same hash
        assert fresh() == base
        for f in files:
            (tmp_path / f).write_text("x = 2\n")
            changed = fresh()
            assert changed != base
            base = changed
    finally:
        overlay_cache.code_hash.cache_clear()


def test_the_hashed_paths_are_this_repo_s_detectors():
    src = overlay_cache._SRC
    assert (src / "signals" / "gaps" / "detect.py").is_file()
    assert all((src / f).is_file() for f in overlay_cache._CODE_FILES)

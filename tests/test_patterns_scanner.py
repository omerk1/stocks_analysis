import numpy as np
import pandas as pd
import pytest

from src.data_processing import db
from src.market_common.models import Timeframe
from src.patterns.config import PatternConfig
from src.patterns.models import PatternType
from src.patterns.scanner import detect, scan_bars


def _chain(*segments: tuple[float, float, int], start: str = "2020-01-01") -> pd.DataFrame:
    frames = []
    cursor = pd.Timestamp(start)
    for p0, p1, n in segments:
        idx = pd.bdate_range(cursor, periods=n)
        closes = np.linspace(p0, p1, n)
        frames.append(pd.DataFrame(
            {"open": closes, "high": closes + 0.3, "low": closes - 0.3, "close": closes, "volume": 1000.0},
            index=idx,
        ))
        cursor = idx[-1] + pd.Timedelta(days=1)
    return pd.concat(frames)


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, pivot_atr_mult=1.0, volume_sma_period=5, prior_trend_min_bars=5, prior_trend_min_pct=10.0,
        min_bars=0, double_top_typical_min_bars=1, double_top_typical_max_bars=200,
    )
    defaults.update(overrides)
    return PatternConfig(**defaults)


# Same shape as test_patterns_double_top_bottom's fixture, but pivots are
# recovered from real bars via market_common.pivots.detect_pivots rather
# than hand-built -- proves scan_bars' own pivot-extraction wiring, not
# just the detector's logic in isolation.
_DOUBLE_TOP_BARS = _chain((100.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 129.0, 5), (127.0, 100.0, 10))


def test_scan_bars_recovers_double_top_from_real_pivots():
    matches = scan_bars(_DOUBLE_TOP_BARS, "TST", Timeframe.DAILY, _config())

    tops = [m for m in matches if m.pattern_type == PatternType.DOUBLE_TOP]
    assert len(tops) == 1
    m = tops[0]
    assert m.key_levels["p1"] == pytest.approx(130.3)
    assert m.key_levels["neckline"] == pytest.approx(120.7)
    assert m.key_levels["p2"] == pytest.approx(129.3)


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    frame = _DOUBLE_TOP_BARS.reset_index().rename(columns={"index": "timestamp"})
    frame["is_partial"] = 0
    frame = frame.set_index("timestamp")
    db.upsert_bars(connection, "bars_1d", "TST", db.YFINANCE, frame)
    yield connection
    connection.close()


def test_detect_as_of_before_formation_end_excludes_the_pattern(conn):
    # The double top's p2 (bar 19) confirms 2020-01-29 (see
    # test_scan_bars_recovers_double_top_from_real_pivots for the same
    # fixture's pivot bar indices).
    matches, _report, skip = detect(conn, "TST", Timeframe.DAILY, _config(), as_of="2020-01-28")
    assert skip is None
    assert matches == []


def test_detect_as_of_after_formation_end_includes_the_pattern(conn):
    matches, _report, skip = detect(conn, "TST", Timeframe.DAILY, _config(), as_of="2020-01-29")
    assert skip is None
    tops = [m for m in matches if m.pattern_type == PatternType.DOUBLE_TOP]
    assert len(tops) == 1


def test_detect_skips_short_history(conn):
    config = _config(min_bars=10_000)
    matches, report, skip = detect(conn, "TST", Timeframe.DAILY, config)
    assert matches == []
    assert skip is not None
    assert report.rows_loaded == len(_DOUBLE_TOP_BARS)

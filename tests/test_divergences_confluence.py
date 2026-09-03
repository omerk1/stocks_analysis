"""Tests for detect._apply_confluence -- cross-indicator confluence grouping.

Exercised entirely through the public `detect()` entry point (matching this
test suite's existing convention of not importing detect.py's underscore-
prefixed helpers directly, see test_divergences_synthetic.py/
test_divergences_smoke.py), with `detect_divergences` monkeypatched to
return hand-built `Divergence` rows -- this lets each test control exact
p2_date/direction/indicator/confirmed_at combinations precisely, rather than
relying on real talib indicator timing (which, empirically, doesn't reliably
produce two indicators confirming off the exact same swing on a small
hand-built fixture -- confirmed by direct experimentation before writing
these tests).
"""

import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.signals.divergences import detect as detect_mod
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.detect import detect
from src.signals.divergences.models import Direction, Divergence, IndicatorKind
from src.foundation.market_common.models import Timeframe


@pytest.fixture
def conn():
    # Real bars are only needed so load_and_validate has something to load --
    # detect_divergences itself is monkeypatched per-test, so their content
    # is irrelevant beyond "long enough to pass min_bars and cover every
    # p2_date used below."
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    idx = pd.bdate_range("2020-01-01", periods=60)
    closes = [100.0 + i for i in range(60)]
    frame = pd.DataFrame(
        {
            "timestamp": idx,
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
            "is_partial": [0] * len(closes),
        }
    ).set_index("timestamp")
    db.upsert_bars(connection, "bars_1d", "TST", db.YFINANCE, frame)
    yield connection, idx
    connection.close()


def _config(**overrides) -> DivergenceConfig:
    cfg = DivergenceConfig(min_bars=0, pairing_window=3)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _divergence(
    indicator: str, p2_date: str, confirmed_at: str, direction: Direction = Direction.BEARISH
) -> Divergence:
    return Divergence(
        id=f"id-{indicator}-{p2_date}", ticker="TST", timeframe=Timeframe.DAILY,
        indicator=IndicatorKind(indicator), direction=direction,
        p1_date="2020-01-02T00:00:00", p2_date=p2_date,
        p1_price=100.0, p2_price=90.0, i1_value=80.0, i2_value=70.0,
        strength=0.5, duration_bars=10, price_move_atr=1.0,
        appeared_at=p2_date, confirmed_at=confirmed_at,
    )


def test_two_indicators_agreeing_on_the_same_swing_cluster_together(conn, monkeypatch):
    connection, idx = conn
    p2 = idx[20].isoformat()
    fixed = [
        _divergence("rsi", p2, p2),
        _divergence("macd_hist", idx[21].isoformat(), idx[21].isoformat()),  # 1 bar away, within tolerance
    ]
    monkeypatch.setattr(detect_mod, "detect_divergences", lambda *a, **k: fixed)

    divs, _report, skip = detect(connection, "TST", Timeframe.DAILY, _config(), as_of=idx[25].isoformat())

    assert skip is None
    assert len(divs) == 2
    for d in divs:
        assert d.confluence_count == 2
        assert d.agreeing_indicators == "macd_hist,rsi"


def test_three_indicators_agreeing_all_cluster_together(conn, monkeypatch):
    connection, idx = conn
    fixed = [
        _divergence("rsi", idx[20].isoformat(), idx[20].isoformat()),
        _divergence("macd_hist", idx[21].isoformat(), idx[21].isoformat()),
        _divergence("obv", idx[22].isoformat(), idx[22].isoformat()),
    ]
    monkeypatch.setattr(detect_mod, "detect_divergences", lambda *a, **k: fixed)

    divs, _report, skip = detect(connection, "TST", Timeframe.DAILY, _config(), as_of=idx[25].isoformat())

    assert skip is None
    assert len(divs) == 3
    for d in divs:
        assert d.confluence_count == 3
        assert d.agreeing_indicators == "macd_hist,obv,rsi"


def test_a_lone_divergence_reports_confluence_count_one(conn, monkeypatch):
    connection, idx = conn
    fixed = [_divergence("rsi", idx[20].isoformat(), idx[20].isoformat())]
    monkeypatch.setattr(detect_mod, "detect_divergences", lambda *a, **k: fixed)

    divs, _report, skip = detect(connection, "TST", Timeframe.DAILY, _config(), as_of=idx[25].isoformat())

    assert skip is None
    assert len(divs) == 1
    assert divs[0].confluence_count == 1
    assert divs[0].agreeing_indicators == "rsi"


def test_pivots_beyond_pairing_window_do_not_cluster(conn, monkeypatch):
    connection, idx = conn
    # pairing_window=3 (see _config): a 4-bar gap is one bar too far.
    fixed = [
        _divergence("rsi", idx[20].isoformat(), idx[20].isoformat()),
        _divergence("macd_hist", idx[24].isoformat(), idx[24].isoformat()),
    ]
    monkeypatch.setattr(detect_mod, "detect_divergences", lambda *a, **k: fixed)

    divs, _report, skip = detect(connection, "TST", Timeframe.DAILY, _config(), as_of=idx[25].isoformat())

    assert skip is None
    assert len(divs) == 2
    for d in divs:
        assert d.confluence_count == 1
        assert d.agreeing_indicators == d.indicator.value


def test_a_gap_of_exactly_pairing_window_still_clusters(conn, monkeypatch):
    connection, idx = conn
    # Inclusive boundary: a 3-bar gap, exactly config.pairing_window, must
    # still cluster (only a gap strictly greater than the tolerance breaks
    # a cluster -- see detect._apply_confluence).
    fixed = [
        _divergence("rsi", idx[20].isoformat(), idx[20].isoformat()),
        _divergence("macd_hist", idx[23].isoformat(), idx[23].isoformat()),
    ]
    monkeypatch.setattr(detect_mod, "detect_divergences", lambda *a, **k: fixed)

    divs, _report, skip = detect(connection, "TST", Timeframe.DAILY, _config(), as_of=idx[25].isoformat())

    assert skip is None
    assert len(divs) == 2
    for d in divs:
        assert d.confluence_count == 2


def test_different_directions_at_the_same_bar_do_not_cluster(conn, monkeypatch):
    connection, idx = conn
    p2 = idx[20].isoformat()
    fixed = [
        _divergence("rsi", p2, p2, direction=Direction.BEARISH),
        _divergence("macd_hist", p2, p2, direction=Direction.BULLISH),
    ]
    monkeypatch.setattr(detect_mod, "detect_divergences", lambda *a, **k: fixed)

    divs, _report, skip = detect(connection, "TST", Timeframe.DAILY, _config(), as_of=idx[25].isoformat())

    assert skip is None
    assert len(divs) == 2
    for d in divs:
        assert d.confluence_count == 1


def test_confluence_never_counts_a_same_pivot_divergence_confirming_after_as_of(conn, monkeypatch):
    # The core zero-lookahead guarantee: rsi confirms early, macd_hist off
    # the same swing confirms later. As-of a date before macd_hist's own
    # confirmation, the visible rsi row must NOT report confluence with a
    # divergence that wasn't knowable yet.
    connection, idx = conn
    p2 = idx[20].isoformat()
    early_confirm = idx[20].isoformat()
    late_confirm = idx[35].isoformat()
    fixed = [
        _divergence("rsi", p2, early_confirm),
        _divergence("macd_hist", p2, late_confirm),
    ]
    monkeypatch.setattr(detect_mod, "detect_divergences", lambda *a, **k: fixed)

    divs_before, _report, skip = detect(
        connection, "TST", Timeframe.DAILY, _config(), as_of=idx[25].isoformat()
    )
    assert skip is None
    assert len(divs_before) == 1
    assert divs_before[0].indicator == IndicatorKind.RSI
    assert divs_before[0].confluence_count == 1
    assert divs_before[0].agreeing_indicators == "rsi"

    divs_after, _report, skip = detect(
        connection, "TST", Timeframe.DAILY, _config(), as_of=idx[40].isoformat()
    )
    assert skip is None
    assert len(divs_after) == 2
    for d in divs_after:
        assert d.confluence_count == 2
        assert d.agreeing_indicators == "macd_hist,rsi"

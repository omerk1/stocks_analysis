from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Timeframe
from src.signals.avwap.models import AnchorStatus, AnchorType
from src.signals.fibonacci.models import FibLevelKind, FibSetStatus, SwingDirection
from src.signals.gaps.models import Direction, GapKind, GapStatus
from src.signals.sr_lines.models import LineKind, LineState
from src.ui.chart import overlays

DAILY = Timeframe.DAILY


@pytest.fixture
def bars():
    idx = pd.bdate_range("2024-01-01", periods=50)
    close = np.linspace(90, 110, 50)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close,
                         "volume": 1000.0}, index=idx)


def _line(center, state, kind=LineKind.HORIZONTAL):
    return NS(kind=kind, center=center, half_width=0.5, state=state, strength=0.4, first_touch="2024-01-10T00:00:00",
              last_event="2024-02-01T00:00:00", touch_counts=NS(total=4))


def test_sr_zones_side_by_last_close_and_broken_lines_dead(monkeypatch):
    lines = [_line(95.0, LineState.ACTIVE), _line(105.0, LineState.FLIPPED), _line(100.0, LineState.BROKEN),
             _line(101.0, LineState.ACTIVE, kind=LineKind.DIAGONAL)]
    monkeypatch.setattr(overlays.sr_engine, "detect", lambda conn, ticker, config: NS(lines=lines))
    out = overlays.sr_overlays(None, "ABC", DAILY, close=100.0)
    assert len(out) == 6  # 3 horizontal lines x both presets; the diagonal is skipped
    first = out[:3]
    # the zone around the close is neither side of it
    assert [o.label for o in first] == ["Support 95.00", "Resistance 105.00 (flipped)", "At price 100.00"]
    assert [o.tag for o in first] == ["S", "R", "S/R"]
    assert [o.alive for o in first] == [True, True, False]
    assert (first[0].lo, first[0].hi, first[0].kind) == (94.5, 95.5, "zone")
    assert first[0].item_id != out[3].item_id  # one id per preset


@pytest.mark.parametrize("direction, fill, expected", [
    (Direction.BULLISH, 0.0, (10.0, 20.0)), (Direction.BULLISH, 30.0, (10.0, 17.0)),
    (Direction.BEARISH, 30.0, (13.0, 20.0)), (Direction.BEARISH, 150.0, (20.0, 20.0)),
])
def test_remaining_zone_is_the_unfilled_part(direction, fill, expected):
    assert overlays.remaining_zone(10.0, 20.0, direction, fill) == pytest.approx(expected)


def test_gaps_open_and_partial_are_alive(monkeypatch):
    def gap(status, fill):
        return NS(zone_bottom=10.0, zone_top=20.0, direction=Direction.BULLISH, max_fill_pct=fill, kind=GapKind.FVG,
                  created_at=f"2024-01-{10 + int(fill / 10):02d}T00:00:00", size_atr=1.5, status=status,
                  n_approaches=1)
    found = [gap(GapStatus.OPEN, 0.0), gap(GapStatus.PARTIAL, 40.0), gap(GapStatus.SOFT_CLOSED, 80.0),
             gap(GapStatus.CLOSED, 100.0)]
    monkeypatch.setattr(overlays.gap_detect, "detect", lambda *a, **k: (found, None, None))
    out = overlays.gap_overlays(None, "ABC", DAILY)
    assert [o.alive for o in out] == [True, True, False, False]
    assert (out[1].lo, out[1].hi) == pytest.approx((10.0, 16.0))
    assert out[1].strength == 1.5 and out[1].tag == "FVG"


def test_avwap_curve_from_its_anchor_and_stale_is_dead(monkeypatch, bars):
    def anchor(date, status):
        return NS(anchor_date=date, current_value=101.0, anchor_types=frozenset({AnchorType.CYCLE_LOW}),
                  status=status, n_crosses=2, avg_reaction_atr_on_touch=None)
    found = [anchor("2024-02-01T00:00:00", AnchorStatus.ACTIVE), anchor("2024-01-15T00:00:00", AnchorStatus.STALE)]
    monkeypatch.setattr(overlays.avwap_anchors, "detect", lambda *a, **k: (found, None, None))
    out = overlays.avwap_overlays(None, "ABC", DAILY, bars)
    assert [o.alive for o in out] == [True, False]
    curve = out[0].series
    assert curve.loc[:"2024-01-31"].isna().all() and curve.loc["2024-02-01":].notna().all()
    assert out[0].kind == "series" and out[0].strength is None
    assert out[1].series is None  # a dead anchor isn't listed, so its curve isn't computed


def test_avwap_without_a_module_value_falls_back_to_its_curve(monkeypatch, bars):
    found = [NS(anchor_date="2024-02-01T00:00:00", current_value=None, anchor_types=frozenset({AnchorType.ATH}),
                status=AnchorStatus.ACTIVE, n_crosses=0, avg_reaction_atr_on_touch=None)]
    monkeypatch.setattr(overlays.avwap_anchors, "detect", lambda *a, **k: (found, None, None))
    (o,) = overlays.avwap_overlays(None, "ABC", DAILY, bars)
    assert o.lo == pytest.approx(o.series.iloc[-1])
    assert np.isnan(overlays._avwap_value(None, None))  # no value at all: out of reach, not a failure


def test_fib_levels_alive_while_their_swing_is(monkeypatch):
    swing = NS(origin_date="2023-01-02", end_date="2023-06-01", scale_mult=4.0, direction=SwingDirection.UP)
    levels = [NS(ratio=0.382, kind=FibLevelKind.RETRACEMENT, price=95.0, n_touches=1, n_violations=0),
              NS(ratio=0.618, kind=FibLevelKind.RETRACEMENT, price=90.0, n_touches=0, n_violations=0)]
    sets = [NS(swing=swing, levels=levels, weight=0.5, status=FibSetStatus.ACTIVE),
            NS(swing=NS(**{**vars(swing), "scale_mult": 8.0}), levels=levels[:1], weight=0.4,
               status=FibSetStatus.INVALIDATED)]
    monkeypatch.setattr(overlays.fib_engine, "detect", lambda *a, **k: NS(selected_sets=sets))
    out = overlays.fib_overlays(None, "ABC", DAILY)
    assert [o.alive for o in out] == [True, True, False]
    assert len({o.item_id for o in out}) == 3
    assert (out[0].kind, out[0].lo, out[0].x0) == ("hline", 95.0, pd.Timestamp("2023-06-01"))


def test_one_family_failing_keeps_the_others(monkeypatch, bars):
    monkeypatch.setattr(overlays, "sr_overlays", lambda *a: [])
    monkeypatch.setattr(overlays, "gap_overlays", lambda *a: (_ for _ in ()).throw(ValueError("boom")))
    monkeypatch.setattr(overlays, "avwap_overlays", lambda *a: ["avwap item"])
    monkeypatch.setattr(overlays, "fib_overlays", lambda *a: ["fib item"])
    monkeypatch.setattr(overlays, "divergence_overlays", lambda *a: ["div item"])
    monkeypatch.setattr(overlays, "volume_profile_overlays", lambda *a: ["vp item"])
    monkeypatch.setattr(overlays, "structure_overlays", lambda *a: ["ms item"])
    items, errors = overlays.all_overlays(None, "ABC", DAILY, bars)
    assert items == ["avwap item", "fib item", "vp item", "div item", "ms item"]
    assert errors == {"gaps": "ValueError: boom"}


def _div(p1, p2, confirmed, indicator="rsi", direction=Direction.BULLISH, hidden=False, invalidated=False):
    from src.signals.divergences.models import DivergenceForm, IndicatorKind
    return NS(p1_date=f"{p1}T00:00:00", p2_date=f"{p2}T00:00:00", confirmed_at=f"{confirmed}T00:00:00",
              p1_price=100.0, p2_price=95.0, i1_value=30.0, i2_value=35.0, strength=0.6,
              indicator=IndicatorKind(indicator), direction=direction,
              form=DivergenceForm.HIDDEN if hidden else DivergenceForm.REGULAR,
              invalidated=invalidated, invalidated_at="2024-03-05T00:00:00" if invalidated else None,
              confluence_count=2)


def test_divergences_are_segments_aged_by_confirmation(monkeypatch, bars):
    divs = [_div("2024-01-15", "2024-02-01", "2024-02-06"),
            _div("2024-01-15", "2024-02-01", "2024-02-07", indicator="macd_hist"),
            _div("2024-01-20", "2024-02-20", "2024-02-26", indicator="obv", direction=Direction.BEARISH,
                 hidden=True, invalidated=True)]
    monkeypatch.setattr(overlays.div_detect, "detect_divergences", lambda *a, **k: divs)
    monkeypatch.setattr(overlays.div_detect, "_apply_confluence", lambda *a, **k: None)
    config = overlays.DivergenceConfig
    monkeypatch.setattr(overlays, "DivergenceConfig", lambda: config(min_bars=10))
    rsi, macd, obv = overlays.divergence_overlays(None, "ABC", DAILY, bars)
    assert rsi.kind == "segment" and rsi.points == ((pd.Timestamp("2024-01-15"), 100.0),
                                                     (pd.Timestamp("2024-02-01"), 95.0))
    assert (rsi.pane, rsi.pane_points[1]) == ("rsi", (pd.Timestamp("2024-02-01"), 35.0))
    assert macd.pane == "macd" and obv.pane is None  # OBV has no pane: drawn on price only
    last = bars.index[-1]
    assert rsi.age_bars == len(bars.loc[pd.Timestamp("2024-02-06"):last]) - 1
    assert rsi.same_key == macd.same_key != obv.same_key  # same pivot, two indicators: one event
    assert (rsi.alive, obv.alive, obv.dashed, obv.bullish) == (True, False, True, False)
    assert rsi.tag == "RSI↑" and obv.tag == "OBV↓h"
    monkeypatch.setattr(overlays, "DivergenceConfig", lambda: config(min_bars=150))  # too few bars: none
    assert overlays.divergence_overlays(None, "ABC", DAILY, bars) == []


def test_volume_profile_gives_poc_and_value_area_edges_per_anchor(monkeypatch, bars):
    profiles = [NS(anchor_date="2024-01-10T00:00:00", anchor_types={AnchorType.ATH}, status=AnchorStatus.ACTIVE,
                   poc=None, vah=None, val=None, n_bars=0, value_area_position=None),
                NS(anchor_date="2024-02-01T00:00:00", anchor_types={AnchorType.ATL}, status=AnchorStatus.STALE,
                   poc=None, vah=None, val=None, n_bars=0, value_area_position=None)]

    def snapshot(bars, atr, p, config):
        p.poc, p.vah, p.val, p.n_bars, p.value_area_position = 100.0, 104.0, 97.0, 30, "inside"
        return p

    config = overlays.VolumeProfileConfig
    monkeypatch.setattr(overlays, "VolumeProfileConfig", lambda: config(min_bars=10))
    monkeypatch.setattr(overlays.history_breaks, "anchor_start_for", lambda *a: None)
    monkeypatch.setattr(overlays.vp_detect, "discover_profiles", lambda *a, **k: profiles)
    monkeypatch.setattr(overlays.vp_detect, "apply_snapshot", snapshot)
    out = overlays.volume_profile_overlays(None, "ABC", DAILY, bars)
    assert [(o.tag, o.lo, o.kind) for o in out[:3]] == [("POC", 100.0, "hline"), ("VAH", 104.0, "hline"),
                                                        ("VAL", 97.0, "hline")]
    assert [o.alive for o in out] == [True] * 3 + [False] * 3  # a stale anchor's lines are dead, like AVWAP
    assert out[0].x0 == pd.Timestamp("2024-01-10") and out[0].strength is None
    assert len({o.item_id for o in out}) == 6


def test_market_structure_events_are_segments_at_the_broken_pivot(monkeypatch, bars):
    from src.foundation.market_common.models import PivotKind
    from src.signals.market_structure.models import StructureEvent

    def event(kind, direction, pivot_day, broken_day, level):
        return NS(event=kind, direction=direction, broken_at=f"{broken_day}T00:00:00", close=level + 1,
                  volume_confirmed=False,
                  broken_pivot=NS(timestamp=f"{pivot_day}T00:00:00", value=level, kind=PivotKind.HIGH))

    events = [event(StructureEvent.CHOCH, Direction.BULLISH, "2024-01-10", "2024-02-01", 95.0),
              event(StructureEvent.BOS, Direction.BULLISH, "2024-02-15", "2024-03-01", 105.0)]
    config = overlays.MarketStructureConfig
    monkeypatch.setattr(overlays, "MarketStructureConfig", lambda: config(min_bars=10))
    monkeypatch.setattr(overlays, "detect_pivots", lambda *a, **k: [])
    monkeypatch.setattr(overlays.ms_detect, "track_market_structure", lambda *a: events)
    choch, bos = overlays.structure_overlays("ABC", DAILY, bars)
    assert choch.points == ((pd.Timestamp("2024-01-10"), 95.0), (pd.Timestamp("2024-02-01"), 95.0))
    assert (choch.tag, choch.dashed, bos.tag, bos.dashed) == ("CHoCH↑", False, "BOS↑", True)
    assert choch.alive and bos.alive and choch.strength is None  # facts: no lifecycle, recency only
    assert bos.age_bars == len(bars.loc["2024-03-01":]) - 1
    assert "trend now" in bos.hover and "trend now" not in choch.hover  # only the latest says the trend
    assert overlays.MS in overlays.EVENT_FAMILIES and overlays.VP not in overlays.EVENT_FAMILIES

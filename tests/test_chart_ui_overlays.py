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
    monkeypatch.setattr(overlays, "pattern_overlays", lambda *a: ["pattern item"])
    items, errors = overlays.all_overlays(None, "ABC", DAILY, bars)
    assert items == ["avwap item", "fib item", "vp item", "pattern item", "div item", "ms item"]  # menu order
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
    monkeypatch.setattr(overlays.div_detect, "detect_on_bars", lambda *a, **k: divs)
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
    def profile(day, status, poc=100.0):
        return NS(anchor_date=f"{day}T00:00:00", anchor_types={AnchorType.ATH}, status=status, poc=poc,
                  vah=104.0, val=97.0, n_bars=30, value_area_position="inside")

    profiles = [profile("2024-01-10", AnchorStatus.ACTIVE), profile("2024-02-01", AnchorStatus.STALE),
                profile("2024-02-15", AnchorStatus.ACTIVE, poc=None)]  # no profile built: skipped
    config = overlays.VolumeProfileConfig
    monkeypatch.setattr(overlays, "VolumeProfileConfig", lambda: config(min_bars=10))
    monkeypatch.setattr(overlays.history_breaks, "anchor_start_for", lambda *a: None)
    monkeypatch.setattr(overlays.vp_detect, "detect_on_bars", lambda *a, **k: profiles)
    out = overlays.volume_profile_overlays(None, "ABC", DAILY, bars)
    assert [(o.tag, o.lo, o.kind) for o in out[:3]] == [("POC Jan 24", 100.0, "hline"), ("VAH Jan 24", 104.0, "hline"),
                                                        ("VAL Jan 24", 97.0, "hline")]
    assert [o.alive for o in out] == [True] * 3 + [False] * 3  # alive follows the anchor's status
    assert out[0].x0 == pd.Timestamp("2024-01-10") and out[0].strength is None
    assert len({o.item_id for o in out}) == 6
    assert out[0].hover is not out[1].hover  # one dict per line


def test_market_structure_events_are_segments_at_the_broken_pivot(monkeypatch, bars):
    from src.foundation.market_common.models import PivotKind
    from src.signals.market_structure.models import StructureEvent

    def event(kind, direction, pivot_day, broken_day, level):
        return NS(event=kind, direction=direction, broken_at=f"{broken_day}T00:00:00", close=level + 1,
                  volume_confirmed=False,
                  broken_pivot=NS(timestamp=f"{pivot_day}T00:00:00", value=level, kind=PivotKind.HIGH))

    events = [event(StructureEvent.CHOCH, Direction.BULLISH, "2024-01-10", "2024-02-01", 95.0),
              event(StructureEvent.BOS, Direction.BULLISH, "2024-02-15", "2024-03-01", 105.0)]
    presets = []
    real = overlays.ms_config.get_preset
    monkeypatch.setattr(overlays.ms_config, "get_preset",
                        lambda name: presets.append(name) or NS(**{**real(name).to_dict(), "min_bars": 10}))
    monkeypatch.setattr(overlays.ms_detect, "detect_on_bars", lambda *a: events)
    choch, bos = overlays.structure_overlays("ABC", DAILY, bars)
    assert presets == ["daily"]  # the module's own preset per timeframe
    assert real("weekly").min_bars < real("daily").min_bars
    assert choch.points == ((pd.Timestamp("2024-01-10"), 95.0), (pd.Timestamp("2024-02-01"), 95.0))
    assert (choch.tag, choch.dashed, bos.tag, bos.dashed) == ("CHoCH↑", False, "BOS↑", True)
    assert choch.alive and bos.alive and choch.strength is None  # facts: no lifecycle, recency only
    assert bos.age_bars == len(bars.loc["2024-03-01":]) - 1
    assert "trend now" in bos.hover and "trend now" not in choch.hover  # only the latest says the trend
    assert overlays.MS in overlays.EVENT_FAMILIES and overlays.VP not in overlays.EVENT_FAMILIES


def _match(bars, kind, direction, status, pivot_bars, breakout=None, key_levels=None, trendlines=None,
           target=None):
    from src.foundation.market_common.models import Direction as Dir
    from src.signals.patterns.models import PatternStatus, PatternType
    pivots = [NS(bar_index=i, timestamp=str(bars.index[i]), price=float(bars["close"].iloc[i])) for i in pivot_bars]
    return NS(pattern_type=PatternType(kind), direction=Dir(direction), status=PatternStatus(status), pivots=pivots,
              breakout_bar=breakout, key_levels=key_levels or {}, trendlines=trendlines or {}, target_price=target,
              stop_price=None, confidence=0.6, volume_confirmed=True, formation_start=pivots[0].timestamp,
              formation_end=pivots[-1].timestamp)


def test_live_chart_patterns_are_outlines_with_trigger_and_target(monkeypatch, bars):
    double = _match(bars, "double_bottom", "bullish", "active", [10, 20, 30], breakout=40,
                    key_levels={"neckline": 99.0, "neckline_bar": 20.0}, target=120.0)
    triangle = _match(bars, "symmetric_triangle", "neutral", "pending", [5, 15, 25, 35],
                      trendlines={"upper": (-0.1, 110.0), "lower": (0.1, 90.0)})
    triple = _match(bars, "triple_bottom", "bullish", "active", [0, 10, 20, 30], breakout=41,
                    key_levels={"neckline": 99.0, "neckline_bar": 20.0})
    dead = _match(bars, "double_top", "bearish", "hit_target", [10, 20, 30], breakout=35)
    scanned = []
    real = overlays.pattern_config.get_preset
    monkeypatch.setattr(overlays.pattern_config, "get_preset",
                        lambda name: NS(**{**real(name).to_dict(), "min_bars": 10}))
    monkeypatch.setattr(overlays.pattern_scanner, "scan_bars",
                        lambda window, *a: scanned.append(len(window)) or [double, triangle, triple, dead])
    out = overlays.pattern_overlays("ABC", DAILY, bars)
    assert [o.tag for o in out] == ["2Bot↑", "SymTri", "3Bot↑"]  # hit target: no longer live
    d, t, tr = out
    assert d.kind == "segment" and len(d.points) == 3 and d.strength == 0.6
    assert d.age_bars == len(bars) - 1 - 40  # since the breakout
    assert t.age_bars == len(bars) - 1 - 35 and t.bullish is None  # pending: since its last pivot
    trigger, target = d.guides
    assert trigger == overlays.Guide(bars.index[20], 99.0, bars.index[40], 99.0)  # neckline up to the breakout
    assert (target.x0, target.y0, target.to_edge, target.text) == (bars.index[40], 120.0, True, "2Bot↑ target")
    assert d.hi < 120.0 and d.x_end == bars.index[40]  # the target isn't in lo/hi, nor in how long they count
    upper, lower = t.guides  # a triangle's two sides, from its first pivot to the last bar
    assert (upper.x0, upper.y0, upper.x1) == (bars.index[5], 109.5, bars.index[-1])
    assert set(t.hover) >= {"upper side", "lower side"} and "trigger" in d.hover
    assert d.same_key == tr.same_key != t.same_key  # double and triple bottom on one swing: one event
    assert d.item_id == f"double_bottom:{bars.index[10]:%Y-%m-%d}:{bars.index[30]:%Y-%m-%d}"  # no direction
    assert overlays.PAT in overlays.EVENT_FAMILIES and scanned == [len(bars)]


def test_one_pending_pattern_found_from_two_windows_is_one_event(bars):
    a = _match(bars, "ascending_triangle", "bullish", "pending", [5, 15, 25, 35])
    b = _match(bars, "ascending_triangle", "bullish", "pending", [15, 25, 35, 45])  # 3 of 5 pivots shared
    other = _match(bars, "rising_wedge", "bullish", "pending", [15, 25, 35, 44])  # another type: its own
    flipped = _match(bars, "ascending_triangle", "bearish", "pending", [15, 25, 35, 46])
    ka, kb, ko, kf = overlays._event_keys([a, b, other, flipped])
    assert ka == kb and len({ka, ko, kf}) == 3


def test_chart_patterns_scan_the_recent_bars_and_everything_near_the_edge(monkeypatch):
    idx = pd.bdate_range("2000-01-03", periods=overlays.PATTERN_SCAN_BARS + 500)
    long = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)
    windows, found = [], []
    monkeypatch.setattr(overlays.pattern_scanner, "scan_bars", lambda window, *a: windows.append(window) or found)
    overlays.pattern_overlays("ABC", DAILY, long)
    assert len(windows) == 1 and len(windows[0]) == overlays.PATTERN_SCAN_BARS and windows[0].index[-1] == idx[-1]
    window = long.iloc[-overlays.PATTERN_SCAN_BARS:]
    found.append(_match(window, "rounding_bottom", "bullish", "pending", [10, 400, 900]))  # starts at the edge
    windows.clear()
    overlays.pattern_overlays("ABC", DAILY, long)
    assert [len(w) for w in windows] == [overlays.PATTERN_SCAN_BARS, len(long)]  # rescanned whole

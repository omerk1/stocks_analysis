"""One adapter per indicator family: a module's own detector -> `Overlay`s, the one
shape the menu, the ranking (`relevance.py`) and the drawing (`figure.py`) share.

Every family runs its own detector live on the ticker's bars, as of the last bar,
instead of reading the derived database:

- `sr_lines` and `fib_sets` have no stored rows (both tables are empty), and
- the stored `gaps` / `avwap_anchors` rows are only as fresh as their last batch
  run, which can be behind the bars on the chart (a gap made since would be missing,
  and one filled since would still look open).

Every module here works on the traded basis, the same bars the chart draws
(`bars.CHART_BASIS`). S/R, gaps, AVWAP and Fibonacci load them through their own
`detect`; volume profile, chart patterns, divergences and market structure run their
module's steps on the chart's bars, so they aren't loaded twice. A run takes from a fraction of a
second (S/R, volume profile) to several (gaps over the whole daily history, Fibonacci
on weekly), so the app caches the result per ticker and timeframe.

This is current state as of the last bar, which is all the first version shows (no
as-of picker: `docs/features/chart_ui_design.md`, "Look-ahead and the holdout").
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from typing import NamedTuple

import pandas as pd

from src.foundation.market_common import history_breaks
from src.foundation.market_common.models import Timeframe
from src.signals.avwap import anchors as avwap_anchors
from src.signals.avwap import compute as avwap_compute
from src.signals.avwap.config import AvwapConfig
from src.signals.avwap.models import AnchorStatus
from src.signals.divergences import detect as div_detect
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.models import DivergenceForm
from src.signals.fibonacci import engine as fib_engine
from src.signals.fibonacci.config import FibConfig
from src.signals.fibonacci.models import FibSetStatus
from src.signals.gaps import detect as gap_detect
from src.signals.gaps.config import GapConfig
from src.signals.gaps.models import Direction, GapKind, GapStatus
from src.signals.sr_lines import engine as sr_engine
from src.signals.sr_lines.config import get_preset
from src.signals.market_structure import config as ms_config
from src.signals.market_structure import detect as ms_detect
from src.signals.market_structure.models import StructureEvent
from src.signals.patterns import config as pattern_config
from src.signals.patterns import plotting as pattern_plotting
from src.signals.patterns import scanner as pattern_scanner
from src.signals.patterns.models import PatternStatus, PatternType
from src.signals.sr_lines.models import LineKind, LineState
from src.signals.volume_profile import detect as vp_detect
from src.signals.volume_profile.config import VolumeProfileConfig

# Menu order. Display names live with the menu (app.py); these are the stable keys.
SR, GAPS, AVWAP, FIB, VP, PAT, DIV, MS = ("sr_lines", "gaps", "avwap", "fibonacci", "volume_profile", "patterns",
                                          "divergences", "market_structure")
FAMILIES = (SR, GAPS, AVWAP, FIB, VP, PAT, DIV, MS)
FAMILY_NAMES = {SR: "Support / resistance", GAPS: "Gaps / FVG", AVWAP: "Anchored VWAP", FIB: "Fibonacci",
                VP: "Volume profile", PAT: "Chart patterns", DIV: "Divergences", MS: "Market structure"}
EVENT_FAMILIES = frozenset({PAT, DIV, MS})  # ranked by recency (`Overlay.age_bars`), not distance from price

# Short and long lookback, as the S/R module's own presets define them.
SR_PRESETS = {Timeframe.DAILY: ("medium_term", "long_term"),
              Timeframe.WEEKLY: ("medium_term_weekly", "long_term_weekly")}


@dataclass(frozen=True, eq=False)
class Overlay:
    """One drawable item. `lo`/`hi` are its price at the last bar (equal for a line,
    a zone's edges otherwise): what proximity is measured to. `strength` is the
    module's own score, unscaled (None: the family has none). `hover` holds the
    source numbers shown next to the item, so it's clear why it was picked."""
    family: str
    item_id: str
    label: str
    kind: str  # "zone" | "hline" | "series"
    x0: pd.Timestamp  # where the drawing starts; it runs to the right edge
    lo: float
    hi: float
    strength: float | None
    alive: bool
    hover: dict = field(default_factory=dict)
    series: pd.Series | None = None  # kind "series" only
    tag: str = ""  # a few characters drawn on the chart next to the item; `label` is for the menu
    # Kind "segment" (an event drawn between two points, e.g. a divergence's two pivots):
    # its points on the price pane, and optionally on an indicator pane (`pane` = its key
    # in `panes.PANES`), drawn there only while that pane is shown.
    points: tuple = ()  # ((x, y), (x, y))
    pane: str | None = None
    pane_points: tuple = ()
    # An event is ranked by how recent it is, not by distance from price: bars from its
    # confirmation to the last bar (None for levels).
    age_bars: int | None = None
    # Items with the same key in a family are one event (e.g. RSI and MACD divergences on
    # the same pivot) and take one default slot; None: compared by price instead.
    same_key: str | None = None
    bullish: bool | None = None  # an event's direction, for its colour; None: the family's colour
    dashed: bool = False  # a segment drawn dashed (a hidden divergence)
    # Extra straight lines drawn with a segment (`Guide`s), e.g. a chart pattern's trigger
    # line and target.
    guides: tuple = ()

    @property
    def x_end(self):
        """Where the part of a segment that `lo`/`hi` cover ends: its last point or a
        guide that ends on a bar. A guide running to the right edge (a pattern's
        target) isn't in `lo`/`hi`, so it doesn't count."""
        return max([p[0] for p in self.points] + [g.x1 for g in self.guides if not g.to_edge])


class Guide(NamedTuple):
    """A straight line drawn with a segment, from (x0, y0) to (x1, y1); x1 None runs it
    to the chart's right edge. `text` is written at its right end."""
    x0: pd.Timestamp
    y0: float
    x1: pd.Timestamp | None
    y1: float
    dash: str = "dot"
    text: str = ""

    @property
    def to_edge(self) -> bool:
        return self.x1 is None


def _day(ts) -> str:
    return str(ts)[:10]


def sr_overlays(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe, close: float) -> list[Overlay]:
    """Horizontal S/R zones from both presets. Broken lines are dead; a flipped line is
    alive (it has swapped sides). Support or resistance is by side of the last close;
    a zone around the close is "at price"."""
    out = []
    for preset in SR_PRESETS[timeframe]:
        for line in sr_engine.detect(conn, ticker, get_preset(preset)).lines:
            if line.kind != LineKind.HORIZONTAL or line.center is None:
                continue  # diagonals are off in every preset; drawing them waits until they aren't
            lo, hi = line.center - line.half_width, line.center + line.half_width
            side, tag = (("At price", "S/R") if lo <= close <= hi
                         else ("Support", "S") if hi < close else ("Resistance", "R"))
            flipped = " (flipped)" if line.state == LineState.FLIPPED else ""
            touches = line.touch_counts.total
            out.append(Overlay(
                family=SR, item_id=f"{preset}:{_day(line.first_touch)}:{line.center:.4f}",
                label=f"{side} {line.center:.2f}{flipped}", tag=tag, kind="zone",
                x0=pd.Timestamp(line.first_touch),
                lo=lo, hi=hi, strength=float(line.strength), alive=line.state != LineState.BROKEN,
                hover={"strength": round(float(line.strength), 3), "touches": touches,
                       "state": line.state.value, "first touch": _day(line.first_touch),
                       "last event": _day(line.last_event), "preset": preset},
            ))
    return out


def remaining_zone(bottom: float, top: float, direction: Direction, fill_pct: float) -> tuple[float, float]:
    """The part of a gap not yet filled. A bullish gap sits below price and fills from
    its top down; a bearish one sits above and fills from its bottom up."""
    filled = (top - bottom) * min(max(fill_pct, 0.0), 100.0) / 100.0
    return (bottom, top - filled) if direction == Direction.BULLISH else (bottom + filled, top)


def gap_overlays(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe) -> list[Overlay]:
    """Open and partly filled gaps are alive (soft-closed and closed ones aren't), drawn
    as their unfilled part from the bar that made them."""
    gaps, _, _ = gap_detect.detect(conn, ticker, timeframe, GapConfig())
    out = []
    for g in gaps:
        lo, hi = remaining_zone(g.zone_bottom, g.zone_top, g.direction, g.max_fill_pct or 0.0)
        kind = "FVG" if g.kind == GapKind.FVG else "Gap"
        out.append(Overlay(
            family=GAPS, item_id=f"{g.kind.value}:{g.direction.value}:{_day(g.created_at)}",
            label=f"{kind} {'up' if g.direction == Direction.BULLISH else 'down'} {lo:.2f}–{hi:.2f}", tag=kind,
            kind="zone", x0=pd.Timestamp(g.created_at), lo=lo, hi=hi, strength=float(g.size_atr),
            alive=g.status in (GapStatus.OPEN, GapStatus.PARTIAL),
            hover={"size (ATR)": round(float(g.size_atr), 2), "filled %": round(float(g.max_fill_pct or 0.0)),
                   "status": g.status.value, "created": _day(g.created_at), "approaches": g.n_approaches},
        ))
    return out


def _avwap_value(current_value, series: pd.Series | None) -> float:
    """The AVWAP at the last bar: the module's own value, else the curve's last point,
    else NaN (the module leaves it None when no volume has traded since the anchor),
    which reads as out of reach instead of failing the family."""
    if current_value is not None and math.isfinite(float(current_value)):
        return float(current_value)
    if series is not None and series.notna().any():
        return float(series.dropna().iloc[-1])
    return float("nan")


def avwap_overlays(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe,
                   bars: pd.DataFrame) -> list[Overlay]:
    """Active anchors are alive, stale ones aren't. The curve is recomputed on `bars`
    from its anchor, the way the module's own plots do."""
    config = AvwapConfig()
    anchors, _, _ = avwap_anchors.detect(conn, ticker, timeframe, config)
    out = []
    for a in anchors:
        alive = a.status == AnchorStatus.ACTIVE
        # Only alive anchors are listed, so only they need the curve (one series per anchor
        # over the whole history otherwise, held in the app's cache).
        series = avwap_compute.anchored_vwap(bars, a.anchor_date, config.price_source) if alive else None
        value = _avwap_value(a.current_value, series)
        types = ", ".join(sorted(t.value.replace("_", " ") for t in a.anchor_types))
        out.append(Overlay(
            family=AVWAP, item_id=_day(a.anchor_date), label=f"AVWAP {_day(a.anchor_date)} ({types})", tag="AVWAP",
            kind="series", x0=pd.Timestamp(a.anchor_date), lo=value, hi=value, strength=None,
            alive=alive, series=series,
            hover={"value": None if math.isnan(value) else round(value, 2), "crosses": a.n_crosses,
                   "avg reaction on touch (ATR)": None if a.avg_reaction_atr_on_touch is None
                   else round(float(a.avg_reaction_atr_on_touch), 2),
                   "status": a.status.value},
        ))
    return out


def fib_overlays(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe) -> list[Overlay]:
    """Each level of the module's selected swings is an item, drawn from the swing's
    end. A level is alive while its swing isn't invalidated."""
    result = fib_engine.detect(conn, ticker, timeframe, FibConfig())
    out = []
    for s in result.selected_sets:
        sw = s.swing
        swing = f"{_day(sw.origin_date)}→{_day(sw.end_date)}"
        for lvl in s.levels:
            out.append(Overlay(
                family=FIB, item_id=f"{swing}x{sw.scale_mult:g}:{lvl.kind.value}:{lvl.ratio:g}",
                label=f"Fib {lvl.ratio:g} {lvl.price:.2f} ({swing})", tag=f"{lvl.ratio:g}", kind="hline",
                x0=pd.Timestamp(sw.end_date), lo=float(lvl.price), hi=float(lvl.price), strength=None,
                alive=s.status == FibSetStatus.ACTIVE,
                hover={"kind": lvl.kind.value, "swing": f"{swing} {sw.direction.value}",
                       "set weight": round(float(s.weight), 3), "touches": lvl.n_touches,
                       "violations": lvl.n_violations},
            ))
    return out


_DIV_NAMES = {"rsi": "RSI", "macd_hist": "MACD", "obv": "OBV", "volume": "Volume"}
_DIV_PANES = {"rsi": "rsi", "macd_hist": "macd"}  # indicator -> the pane it's drawn on (OBV has none)


def divergence_overlays(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe,
                        bars: pd.DataFrame) -> list[Overlay]:
    """Each divergence is an item, drawn from its first price pivot to its second, and
    on its indicator's pane between the paired indicator pivots' values. Alive unless
    invalidated (price went past the pair's extreme within the module's outcome
    window); ranked by recency (bars since confirmation) and the module's strength.
    Divergences sharing their second pivot (RSI and MACD on the same low) are one event.

    The module stores the indicator pivots' values, not their dates (they pair with
    the price pivots within `pairing_window` bars), so the pane segment is drawn on
    the price pivots' dates.

    Runs the module's `detect_on_bars` on the chart's `bars`, which are on the module's
    basis (traded), instead of loading them again: one load, and each divergence's age
    is counted on the same bars it was found on."""
    config = DivergenceConfig()
    if len(bars) < config.min_bars:
        return []
    divergences = div_detect.detect_on_bars(bars, ticker, timeframe, config)
    out = []
    for d in divergences:
        p1, p2, confirmed = pd.Timestamp(d.p1_date), pd.Timestamp(d.p2_date), pd.Timestamp(d.confirmed_at)
        name = _DIV_NAMES.get(d.indicator.value, d.indicator.value)
        bull = d.direction == Direction.BULLISH
        hidden = d.form == DivergenceForm.HIDDEN
        age = _age(bars, confirmed)  # confirmed on a pivot's confirming bar, one of these bars
        out.append(Overlay(
            family=DIV, item_id=f"{d.indicator.value}:{d.direction.value}:{d.form.value}:{_day(p1)}:{_day(p2)}",
            label=f"{name} {'bullish' if bull else 'bearish'}{' hidden' if hidden else ''} {_day(p2)}",
            tag=f"{name}{'↑' if bull else '↓'}{'h' if hidden else ''}", kind="segment",
            x0=p1, lo=min(d.p1_price, d.p2_price), hi=max(d.p1_price, d.p2_price),
            strength=float(d.strength), alive=not d.invalidated,
            points=((p1, float(d.p1_price)), (p2, float(d.p2_price))),
            pane=_DIV_PANES.get(d.indicator.value), pane_points=((p1, float(d.i1_value)), (p2, float(d.i2_value))),
            age_bars=age, same_key=f"{d.direction.value}:{_day(p2)}", bullish=bull, dashed=hidden,
            hover={"strength": round(float(d.strength), 2), "confirmed on": _day(confirmed),
                   "indicator": f"{d.i1_value:.2f} → {d.i2_value:.2f}", "form": d.form.value,
                   "indicators agreeing": d.confluence_count,
                   "invalidated": _day(d.invalidated_at) if d.invalidated else "no"},
        ))
    return out


def _age(bars: pd.DataFrame, when) -> int:
    """Bars from `when` (one of `bars`' dates, or the first after it) to the last bar."""
    return len(bars) - 1 - min(int(bars.index.searchsorted(pd.Timestamp(when))), len(bars) - 1)


def volume_profile_overlays(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe,
                            bars: pd.DataFrame) -> list[Overlay]:
    """Each anchored profile (the same anchors AVWAP uses) gives three lines from its
    anchor: the point of control (POC) and the value area's edges (VAH, VAL). Lines,
    not a value-area zone: the zone is usually wide (NVDA daily: 166-233) with price
    inside it, so it would always rank first and push the POC out. No strength: ranked
    on proximity. The tag on the chart names the anchor's month ("POC Jan 25"), so
    lines from different profiles can be told apart.

    Alive is the anchor's status, but without the module's stored previous run
    (`previous_anchor_types`) the discovery returns only anchors that still qualify,
    all active, so in practice every line is alive (AVWAP is the same).

    Runs the module's `detect_on_bars` on the chart's `bars`, on the module's basis
    (traded), instead of loading them again."""
    config = VolumeProfileConfig()
    if len(bars) < config.min_bars:
        return []
    start = history_breaks.anchor_start_for(conn, ticker, bars, config.history_breaks)
    out = []
    for p in vp_detect.detect_on_bars(bars, ticker, timeframe, config, history_start=start):
        if p.poc is None:
            continue
        anchor = pd.Timestamp(p.anchor_date)
        types = ", ".join(sorted(t.value.replace("_", " ") for t in p.anchor_types))
        for name, price in (("POC", p.poc), ("VAH", p.vah), ("VAL", p.val)):
            out.append(Overlay(
                family=VP, item_id=f"{_day(anchor)}:{name.lower()}", label=f"{name} {price:.2f} (from {_day(anchor)})",
                tag=f"{name} {anchor:%b %y}", kind="hline", x0=anchor, lo=float(price), hi=float(price),
                strength=None, alive=p.status == AnchorStatus.ACTIVE,
                hover={"POC": round(p.poc, 2), "value area": f"{p.val:.2f}–{p.vah:.2f}",
                       "anchor": f"{_day(anchor)} ({types})", "bars": p.n_bars,
                       "close vs value area": p.value_area_position, "status": p.status.value}))
    return out


def structure_overlays(ticker: str, timeframe: Timeframe, bars: pd.DataFrame) -> list[Overlay]:
    """Each break of structure (BOS, the trend continuing) or change of character
    (CHoCH, the trend flipping) is an event drawn as a line at the broken pivot's
    price, from the pivot to the bar whose close broke it. Facts with no lifecycle, so
    all alive and ranked by recency alone. The latest event's direction is the
    current trend, said in its hover.

    Runs the module's `detect_on_bars` on the chart's `bars` (traded basis), with the
    module's own preset for the timeframe (weekly needs fewer bars)."""
    config = ms_config.get_preset(timeframe.value)
    if len(bars) < config.min_bars:
        return []
    events = ms_detect.detect_on_bars(bars, ticker, timeframe, config)
    out = []
    for n, e in enumerate(events):
        pivot_at, broken_at = pd.Timestamp(e.broken_pivot.timestamp), pd.Timestamp(e.broken_at)
        level = float(e.broken_pivot.value)
        up = e.direction == Direction.BULLISH
        name = "CHoCH" if e.event == StructureEvent.CHOCH else "BOS"
        hover = {"broke": f"{level:.2f} ({e.broken_pivot.kind.value} of {_day(pivot_at)})", "close": round(e.close, 2),
                 "volume confirmed": "yes" if e.volume_confirmed else "no"}
        if n == len(events) - 1:
            hover["trend now"] = "up" if up else "down"
        out.append(Overlay(
            family=MS, item_id=f"{e.event.value}:{e.direction.value}:{_day(broken_at)}",
            label=f"{name} {'up' if up else 'down'} {_day(broken_at)} at {level:.2f}", tag=f"{name}{'↑' if up else '↓'}",
            kind="segment", x0=pivot_at, lo=level, hi=level, strength=None, alive=True,
            points=((pivot_at, level), (broken_at, level)), age_bars=_age(bars, broken_at),
            same_key=f"{e.event.value}:{_day(broken_at)}", bullish=up, dashed=e.event == StructureEvent.BOS,
            hover=hover))
    return out


# Statuses still in play at the last bar: not yet broken out (pending), or broken out
# with the target neither hit nor given up within the module's horizon.
_LIVE_PATTERNS = frozenset({PatternStatus.PENDING, PatternStatus.CONFIRMED, PatternStatus.ACTIVE})
_PATTERN_NAMES = {
    PatternType.DOUBLE_TOP: ("Double top", "2Top"), PatternType.DOUBLE_BOTTOM: ("Double bottom", "2Bot"),
    PatternType.TRIPLE_TOP: ("Triple top", "3Top"), PatternType.TRIPLE_BOTTOM: ("Triple bottom", "3Bot"),
    PatternType.REVERSAL_123: ("1-2-3 reversal", "123"),
    PatternType.HEAD_AND_SHOULDERS: ("Head and shoulders", "H&S"),
    PatternType.INVERSE_HEAD_AND_SHOULDERS: ("Inverse head and shoulders", "iH&S"),
    PatternType.ASCENDING_TRIANGLE: ("Ascending triangle", "AscTri"),
    PatternType.DESCENDING_TRIANGLE: ("Descending triangle", "DescTri"),
    PatternType.SYMMETRIC_TRIANGLE: ("Symmetric triangle", "SymTri"),
    PatternType.RISING_WEDGE: ("Rising wedge", "RWedge"), PatternType.FALLING_WEDGE: ("Falling wedge", "FWedge"),
    PatternType.CUP_AND_HANDLE: ("Cup and handle", "C&H"),
    PatternType.INVERSE_CUP_AND_HANDLE: ("Inverse cup and handle", "iC&H"),
    PatternType.ROUNDING_BOTTOM: ("Rounding bottom", "RBot"), PatternType.ROUNDING_TOP: ("Rounding top", "RTop"),
    PatternType.VCP: ("VCP", "VCP"), PatternType.BULL_FLAG: ("Bull flag", "Flag"),
    PatternType.BEAR_FLAG: ("Bear flag", "Flag"), PatternType.PENNANT: ("Pennant", "Pennant"),
}
# A live pattern's age is its formation, plus up to twice that waiting for a breakout
# (the module's expiry), plus at most 252 bars after it: 3 x formation + 252. The
# longest typical formation is 400 bars (rounding; the module scores length, it doesn't
# cap it), so 8 years leaves room for formations up to ~580 bars. It found the same live
# patterns as the whole history on 10 large caps, daily and weekly, in about 0.7 s
# instead of 2-9 s daily (the scan's cost grows faster than the bar count).
PATTERN_SCAN_BARS = 2000
# A live pattern starting this close to the window's first bar may have been cut short
# by it (an earlier left rim, the ATR warmup, the prior-trend check), so the window is
# doubled until none does. That can't catch a pattern the window cut short that was
# found again from a later start; on 10 large caps none was (same live patterns as the
# whole history).
PATTERN_EDGE_BARS = 250
_TRIGGER_NAMES = {"neckline": "trigger", "upper": "upper side", "lower": "lower side", "point2": "trigger",
                  "pivot_price": "trigger"}


def _live_patterns(ticker: str, timeframe: Timeframe, bars: pd.DataFrame, config) -> tuple[pd.DataFrame, list]:
    """The module's live matches and the frame they were found on: the last
    `PATTERN_SCAN_BARS` bars, doubled while a live match starts near the window's edge."""
    size = PATTERN_SCAN_BARS
    while True:
        window = bars.iloc[-size:]
        live = [m for m in pattern_scanner.scan_bars(window, ticker, timeframe, config)
                if m.status in _LIVE_PATTERNS and len(m.pivots) >= 2]
        if len(window) == len(bars) or all(m.pivots[0].bar_index >= PATTERN_EDGE_BARS for m in live):
            return window, live
        size *= 2


def _event_keys(matches: list) -> list[str]:
    """One key per structure, from two rules that don't chain: matches ending on the
    same pivot in the same direction (a double and a triple top on one peak) share
    that pivot's key; and a pending match takes the key of an earlier pending match of
    the same type and direction whose pivots mostly overlap (one pending triangle found
    from windows a pivot apart: the module merges those only once they share a
    breakout bar, by the same overlap rule). Unbroken on both sides, so two different
    outcomes are never merged."""
    keys = [f"{m.direction.value}:{_day(m.pivots[-1].timestamp)}" for m in matches]
    pending = [m.breakout_bar is None for m in matches]
    out = list(keys)
    for i, a in enumerate(matches):
        if not pending[i]:
            continue
        for j in range(i):
            b = matches[j]
            if (pending[j] and a.pattern_type == b.pattern_type and a.direction == b.direction
                    and pattern_scanner._pivot_jaccard(a, b) >= pattern_scanner._PIVOT_JACCARD_MIN):
                out[i] = keys[j]  # b's own key, not what b took: one hop, no chains
                break
    return out


def pattern_overlays(ticker: str, timeframe: Timeframe, bars: pd.DataFrame) -> list[Overlay]:
    """Each live chart pattern (pending, or broken out with its target still open) is
    an event: its pivots joined as an outline, its trigger line up to the breakout,
    and from the breakout its target to the right edge. Ranked by recency (bars since the
    breakout, or since the last pivot while pending) and the module's confidence.
    Patterns that are one structure (`_event_keys`) take one default slot.

    Runs the module's `scan_bars` on the chart's bars (traded basis), the last
    `PATTERN_SCAN_BARS` of them, with the module's preset for the timeframe."""
    config = pattern_config.get_preset(timeframe.value)
    if len(bars) < config.min_bars:
        return []
    window, matches = _live_patterns(ticker, timeframe, bars, config)
    out, ids = [], set()
    for m, key in zip(matches, _event_keys(matches)):
        name, tag = _PATTERN_NAMES.get(m.pattern_type, (m.pattern_type.value, m.pattern_type.value))
        bull = None if m.direction == Direction.NEUTRAL else m.direction == Direction.BULLISH
        broke = m.breakout_bar is not None
        end = m.breakout_bar if broke else len(window) - 1
        points = tuple((pd.Timestamp(p.timestamp), float(p.price)) for p in m.pivots)
        triggers = {_TRIGGER_NAMES.get(k, k): Guide(window.index[s], y0, window.index[e], y1)
                    for k, (s, y0, e, y1) in pattern_plotting.trigger_lines(m, end, len(window)).items()}
        guides = list(triggers.values())
        # lo/hi (what the y-axis fits) cover the outline and trigger, not the target: a
        # measured move can sit far from price (NVDA weekly: 100 with price at 200).
        prices = [p[1] for p in points] + [y for g in guides for y in (g.y0, g.y1)]
        arrow = {True: "↑", False: "↓", None: ""}[bull]
        if broke and m.target_price is not None:
            target = float(m.target_price)
            guides.append(Guide(window.index[end], target, None, target, "dash", f"{tag}{arrow} target"))
        moment = window.index[end] if broke else points[-1][0]
        state = f"broke out {_day(moment)}" if broke else f"pending since {_day(points[-1][0])}"
        hover = {"confidence": round(m.confidence, 2), "status": m.status.value.replace("_", " "),
                 "formed": f"{_day(m.formation_start)} – {_day(m.formation_end)}"}
        hover.update({k: round(g.y1, 2) for k, g in triggers.items()})  # each line's value at its end
        hover.update({"target": round(m.target_price, 2) if m.target_price is not None else "none",
                      "stop": round(m.stop_price, 2) if m.stop_price is not None else "none"})
        if broke:
            hover["breakout volume"] = "confirmed" if m.volume_confirmed else "not confirmed"
        # No direction in the id: a triangle's is only decided at its breakout, and a
        # ticked pattern must stay ticked when it breaks out. It's added only if two
        # matches would share an id (both directions on the same dates).
        item_id = f"{m.pattern_type.value}:{_day(m.formation_start)}:{_day(m.formation_end)}"
        if item_id in ids:
            item_id += f":{m.direction.value}"
        ids.add(item_id)
        out.append(Overlay(
            family=PAT, item_id=item_id,
            label=f"{name}{' ' + arrow if arrow else ''} {state}", tag=f"{tag}{arrow}", kind="segment",
            x0=points[0][0], lo=min(prices), hi=max(prices), strength=float(m.confidence), alive=True,
            points=points, guides=tuple(guides), age_bars=_age(bars, moment), same_key=key, bullish=bull,
            hover=hover))
    return out


def all_overlays(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe,
                 bars: pd.DataFrame) -> tuple[list[Overlay], dict[str, str]]:
    """Every family's overlays, plus {family: message} for families that failed. One
    family's error doesn't lose the others."""
    close = float(bars["close"].iloc[-1])
    runs = {SR: lambda: sr_overlays(conn, ticker, timeframe, close),
            GAPS: lambda: gap_overlays(conn, ticker, timeframe),
            AVWAP: lambda: avwap_overlays(conn, ticker, timeframe, bars),
            FIB: lambda: fib_overlays(conn, ticker, timeframe),
            VP: lambda: volume_profile_overlays(conn, ticker, timeframe, bars),
            PAT: lambda: pattern_overlays(ticker, timeframe, bars),
            DIV: lambda: divergence_overlays(conn, ticker, timeframe, bars),
            MS: lambda: structure_overlays(ticker, timeframe, bars)}
    overlays, errors = [], {}
    for family in FAMILIES:  # menu order
        try:
            overlays.extend(runs[family]())
        except Exception as e:  # noqa: BLE001 -- the chart and the other families still draw
            errors[family] = f"{type(e).__name__}: {e}"
    return overlays, errors

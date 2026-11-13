"""The chart UI's Dash app (`docs/features/chart_ui_design.md`, steps 1-4 and 6): one
ticker, daily/weekly, line/bars/candles, volume, moving averages, the RS strip, the
level menu with its default "relevant now" picks, the earnings flags and cards, and
the RSI / MACD / RS panes. A second tab, Groups, ranks the sectors and lists a
sector's members; click a member to open its chart.

    python -m src.ui.chart.app [--port 8050] [--ticker AAPL] [--page chart|groups] [--debug]

then open http://127.0.0.1:8050. Both databases are opened read-only
(`mode=ro`), one connection per request.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dash import ALL, MATCH, Dash, Input, Output, Patch, State, ctx, dash_table, dcc, html, no_update
from dash.dash_table.Format import Format, Scheme, Sign

from src.foundation.data_processing import db
from src.foundation.market_common.derived_db import default_derived_db_path
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS
from src.foundation.utils.config_loader import load_config
from src.ui.chart import bars as bars_mod
from src.ui.chart import earnings as earnings_mod
from src.ui.chart import groups as groups_mod
from src.ui.chart import overlays as overlays_mod
from src.ui.chart import panes as panes_mod
from src.ui.chart import relevance, rs
from src.ui.chart.config import ChartConfig, ChartType, GroupsConfig, MASpec, PaneConfig
from src.ui.chart.earnings import EarningsCard
from src.ui.chart.overlays import EVENT_FAMILIES, FAMILIES, FAMILY_NAMES, Overlay
from src.ui.chart.figure import (build_figure, closed_weekdays, default_x_range, earnings_bar, figure_annotations,
                                 hidden_weekdays, padded_full_range, y_axis_ranges)

logger = logging.getLogger(__name__)
MARKET_CALENDAR_TICKER = "SPY"
_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else _ROOT / p


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"no database at {path}")
    return db.get_connection(f"file:{path}?mode=ro", uri=True)


@dataclass(frozen=True)
class OverlaySet:
    items: tuple[Overlay, ...]
    errors: dict[str, str]  # {family: message} for families whose detector failed
    seconds: float  # how long the detectors took, shown in the menu


class ChartData:
    """Reads from the two databases. Bars and moving averages are cached for the
    life of the process; restart the app after new data is ingested."""

    def __init__(self, raw_path: Path, derived_path: Path):
        self.raw_path, self.derived_path = raw_path, derived_path
        self.bars = lru_cache(maxsize=32)(self._bars)
        self.moving_averages = lru_cache(maxsize=64)(self._moving_averages)
        self.market_closed = lru_cache(maxsize=1)(self._market_closed)
        self.holidays = lru_cache(maxsize=32)(self._holidays)
        self.overlays = lru_cache(maxsize=16)(self._overlays)
        self.earnings = lru_cache(maxsize=32)(self._earnings)
        self.pane = lru_cache(maxsize=64)(self._pane)
        self.rs_closes = lru_cache(maxsize=32)(self._rs_closes)
        # one page for the life of the process (its config never changes), until Reload
        self._groups_page: groups_mod.GroupsPage | None = None
        self.groups_note: str | None = None

    @classmethod
    def from_config(cls) -> "ChartData":
        paths = load_config().data_paths
        return cls(db.default_db_path(_resolve(paths.raw)), default_derived_db_path(_resolve(paths.derived)))

    def _bars(self, ticker: str, timeframe: Timeframe) -> pd.DataFrame:
        conn = _read_only(self.raw_path)
        try:
            return bars_mod.load_chart_bars(conn, ticker, timeframe)
        finally:
            conn.close()

    def _moving_averages(self, ticker: str, timeframe: Timeframe,
                         specs: tuple[MASpec, ...]) -> dict[str, pd.Series]:
        return bars_mod.moving_averages(self.bars(ticker, timeframe)["close"], specs)

    def _market_closed(self) -> pd.DatetimeIndex:
        """Weekdays SPY has no bar for (holidays); empty if SPY has no bars."""
        return closed_weekdays(self.bars(MARKET_CALENDAR_TICKER, Timeframe.DAILY).index)

    def _holidays(self, ticker: str) -> tuple[str, ...]:
        return hidden_weekdays(self.market_closed(), self.bars(ticker, Timeframe.DAILY).index)

    def _overlays(self, ticker: str, timeframe: Timeframe) -> OverlaySet:
        """Every family's overlays as of the last bar, run live (slow: seconds), cached."""
        bars = self.bars(ticker, timeframe)
        if bars.empty:
            return OverlaySet((), {}, 0.0)
        started = time.perf_counter()
        conn = _read_only(self.raw_path)
        try:
            items, errors = overlays_mod.all_overlays(conn, ticker, timeframe, bars)
        finally:
            conn.close()
        for family, error in errors.items():
            logger.warning("%s %s %s overlays failed: %s", ticker, timeframe.value, family, error)
        return OverlaySet(tuple(items), errors, time.perf_counter() - started)

    def _pane(self, ticker: str, timeframe: Timeframe, key: str, config: PaneConfig) -> panes_mod.Pane:
        bars = self.bars(ticker, timeframe)
        label = panes_mod.pane_label(key, config)
        if key == panes_mod.RS_LINE:
            market = self.bars(config.market, timeframe)
            return panes_mod.Pane(key, label, panes_mod.rs_line_frame(bars, market, config),
                                  panes_mod.rs_line_end(bars, market, config.market))
        if key != panes_mod.RS:
            return panes_mod.Pane(key, label, panes_mod.pane_frame(key, bars, config))
        weekly = {t: self.rs_closes(t) for t in (ticker, config.market)}
        frame, note = panes_mod.rs_pane_data(bars.index, timeframe, weekly[ticker], weekly[config.market], config)
        if weekly[config.market].empty:
            note = f"RS pane: no {config.market} bars"
        return panes_mod.Pane(key, label, frame, note)

    def _rs_closes(self, ticker: str) -> pd.Series:
        """Weekly closes on the relative-strength module's own basis (total return)."""
        conn = _read_only(self.raw_path)
        try:
            weekly = bars_mod.load_chart_bars(conn, ticker, Timeframe.WEEKLY, MODULE_PRICE_BASIS["relative_strength"])
        finally:
            conn.close()
        return weekly["close"] if not weekly.empty else pd.Series(dtype=float)

    def _earnings(self, ticker: str) -> tuple[tuple[EarningsCard, ...], str | None]:
        """(the ticker's earnings cards, oldest first; an error message or None).
        Never raises, so the chart still draws."""
        daily = self.bars(ticker, Timeframe.DAILY)
        if daily.empty:
            return (), None
        try:
            conn = _read_only(self.raw_path)
            try:
                return tuple(earnings_mod.load_cards(conn, ticker, daily)), None
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001 -- a card bug mustn't take the chart down
            logger.warning("earnings for %s failed: %s", ticker, e, exc_info=True)
            return (), f"earnings failed: {type(e).__name__}: {e}"

    def groups(self, config: GroupsConfig, reload: bool = False) -> groups_mod.GroupsPage | str:
        """The groups page, cached until `reload` (the page's Reload button, e.g. after
        relative strength is rerun). A failure isn't cached, so the next open tries
        again; a failed reload keeps the page it had (`groups_note` says why)."""
        self.groups_note = None
        if reload and self._groups_page is not None:
            fresh = self._groups(config)
            if isinstance(fresh, str):
                self.groups_note = f"reload failed, showing the previous page ({fresh})"
                return self._groups_page
            self._groups_page = fresh
        if self._groups_page is None:
            page = self._groups(config)
            if isinstance(page, str):
                return page
            self._groups_page = page
        return self._groups_page

    def _groups(self, config: GroupsConfig) -> groups_mod.GroupsPage | str:
        """The groups page, or a message saying why there isn't one; never raises."""
        if not self.derived_path.exists():
            return "Groups: no derived database"
        conns: list[sqlite3.Connection] = []
        try:
            for path in (self.raw_path, self.derived_path):
                conns.append(_read_only(path))
            return groups_mod.build_page(*conns, config)
        except Exception as e:  # noqa: BLE001 -- a groups bug mustn't take the app down
            logger.warning("groups page failed: %s", e, exc_info=True)
            return f"Groups failed: {type(e).__name__}: {e}"
        finally:
            for conn in conns:
                conn.close()

    def strip(self, ticker: str, change_days: int) -> rs.RSStrip | str:
        """The strip, or a short message saying why there isn't one; never raises,
        so the chart still draws."""
        if not self.derived_path.exists():
            return "RS: no derived database"
        conns: list[sqlite3.Connection] = []
        try:
            for path in (self.raw_path, self.derived_path):
                conns.append(_read_only(path))
            return rs.rs_strip(*conns, ticker, change_days)
        except (sqlite3.Error, pd.errors.DatabaseError, FileNotFoundError) as e:
            logger.warning("RS strip read failed for %s: %s", ticker, e)
            return "RS: read error (see the app's log)"
        finally:
            for conn in conns:
                conn.close()


def _normalise(ticker: str | None) -> str:
    return (ticker or "").strip().upper()


def _view_key(ticker: str, timeframe: Timeframe) -> str:
    return f"{ticker}-{timeframe.value}"


def selected_specs(config: ChartConfig, timeframe: Timeframe, ma_keys) -> tuple[MASpec, ...]:
    """The timeframe's moving averages that are ticked; keys from the other timeframe are ignored."""
    keys = set(ma_keys or [])
    return tuple(s for s in config.ma_options[timeframe] if s.key in keys)


_KIND_ORDER = {"zone": 0, "hline": 1, "series": 2, "segment": 3}  # zones underneath, events on top


def chosen_items(ids: list[dict] | None, values: list[list] | None) -> dict[str, list[str]]:
    """{family: ticked item ids} from the menu's pattern-matched checklists."""
    return {i["family"]: list(v or []) for i, v in zip(ids or [], values or [])}


def selected_overlays(data: ChartData, ticker: str, timeframe: Timeframe, menu_key: str | None,
                      chosen: dict[str, list[str]]) -> tuple[Overlay, ...]:
    """The ticked overlays, zones first. Nothing while the menu belongs to another chart
    (the menu for a new ticker is still being built), so a fast redraw never waits on
    the detectors and never draws the previous ticker's picks."""
    ticker = _normalise(ticker)
    picked = {(f, i) for f, ids in (chosen or {}).items() for i in ids}
    if not ticker or not picked or menu_key != _view_key(ticker, timeframe):
        return ()
    items = [o for o in data.overlays(ticker, timeframe).items if (o.family, o.item_id) in picked]
    return tuple(sorted(items, key=lambda o: _KIND_ORDER.get(o.kind, 9)))


def chart_cards(data: ChartData, ticker: str, timeframe: Timeframe) -> tuple[tuple[EarningsCard, ...], str | None]:
    """(the cards that have a bar on this chart, the error note or None). The latest
    of these is the one open by default, e.g. not one in the weekly chart's week in progress."""
    cards, note = data.earnings(ticker)
    bars = data.bars(ticker, timeframe)
    return tuple(c for c in cards if earnings_bar(bars, c) is not None), note


def open_cards(cards: tuple[EarningsCard, ...], ticker: str, opened: dict | None,
               expand_all: bool = False) -> frozenset[str]:
    """The cards drawn expanded: all with "expand all" (plotly hides the ones out of
    view), else the ones clicked open for this ticker (`opened` = {"ticker", "open"}),
    else only the latest."""
    if expand_all:
        return frozenset(c.key for c in cards)
    if opened and opened.get("ticker") == ticker:
        return frozenset(opened.get("open") or [])
    return frozenset([cards[-1].key]) if cards else frozenset()


def toggle_card(cards: tuple[EarningsCard, ...], ticker: str, opened: dict | None, key: str) -> dict:
    """The new `opened` store after a click on the card or flag `key`."""
    now = set(open_cards(cards, ticker, opened))
    now ^= {key}
    return {"ticker": ticker, "open": sorted(now)}


def clicked_card(click: dict | None) -> str | None:
    """The card key from plotly's annotation click (`clickAnnotationData`)."""
    return ((click or {}).get("annotation") or {}).get("name") or None


def selected_panes(data: ChartData, config: ChartConfig, ticker: str, timeframe: Timeframe,
                   pane_keys) -> tuple[panes_mod.Pane, ...]:
    """The ticked panes, in menu order (unknown keys ignored)."""
    ticked = set(pane_keys or ())
    return tuple(data.pane(ticker, timeframe, key, config.panes) for key in panes_mod.PANES if key in ticked)


def render(data: ChartData, config: ChartConfig, ticker: str, timeframe: Timeframe, chart_type: ChartType,
           ma_keys, show_volume: bool, view: dict | None = None, overlays: tuple[Overlay, ...] = (),
           earnings_options=(), opened: dict | None = None, pane_keys=()):
    """(figure or None, message). `view` is the stored zoom ({"key", "range"}); it's
    kept when it belongs to this ticker and timeframe, else the default span is shown.
    `earnings_options` holds "show" and/or "all" (expand all); `opened` the cards
    clicked open (`open_cards`). `pane_keys`: the indicator panes ticked."""
    ticker = _normalise(ticker)
    if not ticker:
        return None, "Type a ticker."
    bars = data.bars(ticker, timeframe)
    if bars.empty:
        return None, f"No bars for {ticker}."
    mas = data.moving_averages(ticker, timeframe, selected_specs(config, timeframe, ma_keys))
    if view and view.get("key") == _view_key(ticker, timeframe) and view.get("range"):
        x_range = tuple(view["range"])
    else:
        x_range = default_x_range(bars, timeframe, config.default_span_days[timeframe])
    holidays = data.holidays(ticker) if timeframe == Timeframe.DAILY else ()
    cards, note = (), None
    if "show" in (earnings_options or ()):
        cards, note = chart_cards(data, ticker, timeframe)
    expanded = open_cards(cards, ticker, opened, "all" in (earnings_options or ()))
    panes = selected_panes(data, config, ticker, timeframe, pane_keys)
    fig = build_figure(bars, ticker, timeframe, chart_type, mas, config.ma_options[timeframe],
                       show_volume=show_volume, x_range=x_range, holidays=holidays, overlays=overlays,
                       earnings=cards, expanded=expanded, panes=panes, pane_config=config.panes)
    notes = [n for n in (note, *(p.note for p in panes)) if n]
    message = f"{ticker} · {timeframe.value} · {len(bars)} bars · last {bars.index.max():%Y-%m-%d}"
    return fig, " · ".join([message, *notes])


def _distance_text(d: float) -> str:
    return "—" if d == float("inf") else f"{d:.1f} ATR"


def _nearness_text(r: relevance.Ranked) -> str:
    """How far a level is from price, or how long ago an event was confirmed."""
    age = r.overlay.age_bars
    if age is None:
        return _distance_text(r.distance_atr)
    return "this bar" if age == 0 else f"{age} bar{'s' if age > 1 else ''} ago"


def _hover_text(r: relevance.Ranked) -> str:
    parts = [f"{k}: {v}" for k, v in r.overlay.hover.items() if v is not None]
    parts.append(f"{'distance' if r.overlay.age_bars is None else 'age'}: {_nearness_text(r)}")
    if r.strength_pct is not None:
        parts.append(f"strength percentile: {r.strength_pct:.2f}")
    parts.append("score: " + ("not in reach" if r.score is None else f"{r.score:.2f}"))
    return "\n".join(parts)


def family_count_text(shown: int, of: int, events: bool = False) -> str:
    """"3 of 41 shown" (of the family's alive items), or for events "1 of 2 recent"
    (of the alive ones confirmed within reach: old divergences stay alive for ever);
    "3 shown, 0 recent" when older ones were picked by hand or by ticking the family."""
    if events:
        return f"{shown} shown, {of} recent" if shown > of else f"{shown} of {of} recent"
    return f"{shown} of {of} shown"


def family_sync(changed: str, family: str, ticked, values, defaults, count) -> tuple[list, list, str]:
    """(family box value, item values, count text) after the family box (`changed` =
    "family") or one of its items ("items") was clicked. Ticking the box picks its
    defaults and unticking clears them; the box is ticked exactly when an item is, so
    unticking the last item by hand unticks the box and the next tick restores the defaults.
    `count`: the family's {"of", "events"} for the count text."""
    if changed == "family":
        values = list(defaults or []) if ticked else []
    values = list(values or [])
    count = count or {}
    return ([family] if values else []), values, family_count_text(len(values), count.get("of", 0),
                                                                    count.get("events", False))


def total_count_text(shown: int, cap: int) -> str:
    return f"{shown} / {cap} on the chart" + (" — busy" if shown > cap else "")


def menu(data: ChartData, config: ChartConfig, ticker: str, timeframe: Timeframe,
         weight: float | None = None) -> tuple[list, str | None]:
    """(the level menu's children, the chart it belongs to). Each family lists its
    alive items, best first, with the default selection ticked; its hidden stores hold
    what ticking the family box picks and how many alive items it has."""
    ticker = _normalise(ticker)
    if not ticker:
        return [], None
    bars = data.bars(ticker, timeframe)
    if bars.empty:
        return [], None
    cfg = config.relevance
    found = data.overlays(ticker, timeframe)
    atr = relevance.last_atr(bars, cfg.atr_period)
    ranked = relevance.rank(list(found.items), float(bars["close"].iloc[-1]), atr, cfg, weight, timeframe)
    per_family = relevance.family_defaults(ranked, cfg, atr)
    defaults = relevance.default_selection(ranked, cfg, atr, per_family)
    children = [html.Div(f"As of {bars.index.max():%Y-%m-%d} · ATR {atr:.2f} · found in {found.seconds:.1f}s",
                         style={"color": "#64748b", "fontSize": "12px", "marginBottom": "6px"})]
    for family in FAMILIES:
        alive = [r for r in ranked if r.overlay.family == family and r.overlay.alive]
        events = family in EVENT_FAMILIES
        count = {"of": sum(r.in_reach for r in alive) if events else len(alive), "events": events}
        picked = defaults.get(family, [])
        # Ticking the family box picks its defaults; with nothing in reach, its nearest
        # (or most recent) alive items, one per level or event.
        on_tick = per_family.get(family) or relevance.nearest_alive(ranked, family, cfg, atr)
        listed = alive[: cfg.menu_items_per_family]
        must_list = set(picked) | set(on_tick)
        listed += [r for r in alive[cfg.menu_items_per_family:] if r.overlay.item_id in must_list]
        options = [{"label": html.Span(f"{r.overlay.label} · {_nearness_text(r)}",
                                       title=_hover_text(r),
                                       style={"color": "#94a3b8"} if r.score is None else {}),
                    "value": r.overlay.item_id}
                   for r in listed]
        error = found.errors.get(family)
        children.append(html.Div(style={"marginBottom": "10px"}, children=[
            html.Div(style={"display": "flex", "gap": "6px", "alignItems": "baseline"}, children=[
                dcc.Checklist(id={"type": "family", "family": family}, value=[family] if picked else [],
                              options=[{"label": FAMILY_NAMES[family], "value": family}],
                              inputStyle={"marginRight": "6px"}, labelStyle={"fontWeight": 600}),
                html.Span(family_count_text(len(picked), count["of"], events),
                          id={"type": "family-count", "family": family},
                          style={"color": "#64748b", "fontSize": "12px"}),
            ]),
            dcc.Store(id={"type": "family-defaults", "family": family}, data=on_tick),
            dcc.Store(id={"type": "family-alive", "family": family}, data=count),
            html.Div(f"failed: {error}", style={"color": "#dc2626", "fontSize": "12px"}) if error else None,
            dcc.Checklist(id={"type": "items", "family": family}, options=options, value=picked,
                          inputStyle={"marginRight": "6px"},
                          labelStyle={"display": "block", "fontSize": "12px", "marginLeft": "14px"}),
        ]))
    return children, _view_key(ticker, timeframe)


def strip_children(data: ChartData, config: ChartConfig, ticker: str) -> list[str]:
    ticker = _normalise(ticker)
    if not ticker:
        return []
    strip = data.strip(ticker, config.rs_change_days)
    return [strip] if isinstance(strip, str) else rs.strip_parts(strip, config.rs_change_days)


def x_range_from_relayout(relayout: dict | None) -> tuple[str, str] | None:
    """The new x-range from a zoom/pan event, from any of the shared x-axes (one per
    pane: the event names the pane that was dragged)."""
    if not relayout:
        return None
    for axis in _x_axes(relayout):
        if f"{axis}.range[0]" in relayout and f"{axis}.range[1]" in relayout:
            return relayout[f"{axis}.range[0]"], relayout[f"{axis}.range[1]"]
        if f"{axis}.range" in relayout:
            lo, hi = relayout[f"{axis}.range"]
            return lo, hi
    return None


def _x_axes(relayout: dict) -> list[str]:
    """The x-axis names an event mentions ("xaxis", "xaxis2", ...), in order."""
    names = (key.split(".", 1)[0] for key in relayout)
    return list(dict.fromkeys(n for n in names if n == "xaxis" or (n.startswith("xaxis") and n[5:].isdigit())))


def is_autorange(relayout: dict | None) -> bool:
    """A double-click reset: plotly reports autorange instead of a range."""
    return bool(relayout) and any(relayout.get(f"{a}.autorange") for a in _x_axes(relayout))


_TAB = {"padding": "6px 14px"}
_TAB_ON = {**_TAB, "fontWeight": 600}
_WHOLE = Format(precision=0, scheme=Scheme.fixed)
_SIGNED = Format(precision=0, scheme=Scheme.fixed, sign=Sign.positive)
_PCT = Format(precision=0, scheme=Scheme.percentage)
_SIGNED_PCT = Format(precision=0, scheme=Scheme.percentage, sign=Sign.positive)


def _weeks(days: int) -> str:
    return f"{days // 7}w" if days % 7 == 0 else f"{days}d"


_GREEN, _RED, _MUTED = "#15803d", "#b91c1c", "#64748b"
_SELECTED = "#f1f5f9"
_BAR = "#e2e8f0"
# RS rating shading, [low, high): one hue, darker for higher. A rating is a rank, not a
# gain or a loss, so green/red stays for signs (changes, distances from the averages).
_RS_SHADES = ((80, 101, "#93c5fd"), (60, 80, "#bfdbfe"), (40, 60, "#dbeafe"), (20, 40, "#eff6ff"))
_TEXT_COLUMNS = ("sector", "etf", "ticker", "status")
_SMALL_COLUMNS = ("etf", "status")


def _rs_shading(column: str) -> list[dict]:
    return [{"if": {"filter_query": f"{{{column}}} >= {lo} && {{{column}}} < {hi}", "column_id": column},
             "backgroundColor": colour} for lo, hi, colour in _RS_SHADES]


def _sign_colours(columns) -> list[dict]:
    return [style for c in columns for style in (
        {"if": {"filter_query": f"{{{c}}} > 0", "column_id": c}, "color": _GREEN},
        {"if": {"filter_query": f"{{{c}}} < 0", "column_id": c}, "color": _RED})]


def _base_styles(text_columns=_TEXT_COLUMNS, small_columns=_SMALL_COLUMNS) -> tuple[list[dict], list[dict]]:
    """(style_cell_conditional, style_header_conditional): text left, notes small and grey."""
    cells = [{"if": {"column_id": c}, "textAlign": "left"} for c in text_columns]
    cells += [{"if": {"column_id": c}, "color": _MUTED, "fontSize": "12px"} for c in small_columns]
    headers = [{"if": {"column_id": c}, "textAlign": "left"} for c in text_columns]
    return cells, headers


def breadth_bar(share: float) -> str:
    """A cell background filled to `share` (0-1) from the left: a bar under the number."""
    p = max(0.0, min(1.0, share)) * 100
    return f"linear-gradient(90deg, {_BAR} 0%, {_BAR} {p:.0f}%, transparent {p:.0f}%, transparent 100%)"


def sector_styles(rows: list[dict], selected: str | None, n_shares: int) -> list[dict]:
    """The sector table's data styles: RS shading, rank changes by sign, the breadth
    bars (one per row and column, since each fills to its own value) and the selected row."""
    # later styles win, so the selected row's background goes first: the RS shading
    # and the bars still show on it
    styles = ([{"if": {"filter_query": f'{{id}} = "{_quote(selected)}"'}, "backgroundColor": _SELECTED,
                "fontWeight": 600}] if selected else [])
    styles += _rs_shading("rating") + _sign_colours([c for c in rows[0] if c.startswith("rank_change_")] if rows
                                                     else [])
    for row in rows:
        for i in range(n_shares):
            share = row.get(f"above_{i}")
            if share is not None:
                styles.append({"if": {"filter_query": f'{{id}} = "{_quote(row["id"])}"', "column_id": f"above_{i}"},
                               "background": breadth_bar(share)})
    return styles


def member_styles(config: GroupsConfig) -> list[dict]:
    """The members table's data styles: RS shading, changes and MA distances by sign,
    near the 52-week high in green, and tickers that left the index greyed out."""
    near_high = {"if": {"filter_query": "{from_high} >= -0.05", "column_id": "from_high"}, "color": _GREEN,
                 "fontWeight": 600}
    gone = {"if": {"filter_query": '{gone} = "yes"'}, "color": "#94a3b8", "backgroundColor": "#f8fafc"}
    return (_rs_shading("rating") + _sign_colours(["change", *(f"vs_ma_{i}" for i in range(len(config.ma_periods)))])
            + [near_high, gone, {"if": {"column_id": "ticker"}, "fontWeight": 600}])


def sector_columns(config: GroupsConfig) -> list[dict]:
    num = {"type": "numeric"}
    return [{"name": "#", "id": "rank", **num},
            {"name": "Sector", "id": "sector"},
            {"name": "ETF", "id": "etf"},
            {"name": "RS", "id": "rating", **num, "format": _WHOLE},
            *({"name": f"Rank Δ {_weeks(d)}", "id": f"rank_change_{i}", **num, "format": _SIGNED}
              for i, d in enumerate(config.rank_change_days)),
            *({"name": f"> {n}d MA", "id": f"above_{i}", **num, "format": _PCT}
              for i, n in enumerate(config.ma_periods)),
            {"name": "Members", "id": "members", **num}]


def sector_rows(page: groups_mod.GroupsPage) -> tuple[list[dict], list[dict]]:
    """(the sector table's rows, their tooltips: how many members each share counts)."""
    rows, tips = [], []
    for s in page.sectors:
        row = {"id": s.sector, "rank": s.rank, "sector": s.sector, "etf": s.etf, "rating": s.rating,
               "members": s.members}
        tip = {}
        for i, change in enumerate(s.rank_changes):
            row[f"rank_change_{i}"] = change
        for i, (share, n) in enumerate(zip(s.pct_above, s.n_counted)):
            row[f"above_{i}"] = share
            tip[f"above_{i}"] = f"of {n} members with the full window and a bar on {page.as_of}"
        rows.append(row)
        tips.append(tip)
    return rows, tips


def member_columns(config: GroupsConfig) -> list[dict]:
    num = {"type": "numeric"}
    return [{"name": "Ticker", "id": "ticker"},
            {"name": "RS", "id": "rating", **num, "format": _WHOLE},
            {"name": f"RS Δ {_weeks(config.member_change_days)}", "id": "change", **num, "format": _SIGNED},
            {"name": "52w high", "id": "from_high", **num, "format": _SIGNED_PCT},
            *({"name": f"vs {n}d MA", "id": f"vs_ma_{i}", **num, "format": _SIGNED_PCT}
              for i, n in enumerate(config.ma_periods)),
            {"name": "Status", "id": "status"}]


def shown(value: float | None, digits: int) -> float | None:
    """`value` rounded as the table shows it, with no negative zero: the table's
    signed format would print -0.4 as "−0", and its colour would call it a loss."""
    return None if value is None else round(value, digits) + 0.0


def member_rows(page: groups_mod.GroupsPage, sector: str | None) -> list[dict]:
    rows = []
    for m in page.members.get(sector, ()):
        row = {"id": m.ticker, "ticker": m.ticker, "rating": m.rating, "change": shown(m.change, 0),
               "from_high": shown(m.pct_from_high, 2), "status": m.status,
               "gone": "no" if m.member else "yes"}
        for i, v in enumerate(m.vs_ma):
            row[f"vs_ma_{i}"] = shown(v, 2)
        rows.append(row)
    return rows


def groups_header(page: groups_mod.GroupsPage) -> str:
    parts = [f"As of {page.as_of}, the last sector RS date"]
    if page.bars_end and page.bars_end > page.as_of:
        parts.append(f"bars run to {page.bars_end}: rerun relative strength to catch up")
    if page.not_rated:
        parts.append(f"not rated that day: {', '.join(page.not_rated)}")
    if page.no_sector:
        parts.append(f"members with no sector: {', '.join(page.no_sector)}")
    return " · ".join(parts)


def members_title(sector: str, rows: list[dict], config: GroupsConfig) -> str:
    listed = sum(r["gone"] == "no" for r in rows)
    gone = len(rows) - listed
    return (f"{sector} · {listed} members" + (f" (+{gone} left in the last {config.left_window_days} days)"
                                               if gone else "") + " · click a ticker for its chart")


def selected_sector(page: groups_mod.GroupsPage, current: str | None) -> str | None:
    """The sector whose members are listed: the one picked, else the top-ranked."""
    names = [s.sector for s in page.sectors]
    if current in names:
        return current
    return names[0] if names else None


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def clicked_row(cell: dict | None) -> str | None:
    """The row id (sector or ticker) of a table click (`active_cell`)."""
    return (cell or {}).get("row_id") or None


PAGES = ("chart", "groups")


def create_app(data: ChartData | None = None, config: ChartConfig | None = None, page: str = "chart") -> Dash:
    if page not in PAGES:
        raise ValueError(f"page must be one of {PAGES}, not {page!r}")
    data = data or ChartData.from_config()
    config = config or ChartConfig()
    app = Dash(__name__, title="Chart")

    radio = dict(inline=True, inputStyle={"marginRight": "4px", "marginLeft": "10px"})
    daily = Timeframe.DAILY
    chart_page = [
        html.Div(style={"display": "flex", "gap": "16px", "alignItems": "center", "flexWrap": "wrap",
                        "paddingTop": "6px"}, children=[
            dcc.Input(id="ticker", value=config.default_ticker, debounce=True, type="text",
                      style={"width": "90px", "textTransform": "uppercase", "fontWeight": 600}),
            dcc.RadioItems(id="timeframe", value=daily.value, **radio,
                           options=[{"label": "Day", "value": Timeframe.DAILY.value},
                                    {"label": "Week", "value": Timeframe.WEEKLY.value}]),
            dcc.RadioItems(id="chart-type", value=ChartType.CANDLES.value, **radio,
                           options=[{"label": "Line", "value": ChartType.LINE.value},
                                    {"label": "Bars", "value": ChartType.BARS.value},
                                    {"label": "Candles", "value": ChartType.CANDLES.value}]),
            dcc.Checklist(id="volume", value=["on"], options=[{"label": "Volume", "value": "on"}], **radio),
            html.Span(id="message", style={"color": "#64748b"}),
        ]),
        html.Div(id="rs-strip", style={"display": "flex", "gap": "18px", "padding": "6px 0",
                                       "fontSize": "14px", "color": "#0f172a"}),
        html.Div(style={"display": "flex", "gap": "12px"}, children=[
            html.Div(style={"width": "290px", "flexShrink": 0, "height": "82vh", "overflowY": "auto",
                            "overflowX": "hidden"}, children=[
                html.Div("Moving averages", style={"fontWeight": 600, "marginBottom": "4px"}),
                dcc.Checklist(id="mas", inputStyle={"marginRight": "6px"},
                              options=_ma_options(config, daily), value=list(config.ma_defaults[daily])),
                html.Div("Earnings", style={"fontWeight": 600, "margin": "8px 0 4px"}),
                dcc.Checklist(id="earnings", value=["show"], inputStyle={"marginRight": "6px"},
                              options=[{"label": "Flags (click one for its card)", "value": "show"},
                                       {"label": "Expand all", "value": "all"}]),
                dcc.Store(id="earnings-open"),
                html.Div("Panes", style={"fontWeight": 600, "margin": "8px 0 4px"}),
                dcc.Checklist(id="panes", value=[], inputStyle={"marginRight": "6px"},
                              options=[{"label": panes_mod.pane_label(k, config.panes), "value": k}
                                       for k in panes_mod.PANES]),
                html.Hr(style={"margin": "10px 0"}),
                html.Div(style={"fontSize": "12px", "color": "#475569"}, children=[
                    html.Div("Default picks rank by", style={"fontWeight": 600}),
                    dcc.Slider(id="weight", min=0, max=1, step=0.1, value=config.relevance.weight, marks=None,
                               tooltip={"placement": "bottom", "always_visible": False}),
                    html.Div(style={"display": "flex", "justifyContent": "space-between", "marginTop": "-6px"},
                             children=[html.Span("strength"), html.Span("proximity")]),
                ]),
                html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center", "margin": "4px 0 8px"},
                         children=[html.Button("Reset to defaults", id="reset", n_clicks=0,
                                               style={"fontSize": "12px"}),
                                   html.Span(id="overlay-count", style={"fontSize": "12px"})]),
                dcc.Store(id="menu-key"),
                dcc.Loading(html.Div(id="menu"), type="dot"),
            ]),
            dcc.Graph(id="chart", style={"flexGrow": 1, "height": "82vh"},
                      config={"scrollZoom": True, "displaylogo": False}),
        ]),
    ]
    gc = config.groups
    cell_styles, header_styles = _base_styles()
    table_style = dict(
        sort_action="native", cell_selectable=True, style_as_list_view=True,
        style_cell={"fontFamily": "system-ui, sans-serif", "fontSize": "13px", "padding": "4px 10px",
                    "border": "none", "borderBottom": "1px solid #f1f5f9", "whiteSpace": "nowrap"},
        style_header={"fontWeight": 600, "fontSize": "12px", "color": _MUTED, "backgroundColor": "white",
                      "borderBottom": "2px solid #e2e8f0"},
        style_cell_conditional=cell_styles, style_header_conditional=header_styles,
        css=[{"selector": "tr:hover td", "rule": "cursor: pointer;"},
             # a sticky header row (DataTable's fixed_rows can misalign unsized columns)
             {"selector": "th", "rule": "position: sticky; top: 0; z-index: 1;"}])
    title = {"fontWeight": 600, "fontSize": "15px", "marginBottom": "6px"}
    groups_page = html.Div(style={"paddingTop": "8px"}, children=[
        html.Div(style={"display": "flex", "gap": "12px", "alignItems": "center", "marginBottom": "10px"}, children=[
            html.Span(id="groups-head", style={"color": _MUTED, "fontSize": "13px"}),
            html.Button("Reload", id="groups-reload", n_clicks=0, style={"fontSize": "12px"}),
        ]),
        dcc.Loading(type="dot", children=html.Div(
            style={"display": "flex", "gap": "28px", "alignItems": "flex-start", "flexWrap": "wrap"}, children=[
                html.Div(style={"flex": "0 0 auto"}, children=[
                    html.Div("Sectors", style=title),
                    dash_table.DataTable(id="sectors", columns=sector_columns(gc), data=[], tooltip_delay=0,
                                         tooltip_duration=None, **table_style),
                    html.Div("Click a sector for its members. Bars: share of members above the average.",
                             style={"color": _MUTED, "fontSize": "12px", "marginTop": "6px"}),
                ]),
                html.Div(style={"flex": "1 1 560px", "maxWidth": "900px"}, children=[
                    html.Div(id="members-title", style=title),
                    dash_table.DataTable(id="members", columns=member_columns(gc), data=[], page_action="none",
                                         style_data_conditional=member_styles(gc),
                                         style_table={"maxHeight": "76vh", "overflowY": "auto"}, **table_style),
                ]),
            ])),
    ])
    app.layout = html.Div(style={"fontFamily": "system-ui, sans-serif", "padding": "8px"}, children=[
        dcc.Store(id="view"),
        dcc.Store(id="group-sector"),
        dcc.Tabs(id="page", value=page, style={"height": "34px"}, children=[
            dcc.Tab(label="Chart", value="chart", children=chart_page, style=_TAB, selected_style=_TAB_ON),
            dcc.Tab(label="Groups", value="groups", children=[groups_page], style=_TAB, selected_style=_TAB_ON),
        ]),
    ])

    # A timeframe change only resets the MA menu; the new `mas.value` then triggers one
    # redraw (timeframe is State there), instead of one draw per input.
    @app.callback(Output("mas", "options"), Output("mas", "value"), Input("timeframe", "value"),
                  prevent_initial_call=True)
    def _ma_menu(timeframe):
        tf = Timeframe(timeframe)
        return _ma_options(config, tf), list(config.ma_defaults[tf])

    items = {"type": "items", "family": ALL}

    # The menu runs the detectors (seconds). The chart draws without waiting for it;
    # when the menu arrives, its checklists' values redraw the chart with the picks.
    # Moving the slider re-picks the defaults at the new weight (it's there to try weights
    # on a live chart), so hand picks are replaced; "Reset" also puts the slider back.
    @app.callback(Output("menu", "children"), Output("menu-key", "data"), Output("weight", "value"),
                  Input("ticker", "value"), Input("timeframe", "value"), Input("weight", "value"),
                  Input("reset", "n_clicks"))
    def _menu(ticker, timeframe, weight, _reset):
        if ctx.triggered_id == "reset":
            weight = config.relevance.weight
        children, key = menu(data, config, ticker, Timeframe(timeframe), weight)
        return children, key, weight

    family = {"type": "family", "family": MATCH}
    family_items = {"type": "items", "family": MATCH}

    @app.callback(Output(family, "value"), Output(family_items, "value"),
                  Output({"type": "family-count", "family": MATCH}, "children"),
                  Input(family, "value"), Input(family_items, "value"),
                  State({"type": "family-defaults", "family": MATCH}, "data"),
                  State({"type": "family-alive", "family": MATCH}, "data"), prevent_initial_call=True)
    def _family(ticked, values, defaults, alive):
        trigger = ctx.triggered_id
        if trigger is None:  # the menu was just built: keep its own default picks
            return no_update, no_update, no_update
        return family_sync(trigger["type"], trigger["family"], ticked, values, defaults, alive)

    @app.callback(Output("overlay-count", "children"), Input(items, "value"))
    def _total_count(values):
        return total_count_text(sum(len(v or []) for v in values or []), config.relevance.total)

    @app.callback(Output("chart", "figure"), Output("message", "children"),
                  Input("ticker", "value"), Input("chart-type", "value"), Input("mas", "value"),
                  Input("volume", "value"), Input(items, "value"), Input("earnings", "value"),
                  Input("earnings-open", "data"), Input("panes", "value"), State(items, "id"),
                  State("menu-key", "data"), State("timeframe", "value"), State("view", "data"))
    def _draw(ticker, chart_type, ma_keys, volume, item_values, earnings_options, opened, pane_keys, item_ids,
              menu_key, timeframe, view):
        tf = Timeframe(timeframe)
        picked = selected_overlays(data, ticker, tf, menu_key, chosen_items(item_ids, item_values))
        fig, message = render(data, config, ticker, tf, ChartType(chart_type),
                              ma_keys, "on" in (volume or []), view, picked, earnings_options, opened, pane_keys)
        return (fig if fig is not None else {}), message

    # A click on a flag opens its card; a click on a card closes it. With "Expand all"
    # on, clicks are ignored: every card is forced open, so a toggle wouldn't show and
    # would surface later, when "Expand all" is unticked.
    @app.callback(Output("earnings-open", "data"), Input("chart", "clickAnnotationData"),
                  State("earnings-open", "data"), State("ticker", "value"), State("timeframe", "value"),
                  State("earnings", "value"), prevent_initial_call=True)
    def _toggle_card(click, opened, ticker, timeframe, earnings_options):
        key, ticker = clicked_card(click), _normalise(ticker)
        if key is None or not ticker or "all" in (earnings_options or ()):
            return no_update
        return toggle_card(chart_cards(data, ticker, Timeframe(timeframe))[0], ticker, opened, key)

    @app.callback(Output("rs-strip", "children"), Input("ticker", "value"))
    def _strip(ticker):
        return [html.Span(p) for p in strip_children(data, config, ticker)]

    @app.callback(Output("chart", "figure", allow_duplicate=True), Output("view", "data"),
                  Input("chart", "relayoutData"), State("ticker", "value"), State("timeframe", "value"),
                  State("chart-type", "value"), State("mas", "value"), State("volume", "value"),
                  State(items, "value"), State(items, "id"), State("menu-key", "data"), State("panes", "value"),
                  State("earnings", "value"), State("earnings-open", "data"), prevent_initial_call=True)
    def _refit_y(relayout, ticker, timeframe, chart_type, ma_keys, volume, item_values, item_ids, menu_key,
                 pane_keys, earnings_options, opened):
        ticker, tf = _normalise(ticker), Timeframe(timeframe)
        if not ticker:
            return no_update, no_update
        bars = data.bars(ticker, tf)
        if bars.empty:
            return no_update, no_update
        reset = is_autorange(relayout)
        if reset:
            # A double-click reset shows the whole history; set and store it explicitly,
            # so the figure and the next redraw agree instead of going back to the default span.
            x_range = padded_full_range(bars, tf)
        else:
            x_range = x_range_from_relayout(relayout)
            if x_range is None:
                return no_update, no_update
        mas = data.moving_averages(ticker, tf, selected_specs(config, tf, ma_keys))
        view = {"key": _view_key(ticker, tf), "range": list(x_range)}
        picked = selected_overlays(data, ticker, tf, menu_key, chosen_items(item_ids, item_values))
        show_volume, panes = "on" in (volume or []), selected_panes(data, config, ticker, tf, pane_keys)
        ranges = y_axis_ranges(bars, mas, x_range, ChartType(chart_type), show_volume, picked, panes)
        if not ranges:
            return no_update, view
        patch = Patch()
        for axis, axis_range in ranges.items():
            patch["layout"][axis]["range"] = axis_range
            patch["layout"][axis]["autorange"] = False  # an explicit range is ignored while autorange is on
        if reset:
            patch["layout"]["xaxis"]["range"] = list(x_range)
            patch["layout"]["xaxis"]["autorange"] = False
        # an open card's side (above or below its bar) follows the new price range
        cards, _ = chart_cards(data, ticker, tf) if "show" in (earnings_options or ()) else ((), None)
        expanded = open_cards(cards, ticker, opened, "all" in (earnings_options or ()))
        patch["layout"]["annotations"] = figure_annotations(bars, show_volume, panes, cards, expanded,
                                                            ranges["yaxis"])
        return patch, view

    # The groups page is built the first time its tab opens (a few seconds), then cached
    # until "Reload".
    @app.callback(Output("groups-head", "children"), Output("sectors", "data"), Output("sectors", "tooltip_data"),
                  Output("group-sector", "data"), Input("page", "value"), Input("groups-reload", "n_clicks"),
                  State("group-sector", "data"))
    def _groups(page_value, _reload, current):
        if page_value != "groups":
            return no_update, no_update, no_update, no_update
        page = data.groups(gc, reload=ctx.triggered_id == "groups-reload")
        if isinstance(page, str):
            return page, [], [], None
        rows, tips = sector_rows(page)
        header = " · ".join(filter(None, [groups_header(page), data.groups_note]))
        return header, rows, tips, selected_sector(page, current)

    # The clicked cell is cleared: the row highlight shows the pick, and the cell's own
    # focus style would hide its shading.
    @app.callback(Output("group-sector", "data", allow_duplicate=True), Output("sectors", "active_cell"),
                  Input("sectors", "active_cell"), prevent_initial_call=True)
    def _pick_sector(cell):
        sector = clicked_row(cell)
        return (sector, None) if sector else (no_update, no_update)

    # Also on the sector table's data, so a Reload refreshes the members of the same sector.
    @app.callback(Output("members", "data"), Output("members-title", "children"),
                  Output("sectors", "style_data_conditional"), Input("group-sector", "data"),
                  Input("sectors", "data"))
    def _members(sector, sector_data):
        page = data.groups(gc) if sector else None
        if not isinstance(page, groups_mod.GroupsPage):
            return [], "", []
        rows = member_rows(page, sector)
        return rows, members_title(sector, rows, gc), sector_styles(sector_data or [], sector, len(gc.ma_periods))

    # A click on a member opens its chart; the cell is cleared so a second click on it works too.
    @app.callback(Output("ticker", "value"), Output("page", "value"), Output("members", "active_cell"),
                  Input("members", "active_cell"), prevent_initial_call=True)
    def _open_chart(cell):
        ticker = clicked_row(cell)
        if not ticker:
            return no_update, no_update, no_update
        return ticker, "chart", None

    return app


def _ma_options(config: ChartConfig, timeframe: Timeframe) -> list[dict]:
    return [{"label": s.label, "value": s.key} for s in config.ma_options[timeframe]]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.ui.chart.app")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--ticker", default=ChartConfig.default_ticker, help="the ticker the page opens on")
    parser.add_argument("--page", choices=PAGES, default="chart", help="the tab the page opens on")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    config = replace(ChartConfig(), default_ticker=args.ticker.strip().upper())
    create_app(config=config, page=args.page).run(host="127.0.0.1", port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

"""The chart UI's Dash app (`docs/features/chart_ui_design.md`, steps 1-2): one ticker,
daily/weekly, line/bars/candles, volume, moving averages, the RS strip, and the level
menu (S/R, gaps, AVWAP, Fibonacci) with its default "relevant now" picks.

    python -m src.ui.chart.app [--port 8050] [--ticker AAPL] [--debug]

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
from dash import ALL, MATCH, Dash, Input, Output, Patch, State, ctx, dcc, html, no_update

from src.foundation.data_processing import db
from src.foundation.market_common.derived_db import default_derived_db_path
from src.foundation.market_common.models import Timeframe
from src.foundation.utils.config_loader import load_config
from src.ui.chart import bars as bars_mod
from src.ui.chart import overlays as overlays_mod
from src.ui.chart import relevance, rs
from src.ui.chart.config import ChartConfig, ChartType, MASpec
from src.ui.chart.overlays import FAMILIES, FAMILY_NAMES, Overlay
from src.ui.chart.figure import (build_figure, closed_weekdays, default_x_range, hidden_weekdays,
                                 padded_full_range, y_axis_ranges)

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


_KIND_ORDER = {"zone": 0, "hline": 1, "series": 2}  # zones underneath, curves on top


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


def render(data: ChartData, config: ChartConfig, ticker: str, timeframe: Timeframe, chart_type: ChartType,
           ma_keys, show_volume: bool, view: dict | None = None, overlays: tuple[Overlay, ...] = ()):
    """(figure or None, message). `view` is the stored zoom ({"key", "range"}); it's
    kept when it belongs to this ticker and timeframe, else the default span is shown."""
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
    fig = build_figure(bars, ticker, timeframe, chart_type, mas, config.ma_options[timeframe],
                       show_volume=show_volume, x_range=x_range, holidays=holidays, overlays=overlays)
    return fig, f"{ticker} · {timeframe.value} · {len(bars)} bars · last {bars.index.max():%Y-%m-%d}"


def _distance_text(d: float) -> str:
    return "—" if d == float("inf") else f"{d:.1f} ATR"


def _hover_text(r: relevance.Ranked) -> str:
    parts = [f"{k}: {v}" for k, v in r.overlay.hover.items() if v is not None]
    parts.append(f"distance: {_distance_text(r.distance_atr)}")
    if r.strength_pct is not None:
        parts.append(f"strength percentile: {r.strength_pct:.2f}")
    parts.append("score: " + ("not in reach" if r.score is None else f"{r.score:.2f}"))
    return "\n".join(parts)


def family_count_text(shown: int, alive: int) -> str:
    return f"{shown} of {alive} shown"


def family_sync(changed: str, family: str, ticked, values, defaults, alive) -> tuple[list, list, str]:
    """(family box value, item values, count text) after the family box (`changed` =
    "family") or one of its items ("items") was clicked. Ticking the box picks its
    defaults and unticking clears them; the box is ticked exactly when an item is, so
    unticking the last item by hand unticks the box and the next tick restores the defaults."""
    if changed == "family":
        values = list(defaults or []) if ticked else []
    values = list(values or [])
    return ([family] if values else []), values, family_count_text(len(values), alive or 0)


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
    ranked = relevance.rank(list(found.items), float(bars["close"].iloc[-1]), atr, cfg, weight)
    per_family = relevance.family_defaults(ranked, cfg, atr)
    defaults = relevance.default_selection(ranked, cfg, atr, per_family)
    children = [html.Div(f"As of {bars.index.max():%Y-%m-%d} · ATR {atr:.2f} · found in {found.seconds:.1f}s",
                         style={"color": "#64748b", "fontSize": "12px", "marginBottom": "6px"})]
    for family in FAMILIES:
        alive = [r for r in ranked if r.overlay.family == family and r.overlay.alive]
        picked = defaults.get(family, [])
        # Ticking the family box picks its defaults; with nothing in reach, its nearest alive items.
        on_tick = per_family.get(family) or [r.overlay.item_id for r in alive[: cfg.per_family]]
        listed = alive[: cfg.menu_items_per_family]
        must_list = set(picked) | set(on_tick)
        listed += [r for r in alive[cfg.menu_items_per_family:] if r.overlay.item_id in must_list]
        options = [{"label": html.Span(f"{r.overlay.label} · {_distance_text(r.distance_atr)}",
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
                html.Span(family_count_text(len(picked), len(alive)), id={"type": "family-count", "family": family},
                          style={"color": "#64748b", "fontSize": "12px"}),
            ]),
            dcc.Store(id={"type": "family-defaults", "family": family}, data=on_tick),
            dcc.Store(id={"type": "family-alive", "family": family}, data=len(alive)),
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
    """The new x-range from a zoom/pan event, from either shared x-axis."""
    if not relayout:
        return None
    for axis in ("xaxis", "xaxis2"):
        if f"{axis}.range[0]" in relayout and f"{axis}.range[1]" in relayout:
            return relayout[f"{axis}.range[0]"], relayout[f"{axis}.range[1]"]
        if f"{axis}.range" in relayout:
            lo, hi = relayout[f"{axis}.range"]
            return lo, hi
    return None


def is_autorange(relayout: dict | None) -> bool:
    """A double-click reset: plotly reports autorange instead of a range."""
    return bool(relayout) and any(relayout.get(f"{a}.autorange") for a in ("xaxis", "xaxis2"))


def create_app(data: ChartData | None = None, config: ChartConfig | None = None) -> Dash:
    data = data or ChartData.from_config()
    config = config or ChartConfig()
    app = Dash(__name__, title="Chart")

    radio = dict(inline=True, inputStyle={"marginRight": "4px", "marginLeft": "10px"})
    daily = Timeframe.DAILY
    app.layout = html.Div(style={"fontFamily": "system-ui, sans-serif", "padding": "8px"}, children=[
        dcc.Store(id="view"),
        html.Div(style={"display": "flex", "gap": "16px", "alignItems": "center", "flexWrap": "wrap"}, children=[
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
                  Input("volume", "value"), Input(items, "value"), State(items, "id"),
                  State("menu-key", "data"), State("timeframe", "value"), State("view", "data"))
    def _draw(ticker, chart_type, ma_keys, volume, item_values, item_ids, menu_key, timeframe, view):
        tf = Timeframe(timeframe)
        picked = selected_overlays(data, ticker, tf, menu_key, chosen_items(item_ids, item_values))
        fig, message = render(data, config, ticker, tf, ChartType(chart_type),
                              ma_keys, "on" in (volume or []), view, picked)
        return (fig if fig is not None else {}), message

    @app.callback(Output("rs-strip", "children"), Input("ticker", "value"))
    def _strip(ticker):
        return [html.Span(p) for p in strip_children(data, config, ticker)]

    @app.callback(Output("chart", "figure", allow_duplicate=True), Output("view", "data"),
                  Input("chart", "relayoutData"), State("ticker", "value"), State("timeframe", "value"),
                  State("chart-type", "value"), State("mas", "value"), State("volume", "value"),
                  State(items, "value"), State(items, "id"), State("menu-key", "data"),
                  prevent_initial_call=True)
    def _refit_y(relayout, ticker, timeframe, chart_type, ma_keys, volume, item_values, item_ids, menu_key):
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
        ranges = y_axis_ranges(bars, mas, x_range, ChartType(chart_type), "on" in (volume or []), picked)
        if reset:
            ranges["xaxis"] = list(x_range)
        if not ranges:
            return no_update, view
        patch = Patch()
        for axis, axis_range in ranges.items():
            patch["layout"][axis]["range"] = axis_range
            patch["layout"][axis]["autorange"] = False  # an explicit range is ignored while autorange is on
        return patch, view

    return app


def _ma_options(config: ChartConfig, timeframe: Timeframe) -> list[dict]:
    return [{"label": s.label, "value": s.key} for s in config.ma_options[timeframe]]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.ui.chart.app")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--ticker", default=ChartConfig.default_ticker, help="the ticker the page opens on")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    config = replace(ChartConfig(), default_ticker=args.ticker.strip().upper())
    create_app(config=config).run(host="127.0.0.1", port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

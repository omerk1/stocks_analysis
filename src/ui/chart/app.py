"""The chart UI's Dash app, step 1 of `docs/features/chart_ui_design.md`: one ticker,
daily/weekly, line/bars/candles, volume, moving averages and the RS strip.

    python -m src.ui.chart.app [--port 8050] [--debug]

then open http://127.0.0.1:8050. Both databases are opened read-only
(`mode=ro`), one connection per request.
"""

from __future__ import annotations

import argparse
import sqlite3
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dash import Dash, Input, Output, Patch, State, dcc, html, no_update

from src.foundation.data_processing import db
from src.foundation.market_common.derived_db import default_derived_db_path
from src.foundation.market_common.models import Timeframe
from src.foundation.utils.config_loader import load_config
from src.ui.chart import bars as bars_mod
from src.ui.chart import rs
from src.ui.chart.config import ChartConfig, ChartType
from src.ui.chart.figure import build_figure, y_fit

_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else _ROOT / p


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"no database at {path}")
    return db.get_connection(f"file:{path}?mode=ro", uri=True)


class ChartData:
    """Reads from the two databases. Bars are cached per (ticker, timeframe) for the
    life of the process; restart the app after new data is ingested."""

    def __init__(self, raw_path: Path, derived_path: Path):
        self.raw_path, self.derived_path = raw_path, derived_path
        self.bars = lru_cache(maxsize=32)(self._bars)

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

    def strip(self, ticker: str, change_days: int) -> rs.RSStrip | None:
        """None when the derived database is missing."""
        if not self.derived_path.exists():
            return None
        raw, derived = _read_only(self.raw_path), _read_only(self.derived_path)
        try:
            return rs.rs_strip(raw, derived, ticker, change_days)
        finally:
            raw.close()
            derived.close()


def _ma_options(config: ChartConfig, timeframe: Timeframe) -> list[dict]:
    return [{"label": s.label, "value": s.key} for s in config.ma_options[timeframe]]


def render(data: ChartData, config: ChartConfig, ticker: str, timeframe: Timeframe, chart_type: ChartType,
           ma_keys: list[str], show_volume: bool):
    """(figure or None, strip text pieces, message). Pure apart from `data`'s reads."""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return None, [], "Type a ticker."
    bars = data.bars(ticker, timeframe)
    if bars.empty:
        return None, [], f"No bars for {ticker}."
    specs = tuple(s for s in config.ma_options[timeframe] if s.key in set(ma_keys or []))
    mas = bars_mod.moving_averages(bars["close"], specs)
    fig = build_figure(bars, ticker, timeframe, chart_type, mas, config.ma_options[timeframe],
                       show_volume=show_volume, span_days=config.default_span_days[timeframe])
    strip = data.strip(ticker, config.rs_change_days)
    parts = rs.strip_parts(strip, config.rs_change_days) if strip else ["RS: no derived database"]
    message = f"{ticker} · {timeframe.value} · {len(bars)} bars · last {bars.index.max():%Y-%m-%d}"
    return fig, parts, message


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


def create_app(data: ChartData | None = None, config: ChartConfig | None = None) -> Dash:
    data = data or ChartData.from_config()
    config = config or ChartConfig()
    app = Dash(__name__, title="Chart")

    radio = dict(inline=True, inputStyle={"marginRight": "4px", "marginLeft": "10px"})
    app.layout = html.Div(style={"fontFamily": "system-ui, sans-serif", "padding": "8px"}, children=[
        html.Div(style={"display": "flex", "gap": "16px", "alignItems": "center", "flexWrap": "wrap"}, children=[
            dcc.Input(id="ticker", value=config.default_ticker, debounce=True, type="text",
                      style={"width": "90px", "textTransform": "uppercase", "fontWeight": 600}),
            dcc.RadioItems(id="timeframe", value=Timeframe.DAILY.value, **radio,
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
            html.Div(style={"width": "150px", "flexShrink": 0}, children=[
                html.Div("Moving averages", style={"fontWeight": 600, "marginBottom": "4px"}),
                dcc.Checklist(id="mas", inputStyle={"marginRight": "6px"}),
            ]),
            dcc.Graph(id="chart", style={"flexGrow": 1, "height": "82vh"},
                      config={"scrollZoom": True, "displaylogo": False}),
        ]),
    ])

    @app.callback(Output("mas", "options"), Output("mas", "value"), Input("timeframe", "value"))
    def _ma_menu(timeframe):
        tf = Timeframe(timeframe)
        return _ma_options(config, tf), list(config.ma_defaults[tf])

    @app.callback(Output("chart", "figure"), Output("rs-strip", "children"), Output("message", "children"),
                  Input("ticker", "value"), Input("timeframe", "value"), Input("chart-type", "value"),
                  Input("mas", "value"), Input("volume", "value"))
    def _draw(ticker, timeframe, chart_type, ma_keys, volume):
        fig, parts, message = render(data, config, ticker, Timeframe(timeframe), ChartType(chart_type),
                                     ma_keys, "on" in (volume or []))
        return (fig if fig is not None else {}), [html.Span(p) for p in parts], message

    @app.callback(Output("chart", "figure", allow_duplicate=True), Input("chart", "relayoutData"),
                  State("ticker", "value"), State("timeframe", "value"), State("mas", "value"),
                  State("volume", "value"), prevent_initial_call=True)
    def _refit_y(relayout, ticker, timeframe, ma_keys, volume):
        x_range = x_range_from_relayout(relayout)
        if x_range is None or not ticker:
            return no_update
        tf = Timeframe(timeframe)
        bars = data.bars(ticker.strip().upper(), tf)
        specs = tuple(s for s in config.ma_options[tf] if s.key in set(ma_keys or []))
        fit = y_fit(bars, bars_mod.moving_averages(bars["close"], specs), *x_range)
        if fit is None:
            return no_update
        price_range, volume_top = fit
        patch = Patch()
        patch["layout"]["yaxis"]["range"] = price_range
        if "on" in (volume or []) and volume_top is not None:
            patch["layout"]["yaxis2"]["range"] = [0, volume_top]
        return patch

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.ui.chart.app")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    create_app().run(host="127.0.0.1", port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

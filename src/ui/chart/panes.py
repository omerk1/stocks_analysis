"""Indicator panes below the chart (`docs/features/chart_ui_design.md`, step 4): RSI,
MACD and relative strength against the market. Off by default, not ranked.

Computed here on the bars the chart shows (traded basis, the chart's timeframe),
with the shared `market_common.indicators` wrappers, so a pane always ends on the
chart's last bar. The relative-strength module's stored `rs_mansfield` is only as
fresh as its last batch run, so the pane recomputes it: the ticker's close over the
market's (SPY), and the Mansfield oscillator of that ratio, its distance in % from
its own 52-week average (`indicators.mansfield_rs`, the module's own definition).
On a daily chart the average is 252 days, about the same year.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.models import Timeframe

RSI, MACD, RS = "rsi", "macd", "rs"
PANES = (RSI, MACD, RS)


@dataclass(frozen=True)
class PaneConfig:
    rsi_period: int = 14
    rsi_bands: tuple[float, float] = (30.0, 70.0)
    macd: tuple[int, int, int] = (12, 26, 9)  # fast, slow, signal
    market: str = "SPY"
    mansfield_weeks: int = 52


@dataclass(frozen=True, eq=False)
class Pane:
    key: str
    label: str
    frame: pd.DataFrame


def pane_label(key: str, config: PaneConfig) -> str:
    fast, slow, signal = config.macd
    return {RSI: f"RSI {config.rsi_period}", MACD: f"MACD {fast}/{slow}/{signal}",
            RS: f"RS vs {config.market} (Mansfield)"}[key]


def mansfield_period(timeframe: Timeframe, config: PaneConfig) -> int:
    return config.mansfield_weeks if timeframe == Timeframe.WEEKLY else config.mansfield_weeks * 252 // 52


def pane_frame(key: str, bars: pd.DataFrame, timeframe: Timeframe, config: PaneConfig,
               market: pd.DataFrame | None = None) -> pd.DataFrame:
    """The pane's series on `bars`' index; NaN through warmups. RS needs `market`'s
    bars on the same timeframe; days either side lacks are NaN, not filled."""
    close = bars["close"]
    if key == RSI:
        return pd.DataFrame({"rsi": indicators.rsi(close, config.rsi_period)}, index=bars.index)
    if key == MACD:
        line, signal, hist = indicators.macd(close, *config.macd)
        return pd.DataFrame({"macd": line, "signal": signal, "hist": hist}, index=bars.index)
    if key == RS:
        if market is None or market.empty:
            return pd.DataFrame({"mansfield": float("nan")}, index=bars.index)
        ratio = indicators.ratio(close, market["close"])
        mansfield = indicators.mansfield_rs(ratio, mansfield_period(timeframe, config))
        return pd.DataFrame({"mansfield": mansfield.reindex(bars.index)}, index=bars.index)
    raise ValueError(f"unknown pane {key!r}")


def pane_range(key: str, frame: pd.DataFrame, start, end) -> list[float] | None:
    """The pane's y-range over [start, end]: RSI is always 0-100; the others fit what's
    in the window, with 0 kept in view (both oscillate around it). None when empty."""
    if key == RSI:
        return [0.0, 100.0]
    window = frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
    values = window.stack().dropna() if not window.empty else window
    if len(values) == 0:
        return None
    low, high = min(float(values.min()), 0.0), max(float(values.max()), 0.0)
    pad = (high - low) * 0.08 or 1.0
    return [low - pad, high + pad]

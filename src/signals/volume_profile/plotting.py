"""Plotly chart: candlesticks with one anchored volume profile drawn as a
horizontal histogram on a shared price axis, plus that profile's POC/VAH/
VAL lines from the anchor date to the last bar. Pure consumer of (bars,
profiles) -- the histogram is recomputed on demand via detect.build_for
(the exact call the stored snapshot came from), never read from the DB.

One profile per chart, like TradingView's Anchored VP: several overlapping
histograms on one axis are unreadable. `anchor_date` picks which; by
default the most senior active anchor (ties -> earliest, i.e. the widest
window).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.foundation.market_common.anchors import SENIORITY, AnchorStatus, primary_role
from src.signals.volume_profile.config import VolumeProfileConfig
from src.signals.volume_profile.detect import build_for
from src.signals.volume_profile.models import AnchoredVolumeProfile

# Dataviz skill's validated default palette (light-mode, plotly_white
# export) -- same source as avwap.plotting's _LINE_COLORS.
_UP_COLOR = "#1baf7a"
_DOWN_COLOR = "#e34948"
_TOTAL_COLOR = "#2a78d6"
_POC_COLOR = "#eb6834"
_VA_COLOR = "#4a3aa7"
_WEEKEND_RANGEBREAKS = [dict(bounds=["sat", "mon"])]


def _default_profile(profiles: list[AnchoredVolumeProfile]) -> AnchoredVolumeProfile | None:
    active = [p for p in profiles if p.status == AnchorStatus.ACTIVE] or profiles
    if not active:
        return None
    return min(active, key=lambda p: (SENIORITY[primary_role(p.anchor_types)], p.anchor_date))


def render_volume_profile_chart(
    bars: pd.DataFrame,
    profiles: list[AnchoredVolumeProfile],
    ticker: str,
    timeframe,
    config: VolumeProfileConfig | None = None,
    anchor_date: str | None = None,
) -> go.Figure:
    config = config or VolumeProfileConfig()
    if anchor_date is not None:
        matches = [p for p in profiles if p.anchor_date[:10] == str(anchor_date)[:10]]
        if not matches:
            raise ValueError(f"No stored anchor on {anchor_date}; have {[p.anchor_date[:10] for p in profiles]}")
        chosen = matches[0]
    else:
        chosen = _default_profile(profiles)

    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True, column_widths=[0.8, 0.2], horizontal_spacing=0.01,
    )
    fig.add_trace(go.Candlestick(
        x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
        name=ticker, showlegend=False,
    ), row=1, col=1)

    built = build_for(bars, chosen.anchor_date, config) if chosen is not None else None
    if built is not None:
        mids = built.mids
        widths = built.edges[1:] - built.edges[:-1]
        bar_kw = dict(y=mids, width=widths * 0.9, orientation="h")
        if config.volume_mode == "up_down":
            fig.add_trace(go.Bar(x=built.up, marker_color=_UP_COLOR, name="up volume", **bar_kw), row=1, col=2)
            fig.add_trace(go.Bar(x=built.down, marker_color=_DOWN_COLOR, name="down volume", **bar_kw), row=1, col=2)
        elif config.volume_mode == "delta":
            delta = built.up - built.down
            colors = [_UP_COLOR if d >= 0 else _DOWN_COLOR for d in delta]
            fig.add_trace(go.Bar(x=delta, marker_color=colors, name="delta volume", **bar_kw), row=1, col=2)
        else:
            fig.add_trace(go.Bar(x=built.total, marker_color=_TOTAL_COLOR, name="volume", **bar_kw), row=1, col=2)

        # A DatetimeIndex, not bare Timestamps -- static image export's JSON
        # encoder rejects the latter (HTML export doesn't care).
        span = pd.DatetimeIndex([pd.Timestamp(chosen.anchor_date), bars.index[-1]])
        for level, name, color, dash in (
            (built.poc, "POC", _POC_COLOR, "solid"),
            (built.vah, "VAH", _VA_COLOR, "dash"),
            (built.val, "VAL", _VA_COLOR, "dash"),
        ):
            fig.add_trace(go.Scatter(
                x=span, y=[level, level], mode="lines",
                line=dict(color=color, width=1.5, dash=dash), name=f"{name} {level:.2f}",
            ), row=1, col=1)

    types = "+".join(sorted(t.value for t in chosen.anchor_types)) if chosen else "none"
    anchor_label = f"{chosen.anchor_date[:10]} [{types}]" if chosen else "no anchor"
    fig.update_layout(
        title=(
            f"{ticker} anchored volume profile ({getattr(timeframe, 'value', timeframe)}) -- "
            f"{anchor_label}, {config.row_count} {config.row_scale} rows, "
            f"{config.value_area_pct:.0%} value area"
        ),
        barmode="stack" if config.volume_mode == "up_down" else "relative",
        xaxis_rangeslider_visible=False,
        xaxis_rangebreaks=_WEEKEND_RANGEBREAKS,
        template="plotly_white",
    )
    return fig

"""Plotly overlay for detected fib sets -- pure consumer of FibSet/
FibSwing (plus the raw bars, for candlesticks), same separation as
sr_lines.plotting: no detection logic lives here.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.signals.fibonacci.models import FibLevelKind, FibSet, FibSetStatus

# Categorical palette (dataviz skill's validated default, light-mode column --
# this chart is a static plotly_white export, not a theme-aware artifact, so
# there's no dark surface to also validate against). Assigned by each fib_set's
# position in the input list (its rank, fixed by the caller) so that every
# line belonging to the same swing -- retracement, extension, the swing
# itself, and its 0%/100% boundary -- reads as one visual "range", which is
# the whole point of coloring by set instead of by level-kind: level-kind is
# still legible from dash style (solid=retracement, dash=extension).
_SET_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
_SWING_DASH = "dot"

# Direct labels sit right next to their own colored line, but the label TEXT
# itself stays in muted ink rather than the line's color -- color carries
# series identity, text stays legible/neutral (dataviz skill: "text wears
# text tokens, never the series color").
_LABEL_COLOR = "#52514e"

# Weekend-closed markets leave a blank gap between Friday and Monday
# candles on a plain datetime x-axis -- collapse those empty slots so
# consecutive trading days render adjacent.
_WEEKEND_RANGEBREAKS = [dict(bounds=["sat", "mon"])]

# Floored well above zero (unlike a bare weight-proportional value, which
# could fade a low-weight set toward fully invisible) -- even the weakest
# selected set (already top-max_sets by weight) should stay perceptible and
# hoverable on the chart, mirroring sr_lines.plotting's own marker-opacity
# floor for the same reason.
_MIN_OPACITY = 0.25


def _opacity_for_weight(weight: float) -> float:
    t = max(0.0, min(weight, 1.0))
    return _MIN_OPACITY + (1.0 - _MIN_OPACITY) * t


def _set_color(index: int) -> str:
    return _SET_COLORS[index % len(_SET_COLORS)]


def _segment_end(fib_set: FibSet, last_bar_ts: pd.Timestamp) -> pd.Timestamp:
    if fib_set.status == FibSetStatus.INVALIDATED and fib_set.invalidated_date:
        return pd.Timestamp(fib_set.invalidated_date)
    return last_bar_ts


def _level_label(ratio: float, price: float) -> str:
    return f"{ratio * 100:g}%  {price:.2f}"


def render_fib_chart(bars: pd.DataFrame, fib_sets: list[FibSet]) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
            name="price", showlegend=False,
        )
    )

    last_bar_ts = bars.index[-1] if not bars.empty else pd.Timestamp.now()

    for i, fib_set in enumerate(fib_sets):
        swing = fib_set.swing
        color = _set_color(i)
        opacity = _opacity_for_weight(fib_set.weight)
        start_ts = pd.Timestamp(swing.end_date)
        end_ts = max(_segment_end(fib_set, last_bar_ts), start_ts)
        legend_label = f"{swing.direction.value} x{swing.scale_mult:g} {swing.origin_date[:10]}->{swing.end_date[:10]}"

        # 0% (the swing's own end -- "no retracement yet") and 100% (back to
        # the swing's origin) aren't in config.retracement_ratios (which only
        # holds the strictly-internal ratios) but are exactly as real a level
        # as any other -- drawn here from swing.origin_price/end_price
        # directly, not persisted as FibLevel rows (no schema/detection change).
        render_levels = [
            (0.0, FibLevelKind.RETRACEMENT, swing.end_price),
            (1.0, FibLevelKind.RETRACEMENT, swing.origin_price),
        ] + [(level.ratio, level.kind, level.price) for level in fib_set.levels]

        for ratio, kind, price in render_levels:
            is_retracement = kind == FibLevelKind.RETRACEMENT
            fig.add_trace(
                go.Scatter(
                    x=[start_ts, end_ts], y=[price, price],
                    mode="lines+text",
                    line=dict(color=color, dash="solid" if is_retracement else "dash", width=1.5),
                    opacity=opacity,
                    text=["", _level_label(ratio, price)],
                    textposition="middle right",
                    textfont=dict(size=10, color=_LABEL_COLOR),
                    legendgroup=fib_set.id,
                    name=f"{kind.value} {ratio * 100:g}%",
                    hovertemplate=f"{kind.value} {ratio * 100:g}%: {price:.2f}<extra></extra>",
                    showlegend=False,
                )
            )

        fig.add_trace(
            go.Scatter(
                x=[pd.Timestamp(swing.origin_date), pd.Timestamp(swing.end_date)],
                y=[swing.origin_price, swing.end_price],
                mode="lines+markers",
                line=dict(color=color, width=2, dash=_SWING_DASH),
                marker=dict(size=6, color=color),
                opacity=opacity,
                legendgroup=fib_set.id,
                name=legend_label,
                hovertemplate=(
                    f"{swing.direction.value} swing x{swing.scale_mult:g} weight={fib_set.weight:.2f}<br>"
                    f"{swing.origin_date} @ {swing.origin_price:.2f} -&gt; "
                    f"{swing.end_date} @ {swing.end_price:.2f}<extra></extra>"
                ),
                # One legend entry per set (on its swing trace) toggles every
                # level line + boundary in that set at once via groupclick
                # below -- the only way multiple overlapping sets stay
                # individually reviewable on one chart.
                showlegend=True,
            )
        )

        status_suffix = " [invalidated]" if fib_set.status == FibSetStatus.INVALIDATED else ""
        fig.add_annotation(
            x=pd.Timestamp(swing.end_date), y=swing.end_price,
            text=f"{swing.direction.value} x{swing.scale_mult:g}{status_suffix}",
            showarrow=True, arrowhead=1, arrowcolor=color, opacity=opacity, font=dict(size=10, color=color),
        )

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        xaxis_rangebreaks=_WEEKEND_RANGEBREAKS,
        template="plotly_white",
        legend=dict(groupclick="togglegroup"),
    )
    return fig

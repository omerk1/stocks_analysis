"""Display settings for the chart UI. None of these are tuned against anything, and
none should be tuned against returns: they decide what the chart shows, not what
is true (`docs/features/chart_ui_design.md`, "Default selection")."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.foundation.market_common.models import Timeframe


class ChartType(str, Enum):
    LINE = "line"
    BARS = "bars"
    CANDLES = "candles"


class MAKind(str, Enum):
    SMA = "sma"
    EMA = "ema"


@dataclass(frozen=True)
class MASpec:
    kind: MAKind
    period: int

    @property
    def key(self) -> str:
        return f"{self.kind.value}_{self.period}"

    @property
    def label(self) -> str:
        return f"{self.kind.value.upper()} {self.period}"


def _ma_specs(periods: tuple[int, ...]) -> tuple[MASpec, ...]:
    return tuple(MASpec(kind, p) for kind in MAKind for p in periods)


@dataclass(frozen=True)
class ChartConfig:
    default_ticker: str = "AAPL"
    # Bars shown when a chart opens; zoom out for the rest (the whole history is loaded).
    default_span_days: dict[Timeframe, int] = field(
        default_factory=lambda: {Timeframe.DAILY: 548, Timeframe.WEEKLY: 5 * 365})
    ma_options: dict[Timeframe, tuple[MASpec, ...]] = field(default_factory=lambda: {
        Timeframe.DAILY: _ma_specs((20, 50, 100, 200)),
        Timeframe.WEEKLY: _ma_specs((10, 30, 40)),
    })
    ma_defaults: dict[Timeframe, tuple[str, ...]] = field(default_factory=lambda: {
        Timeframe.DAILY: ("ema_20", "sma_50", "sma_200"),
        Timeframe.WEEKLY: ("sma_10", "sma_40"),
    })
    # The RS strip's "change" compares the latest rating with the last one on or
    # before this many calendar days earlier.
    rs_change_days: int = 28

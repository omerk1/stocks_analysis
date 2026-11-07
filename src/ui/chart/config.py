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
    relevance: "RelevanceConfig" = field(default_factory=lambda: RelevanceConfig())
    panes: "PaneConfig" = field(default_factory=lambda: PaneConfig())


@dataclass(frozen=True)
class PaneConfig:
    """The indicator panes (`panes.py`). The RS pane's market and period are the
    relative-strength module's own (`RelativeStrengthConfig`)."""
    rsi_period: int = 14
    rsi_bands: tuple[float, float] = (30.0, 70.0)
    macd: tuple[int, int, int] = (12, 26, 9)  # fast, slow, signal
    market: str = "SPY"
    mansfield_weeks: int = 52


@dataclass(frozen=True)
class RelevanceConfig:
    """The default selection ("relevant now", design doc). `weight` is the starting
    point of the menu's proximity <-> strength slider: score = weight x proximity +
    (1 - weight) x strength."""
    atr_period: int = 14
    reach_atr: float = 3.0  # farther than this from the last close: not picked by default
    reach_bars: int = 40  # an event (divergence) confirmed longer ago than this: not picked by default
    weight: float = 0.7
    per_family: int = 3
    total: int = 10
    # Within a family, an item this close to one already picked is the same level.
    same_level_atr: float = 0.1
    menu_items_per_family: int = 12  # the menu lists this many alive items per family, best first

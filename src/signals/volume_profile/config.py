"""VolumeProfileConfig -- every tunable knob for the anchored volume
profile (anchor discovery included, via AnchorConfig), kept in one place so
the CLI can drive it without touching compute code (same reasoning as
avwap.config.AvwapConfig / gaps.config.GapConfig).

Defaults follow TradingView's Anchored Volume Profile inputs ("Rows
Layout" / "Row Size" / "Volume" / "Value Area Volume") except where noted.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.foundation.market_common.anchors import AnchorConfig
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS, PriceBasis


@dataclass
class VolumeProfileConfig(AnchorConfig):
    # Anchor-discovery knobs (trailing_window_bars, cycle_scale_mult,
    # cycle_atr_period, max_cycle_anchors, max_anchors_total, min_bars,
    # warmup_bars) are inherited from market_common.anchors.AnchorConfig --
    # the exact same anchors avwap uses, so an anchor's AVWAP line and its
    # volume profile always start on the same bar.

    # Number of price rows the anchor's [lowest low, highest high] range is
    # split into ("Rows Layout: Number of Rows"). TradingView defaults to
    # 24; 100 chosen here because long-lived anchors (an ATL years back)
    # span a wide price range and 24 rows would make the POC too coarse to
    # compare against price. Not a sensitive choice: across 28 tickers the
    # daily POC moved a median 0.02-0.11 ATR between 50/100/200 rows
    # (validate_intraday.py). TradingView's other layout, "Ticks Per Row",
    # is deliberately not offered: a tick size isn't comparable across
    # tickers on daily data.
    row_count: int = 100

    # "linear" (TradingView's only option -- equal-price-width rows) or
    # "log" (equal-percentage-width rows). Log keeps resolution at the low
    # end of an anchor whose price has since moved several-fold -- e.g. a
    # $20 -> $200 run gets ~11 of 100 linear rows below $40, but ~30 log
    # rows. Default switched to "log" (2026-09-29) together with
    # volume_measure="dollars": for AAPL's 1982 anchor the POC goes from
    # $1.76 (linear, shares) to $174 (log, dollars) against a $331 close;
    # for a recent anchor all four combinations agree to within cents.
    row_scale: str = "log"

    # "shares" (TradingView's) or "dollars" (shares x typical price -- the
    # money traded at each price). See compute.build_profile. Stored
    # total/up/down/POC volumes are in this unit.
    volume_measure: str = "dollars"

    # "up_down" (TradingView default), "total" or "delta" -- how each row's
    # volume is split for display (plotting.py). POC and value area are
    # always computed on total volume regardless, as TradingView does; the
    # stored snapshot carries total, up and down volumes either way.
    volume_mode: str = "up_down"

    # Fraction of total volume the value area must contain -- the Market
    # Profile convention (~one standard deviation of a normal), and
    # TradingView's default.
    value_area_pct: float = 0.70

    # How each bar's volume is spread across the rows it overlaps.
    # "uniform_hl": evenly across the bar's [low, high] range -- the
    # standard approximation when only bars (not trades) are available.
    # Applied to whatever bars feed compute.build_profile: today daily/
    # weekly bars (all this project has historically), but the same
    # function takes finer bars (e.g. bars_1h) unchanged if an intraday
    # source ever gets filled in -- that's the plug-in point.
    volume_distribution: str = "uniform_hl"

    # ATR lookback for distance_to_poc_atr -- same default as every other
    # module's atr_period.
    atr_period: int = 14

    # Price series this module computes on -- from the central table in
    # market_common.price_basis (docs/decisions/price-basis.md); recorded
    # with every run via the config. Don't override casually: stored results
    # and the bars they're compared against must share a basis.
    price_basis: PriceBasis = MODULE_PRICE_BASIS["volume_profile"]

"""The capability catalogue: what the platform can compute today, step 2b of the strategy
agent (`docs/strategy-agent/idea.md`, "LLM guardrails" -> "Unsupported requests").

It goes into the extraction prompt, so the LLM knows what exists and can say when an idea
needs something that doesn't, instead of mapping it to the nearest thing that does. A
spec names the entries it is built from in `StrategySpec.uses`, and `find_gaps` refuses
an id that isn't here.

Each entry is written by hand: an id, a one-line description in trading language (what
the LLM matches a user's words against), and `impl`, the code that implements it as
`module:attribute`. Written by hand, but it can't drift from the code without a test
failing (`tests/test_llm_strategy_spec_catalogue.py`):

- every `impl` must import;
- where the code has a fixed list (pattern types, gap kinds, divergence indicators,
  market-structure events, support/resistance events, Fibonacci level kinds, the model
  feature registry, the public functions in `market_common.indicators`), the catalogue
  must match it both ways: a new pattern type with no entry fails, and so does an entry
  for one that was removed;
- the spec's fixed choices (timeframes, normalisations, price basis, execution) aren't
  listed here at all: `render` reads them from `schema.py`, so they exist in one place.

Nothing here imports the signal code: rendering the prompt shouldn't load pandas and the
feature registry. Only the tests resolve `impl`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

Kind = Literal["data", "detector", "indicator", "feature", "control", "metric"]


@dataclass(frozen=True)
class Capability:
    id: str
    kind: Kind
    description: str
    impl: str  # "module:attribute"


def _entries(kind: Kind, prefix: str, impl: str, items: dict[str, str]) -> list[Capability]:
    return [Capability(f"{kind}:{prefix}{name}", kind, text, impl) for name, text in items.items()]


_DB = "src.foundation.data_processing.db"

DATA = [
    Capability("data:bars", "data", "open, high, low, close and volume per bar, split-adjusted, for US stocks "
               "including delisted ones; weekly bars are resampled from daily", f"{_DB}:read_bars"),
    Capability("data:splits", "data", "stock split history", f"{_DB}:read_splits"),
    Capability("data:index_membership", "data", "point-in-time index membership (who was in the index on a date)",
               f"{_DB}:read_index_membership"),
    Capability("data:sector", "data", "each ticker's sector (current, not point-in-time)", f"{_DB}:read_ticker_sector"),
    Capability("data:shares_outstanding", "data", "shares outstanding over time", f"{_DB}:read_shares_outstanding"),
    Capability("data:macro_series", "data", "macroeconomic series from FRED (rates, inflation, ...)",
               f"{_DB}:read_macro_series"),
]

# Examples of data that doesn't exist, so the prompt shows what "unsupported data" means.
NOT_AVAILABLE = (
    "intraday bars", "options data", "earnings dates or surprises", "analyst estimates",
    "news or sentiment", "fundamentals beyond shares outstanding", "short interest",
    "order book or tick data", "non-US markets, futures, forex, crypto",
)

_PATTERNS = "src.signals.patterns.scanner:detect"
DETECTORS = [
    *_entries("detector", "pattern.", _PATTERNS, {
        "double_top": "two peaks at about the same level, confirmed by a close below the trough between them",
        "double_bottom": "two troughs at about the same level, confirmed by a close above the peak between them",
        "triple_top": "three peaks at about the same level, confirmed by a close below the troughs",
        "triple_bottom": "three troughs at about the same level, confirmed by a close above the peaks",
        "reversal_123": "1-2-3 reversal: a swing extreme, a counter-swing, a failed retest, then a break of point 2",
        "head_and_shoulders": "head and shoulders top, confirmed by a close below the neckline",
        "inverse_head_and_shoulders": "inverse head and shoulders bottom, confirmed by a close above the neckline",
        "ascending_triangle": "flat resistance with rising lows, breakout through the flat side",
        "descending_triangle": "flat support with falling highs, breakdown through the flat side",
        "symmetric_triangle": "converging highs and lows, breakout in either direction",
        "rising_wedge": "both trendlines rising and converging, usually resolving down",
        "falling_wedge": "both trendlines falling and converging, usually resolving up",
        "cup_and_handle": "rounded base, a shallow pullback (the handle), breakout above the rim",
        "inverse_cup_and_handle": "inverted rounded top with a handle, breakdown below the rim",
        "rounding_bottom": "a gradual U-shaped base",
        "rounding_top": "a gradual inverted-U top",
        "vcp": "volatility contraction pattern: successively tighter pullbacks, breakout above the last pivot",
        "bull_flag": "a sharp rise (the pole) then a short, tight, downward-sloping consolidation",
        "bear_flag": "a sharp fall then a short, tight, upward-sloping consolidation",
        "pennant": "a sharp move then a short, small symmetric triangle",
    }),
    *_entries("detector", "gap.", "src.signals.gaps.detect:detect_gaps", {
        "classic": "a price gap between two consecutive bars (today's low above yesterday's high, or the reverse), "
                   "tracked until it fills",
        "fvg": "fair value gap: a three-bar imbalance where bar 1's and bar 3's ranges don't overlap",
    }),
    *_entries("detector", "divergence.", "src.signals.divergences.detect:detect_divergences", {
        "rsi": "price and RSI disagree at two swing pivots (regular: reversal reading; hidden: continuation)",
        "macd_hist": "price and the MACD histogram disagree at two swing pivots (regular or hidden)",
        "obv": "price and on-balance volume disagree at two swing pivots (regular or hidden)",
        "volume": "price and volume disagree at two swing pivots (regular or hidden)",
    }),
    *_entries("detector", "structure.", "src.signals.market_structure.detect:track_market_structure", {
        "bos": "break of structure: a close beyond the last same-direction swing, the trend continuing",
        "choch": "change of character: a close beyond the swing that held the opposite side, the trend flipping",
    }),
    *_entries("detector", "sr_line.", "src.signals.sr_lines.events:classify_events", {
        "touch": "a support/resistance zone (horizontal or diagonal) is touched by a wick and holds",
        "body_touch": "the bar's body enters a support/resistance zone, the close stays on its side",
        "wick_fake": "a wick pierces through a support/resistance zone but the bar closes back on its side",
        "body_fake": "a close beyond a support/resistance zone that is reclaimed within a few bars "
                     "(undercut and rally)",
        "break": "a close beyond a support/resistance zone that isn't reclaimed: the level breaks",
    }),
    *_entries("detector", "fibonacci.", "src.signals.fibonacci.engine:detect", {
        "retracement": "Fibonacci retracement levels (38.2%, 50%, 61.8%, ...) of a confirmed swing",
        "extension": "Fibonacci extension levels (127.2%, 161.8%, ...) beyond a confirmed swing",
    }),
    Capability("detector:avwap", "detector", "anchored VWAP from all-time highs/lows, 52-week highs/lows and "
               "swing highs/lows, with price touches and crosses tracked", "src.signals.avwap.compute:anchored_vwap"),
    Capability("detector:volume_profile", "detector", "anchored volume profile: point of control and value area "
               "from the same anchors as anchored VWAP", "src.signals.volume_profile.detect:detect"),
    Capability("detector:ma.first_touch", "detector", "first touch of a moving average after price has been away "
               "from it (SMA or EMA, 20/50/150/200)", "src.signals.moving_averages.features.touch:touch_events"),
    Capability("detector:ma.crossover", "detector", "a fast moving average crossing a slow one (golden or death cross)",
               "src.signals.moving_averages.features.crossover:crossover_events"),
]

_IND = "src.foundation.market_common.indicators"
INDICATORS = [
    Capability("indicator:sma", "indicator", "simple moving average, any length", f"{_IND}:sma"),
    Capability("indicator:ema", "indicator", "exponential moving average, any length", f"{_IND}:ema"),
    Capability("indicator:atr", "indicator", "average true range, any length", f"{_IND}:atr"),
    Capability("indicator:rsi", "indicator", "relative strength index, any length", f"{_IND}:rsi"),
    Capability("indicator:macd", "indicator", "MACD line, signal line and histogram", f"{_IND}:macd"),
    Capability("indicator:obv", "indicator", "on-balance volume", f"{_IND}:obv"),
    Capability("indicator:mansfield_rs", "indicator", "Mansfield relative strength against a benchmark",
               f"{_IND}:mansfield_rs"),
    Capability("indicator:relative_strength", "indicator", "relative strength of a stock against the market "
               "or its sector, as a ratio line and a rank",
               "src.signals.relative_strength.compute:compute_stock_vs_market"),
    Capability("indicator:breadth", "indicator", "market breadth: share of stocks above their moving averages, "
               "advance/decline line", "src.signals.breadth.compute:compute_breadth"),
]

# Public functions in `market_common.indicators` that aren't indicators a user would ask
# for, with why. The drift test needs every public function to be here or in INDICATORS.
NOT_USER_FACING_INDICATORS = {
    "ratio": "the price ratio behind relative strength (indicator:mansfield_rs)",
    "percentile_rank": "a normalisation (the spec's `percentile`), not an indicator",
    "scale_consistent": "a sanity check on two prices' scale",
}

# The model feature registry's model inputs (`src/models/features/registry.py`).
_REG = "src.models.features.registry:REGISTRY"
FEATURES = _entries("feature", "", _REG, {
    "mom_12_1": "12-month momentum skipping the last month",
    "realized_vol_63": "63-day realised volatility",
    "mom_1_0": "last month's return (short-term reversal)",
    "dist_pct_sma_50": "distance from the 50-day SMA, in percent",
    "sector": "the ticker's sector",
    "slope_log_21_sma_50": "slope of the 50-day SMA over 21 days, on log prices",
    "ribbon_agreement_state": "whether the moving averages' slopes agree in direction",
    "dist_z_sma_20": "distance from the 20-day SMA as a trailing z-score",
    "dist_from_52w_low": "distance from the 52-week low",
    "stack_fully_bearish": "every moving average below the next longer one",
    "log_dollar_volume_20d": "20-day average dollar volume, log scale (size and liquidity)",
    "macd_hist_pct": "MACD histogram as a percent of price",
    "ribbon_width_pctile": "spread of the moving-average ribbon as a trailing percentile",
    "dist_z_sma_200": "distance from the 200-day SMA as a trailing z-score",
    "slope_log_63_sma_50": "slope of the 50-day SMA over 63 days, on log prices",
    "adx_14": "ADX(14) trend strength",
    "bb_width_pctile": "Bollinger band (20, 2) width as a trailing 252-day percentile (squeeze)",
    "atr_ratio_5_63": "5-day ATR over 63-day ATR (volatility contraction or expansion)",
    "rvol_21_pctile_252": "21-day realised volatility against its own trailing year",
    "rel_volume_20": "volume relative to its 20-day average",
    "updown_volume_20": "share of volume on up days over 20 days",
    "rsi_14": "RSI(14)",
    "spy_dist_sma_200": "S&P 500 ETF distance from its 200-day SMA (market regime)",
    "spy_slope_log_63": "slope of the S&P 500 ETF's 50-day SMA over 63 days",
    "spy_rvol_21": "S&P 500 ETF 21-day realised volatility",
    "breadth_above_sma50": "share of index members above their 50-day SMA",
    "breadth_above_sma200": "share of index members above their 200-day SMA",
    "adv_dec_10": "10-day advance/decline balance",
    "sector_rel_mom_63": "63-day momentum relative to the sector median",
    "sector_rank_mom_63": "63-day momentum rank within the sector",
})

_CTL = "src.signals.moving_averages.stats.controls"
CONTROLS = [
    Capability("control:unconditional", "control", "the event's average outcome minus every stock-day's "
               "(the weakest control)", f"{_CTL}:c0_delta"),
    Capability("control:same_date", "control", "the event minus other stocks on the same dates", f"{_CTL}:c1_delta"),
    Capability("control:matched", "control", "the event minus stocks on the same date with similar momentum, "
               "volatility and sector", f"{_CTL}:c2_delta"),
    Capability("control:placebo_ma", "control", "the same event at nearby moving-average lengths "
               "(e.g. 187/193/207/213 around the 200-day)",
               "src.signals.moving_averages.features.placebo_ma:build_placebo_panel"),
    Capability("control:matched_pivot_pairs", "control", "swing-pivot pairs without the divergence, matched "
               "on date and context", "src.signals.divergences.controls:build_control_pairs"),
]

_FWD = "src.signals.moving_averages.labels.forward_returns"
_SHAPE = "src.signals.moving_averages.stats.shape"
METRICS = [
    Capability("metric:forward_return", "metric", "return from entry to N bars later", f"{_FWD}:forward_return"),
    Capability("metric:forward_volatility", "metric", "realised volatility over the N bars after entry",
               f"{_FWD}:forward_realized_vol"),
    Capability("metric:max_adverse_excursion", "metric", "worst drawdown touched within N bars after entry (MAE); "
               "the favourable side (MFE) isn't built",
               "src.signals.moving_averages.labels.path_metrics:forward_max_drawdown"),
    Capability("metric:hit_rate", "metric", "share of events with a positive outcome, against the control's",
               f"{_SHAPE}:hit_rate_deltas"),
    Capability("metric:win_loss_ratio", "metric", "average win over average loss", f"{_SHAPE}:distribution_shape"),
    Capability("metric:skew", "metric", "skew of the outcome distribution", f"{_SHAPE}:distribution_shape"),
    Capability("metric:barrier_outcome", "metric", "whether an ATR-sized target or stop is hit first within N bars",
               "src.models.labels.barriers:barrier_labels"),
    Capability("metric:expected_value", "metric", "expected value of a target/stop trade, in ATR units",
               "src.models.metrics:expected_value"),
    Capability("metric:top_k", "metric", "outcome of the top k ranked names each day", "src.models.metrics:top_k_daily"),
    Capability("metric:cost_hurdle", "metric", "signals per year times round-trip cost, the gross edge must clear it",
               "src.signals.moving_averages.stats.costs:cost_hurdle"),
    Capability("metric:bootstrap_ci", "metric", "confidence interval by block bootstrap over dates",
               "src.signals.moving_averages.stats.inference:block_bootstrap_delta"),
]

CATALOGUE: tuple[Capability, ...] = (*DATA, *DETECTORS, *INDICATORS, *FEATURES, *CONTROLS, *METRICS)
IDS: frozenset[str] = frozenset(c.id for c in CATALOGUE)

_HEADINGS = {
    "data": "Data", "detector": "Events and detectors", "indicator": "Indicators",
    "feature": "Precomputed features", "control": "Controls (what an event is compared against)",
    "metric": "Outcome metrics",
}


def render() -> str:
    """The catalogue as prompt text: the spec's fixed choices, then every entry by kind."""
    from src.llm.strategy_spec import schema  # lazy: schema imports this module

    def options(name: str, literal) -> str:
        return f"- {name}: {', '.join(get_args(literal))}"

    lines = [
        "# What the platform can test",
        "",
        "## Spec options",
        options("timeframe", schema.Timeframe),
        options("size normalisation", schema.Normalisation),
        options("trigger price basis", schema.PriceBasis),
        options("trigger execution", schema.Execution),
        "- horizons: any whole number of bars (of the spec's timeframe) after entry",
        "(raw_price and same_close record an idea stated that way; the gap check flags both.)",
        "",
        f"Not available: {', '.join(NOT_AVAILABLE)}.",
    ]
    for kind in get_args(Kind):
        lines += ["", f"## {_HEADINGS[kind]}"]
        lines += [f"- {c.id}: {c.description}" for c in CATALOGUE if c.kind == kind]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render(), end="")

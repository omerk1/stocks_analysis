"""DivergenceConfig -- every tunable knob for RSI/MACD-histogram/OBV/volume
price-divergence detection, kept in one place so the CLI/plotting can drive
it without touching detection code (same reasoning as sr_lines.config.
SRConfig / gaps.config.GapConfig).
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _default_strength_weights() -> dict:
    return {"indicator_gap": 0.5, "price_move": 0.3, "span": 0.2}


def _default_indicators() -> list[str]:
    return ["rsi", "macd_hist", "obv"]


@dataclass
class DivergenceConfig:
    # Which indicators to evaluate. "volume" is a valid value (log(volume),
    # 5-bar smoothed) but off by default -- volume divergence is a noisier,
    # less-established signal than RSI/MACD-hist/OBV.
    indicators: list[str] = field(default_factory=_default_indicators)
    rsi_period: int = 14
    macd_params: tuple[int, int, int] = (12, 26, 9)  # fast, slow, signal
    # Not called out separately in indicators/macd_params above, but needed
    # for both price-pivot sizing (price_pivot_atr_mult below) and the
    # price_move strength component -- same 14-bar default sr_lines/gaps
    # both already use.
    atr_period: int = 14

    # Price-pivot detection (on close): reversal must clear this x ATR.
    price_pivot_atr_mult: float = 2.0
    # RSI-pivot detection: flat threshold in RSI points, not ATR-scaled --
    # RSI's own 0-100 scale is already a fixed unit, unlike price/MACD-hist/
    # OBV whose natural scale varies by ticker and time.
    rsi_reversal_points: float = 5.0
    # Rolling window (bars) for the std-based thresholds used by
    # macd_hist/obv/volume pivot detection below.
    std_window: int = 100
    std_reversal_mult: float = 1.0

    # Max bar distance to pair a price pivot with an indicator pivot of the
    # same kind (HIGH/LOW).
    pairing_window: int = 3
    # Discard a price-pivot pair whose two pivots are closer together than
    # this -- too short a span for a divergence claim to mean much.
    min_pivot_span_bars: int = 5
    # Tolerance (x ATR at the second pivot) for judging price "equal or
    # higher/lower" in bearish/bullish evaluation. 0.0 = strict inequality.
    extreme_equality_tolerance_atr: float = 0.0

    strength_weights: dict = field(default_factory=_default_strength_weights)
    # Normalization caps for the three strength components -- a pair whose
    # raw indicator_gap/price_move/span meets or exceeds its cap maps to
    # that component's full [0, 1] weight. indicator_gap_cap is in units of
    # "x the raw indicator magnitude", price_move_cap in "x ATR", span_cap
    # in bars.
    indicator_gap_cap: float = 3.0
    price_move_cap: float = 6.0
    span_cap_bars: int = 60

    # Skip (ticker, timeframe) with fewer rows than this after filtering --
    # log a warning, don't attempt detection on too short a history.
    min_bars: int = 150
    # Skip this many leading bars of each series for detection purposes --
    # guarantees every indicator/ATR/rolling-std series is fully warmed up
    # (no NaN warmup tail) before any pivot search starts.
    warmup_bars: int = 50

    # Outcome tracking (see lifecycle.apply_outcome). Forward window, in
    # bars past confirmed_at, for measuring whether the divergence's
    # implied reversal actually happened -- longer than
    # SRConfig/FibConfig/AvwapConfig's touch_reaction_window_bars=10 since
    # a divergence's thesis is a multi-bar trend reversal, not an
    # immediate single-touch bounce. Starting point, not validated.
    outcome_window_bars: int = 20

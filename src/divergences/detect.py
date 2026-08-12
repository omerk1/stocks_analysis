"""RSI/MACD-histogram/OBV/volume price-divergence detection: indicator
pivots, price/indicator pairing, and pairwise evaluation into `Divergence`
rows, plus the top-level `detect()` entry point that loads/validates bars
and runs the full pipeline for one (ticker, timeframe) as of a given date.

`detect_for_indicator` is a pure function over an already-loaded bars frame
plus an already-computed indicator series -- no DB access, no indicator
computation, no as_of handling -- so synthetic tests can hand it small,
hand-built bars *and* a hand-built indicator series directly, independent of
the real talib-backed indicators in `market_common.indicators`. `detect()`
is the only place as_of actually gets applied (via
`market_common.data.load_and_validate` plus a final confirmed_at filter),
which is what guarantees zero lookahead.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import date

import numpy as np
import pandas as pd

from src.divergences.config import DivergenceConfig
from src.divergences.lifecycle import apply_outcome
from src.divergences.models import Direction, Divergence, IndicatorKind, Timeframe
from src.market_common import data as data_mod
from src.market_common import indicators
from src.market_common.models import DataQualityReport, Pivot, PivotKind
from src.market_common.pivots import detect_pivots

logger = logging.getLogger(__name__)

_STD_BASED_INDICATORS = {"macd_hist", "obv", "volume"}


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _warmup_offset(n: int, warmup_bars: int) -> int:
    # Never slice away so much that fewer than 2 bars remain -- detect_pivots
    # itself already handles n < 2 gracefully, this just avoids clipping a
    # short series down to nothing before it even gets there.
    return min(warmup_bars, max(n - 2, 0))


def _warmup_for(indicator_name: str, config: DivergenceConfig) -> int:
    """RSI's threshold is a flat constant, so `config.warmup_bars` alone is
    enough lookback. macd_hist/obv/volume confirm pivots against a rolling
    std that itself needs `config.std_window` bars before it's non-NaN --
    with the defaults (std_window=100 > warmup_bars=50), slicing at
    warmup_bars alone left a ~49-bar NaN tail in the confirmation threshold,
    so any candidate pivot whose bar fell in that gap could never confirm
    and was silently, permanently dropped once a later bar replaced it as
    the running candidate. Using the larger of the two closes that gap."""
    if indicator_name == "rsi":
        return config.warmup_bars
    return max(config.warmup_bars, config.std_window)


def _price_pivots_and_atr(
    bars: pd.DataFrame, config: DivergenceConfig, warmup_bars: int
) -> tuple[list[Pivot], pd.Series]:
    """Price pivots on close, ATR-scaled reversal threshold. Returns the
    pivots plus the *warmup-sliced* ATR series (same slice offset applied to
    close before pivot detection), so callers can look up ATR at any
    resulting pivot's own `bar_index` directly via `.iloc[]`.

    `warmup_bars` is the caller's already-resolved effective offset (see
    `_warmup_for`), not read off `config.warmup_bars` directly -- it must
    match whatever offset the paired `_indicator_pivots` call used, since
    `_pair_pivots`' distance matching only makes sense if both pivot lists'
    `bar_index` values share the same slice origin.
    """
    atr_series = indicators.atr(bars, config.atr_period)
    warmup = _warmup_offset(len(bars), warmup_bars)
    close_s = bars["close"].iloc[warmup:]
    atr_s = atr_series.iloc[warmup:]

    pivots = detect_pivots(close_s, threshold_fn=lambda i: config.price_pivot_atr_mult * atr_s.iloc[i])
    return pivots, atr_s


def _indicator_pivots(
    indicator_name: str, indicator_series: pd.Series, config: DivergenceConfig, warmup_bars: int
):
    """Indicator pivots plus a `magnitude_at(bar_index)` callable usable
    against the same warmup-sliced position space as the price pivots
    returned by `_price_pivots_and_atr` (both slice by the same
    `warmup_bars` offset off series that share the same original index --
    see `_warmup_for` for why that offset can differ from plain
    `config.warmup_bars`).

    RSI uses a flat points threshold for both confirming pivots *and* as the
    strength-score magnitude. macd_hist/obv/volume confirm pivots against
    `std_reversal_mult * rolling_std` but the strength score's `indicator_gap`
    needs the *raw*, unscaled rolling std -- otherwise strength would be an
    artifact of the confirmation-sensitivity knob rather than the divergence
    itself (the same threshold_fn/magnitude_fn split `market_common.pivots`
    already draws for exactly this reason). The rolling std is computed on
    the *full*, unsliced series first (so the window's own warmup draws on
    real pre-cutoff history) and only sliced afterward, matching ATR above.
    """
    warmup = _warmup_offset(len(indicator_series), warmup_bars)
    series_s = indicator_series.iloc[warmup:]

    if indicator_name == "rsi":
        threshold_at = lambda i: config.rsi_reversal_points  # noqa: E731
        magnitude_at = threshold_at
    else:
        std_full = indicator_series.rolling(config.std_window).std()
        std_s = std_full.iloc[warmup:]
        threshold_at = lambda i: config.std_reversal_mult * std_s.iloc[i]  # noqa: E731
        magnitude_at = lambda i: std_s.iloc[i]  # noqa: E731

    pivots = detect_pivots(series_s, threshold_fn=threshold_at)
    return pivots, magnitude_at


def _pair_pivots(
    price_pivots: list[Pivot], indicator_pivots: list[Pivot], pairing_window: int
) -> dict[int, Pivot]:
    """For each price pivot, in chronological order, claim the nearest
    still-unclaimed same-kind indicator pivot within `pairing_window` bars
    (ties broken by the earlier indicator pivot). Once an indicator pivot is
    claimed by an earlier price pivot it is unavailable to a later one --
    this is a single pass across all price pivots, not independent
    per-pivot searches, so two price pivots can never both claim the same
    indicator pivot.

    Returns {price_pivot.bar_index: matched indicator Pivot}; price pivots
    with no match within the window are simply absent from the result.
    """
    claimed: set[int] = set()
    paired: dict[int, Pivot] = {}

    for pp in price_pivots:
        best_idx = None
        best_key = None
        for idx, ip in enumerate(indicator_pivots):
            if idx in claimed or ip.kind != pp.kind:
                continue
            dist = abs(ip.bar_index - pp.bar_index)
            if dist > pairing_window:
                continue
            key = (dist, ip.bar_index)
            if best_key is None or key < best_key:
                best_key = key
                best_idx = idx
        if best_idx is not None:
            paired[pp.bar_index] = indicator_pivots[best_idx]
            claimed.add(best_idx)

    return paired


def _evaluate_pairs(
    price_pivots: list[Pivot],
    paired: dict[int, Pivot],
    atr_s: pd.Series,
    magnitude_at,
    config: DivergenceConfig,
    ticker: str,
    timeframe: Timeframe,
    indicator_name: str,
) -> list[Divergence]:
    """Evaluate every pair of CONSECUTIVE same-kind price pivots (k, k+1) --
    consecutive within the HIGH-only or LOW-only subsequence, i.e. skipping
    over any opposite-kind pivots in between, which is how "two swing highs
    in a row" is normally read on a chart even though detect_pivots' own
    output alternates HIGH/LOW/HIGH/... Chained triples (k,k+1) and
    (k+1,k+2) both qualifying produce two separate rows, never merged.
    """
    results: list[Divergence] = []
    weights = config.strength_weights

    for kind, direction in (
        (PivotKind.HIGH, Direction.BEARISH),
        (PivotKind.LOW, Direction.BULLISH),
    ):
        same_kind = [p for p in price_pivots if p.kind == kind]
        for k in range(len(same_kind) - 1):
            p1, p2 = same_kind[k], same_kind[k + 1]
            if p2.bar_index - p1.bar_index < config.min_pivot_span_bars:
                continue

            ip1 = paired.get(p1.bar_index)
            ip2 = paired.get(p2.bar_index)
            if ip1 is None or ip2 is None:
                continue

            atr_at_p1 = atr_s.iloc[p1.bar_index]
            atr_at_p2 = atr_s.iloc[p2.bar_index]
            if pd.isna(atr_at_p2) or atr_at_p2 <= 0:
                continue
            if not indicators.scale_consistent(atr_at_p1, atr_at_p2):
                # p1/p2 straddle a regime change (almost always a large
                # stock split -- see scale_consistent's docstring): a raw
                # price/indicator delta spanning them, normalized by only
                # one end's ATR/magnitude, would be off by whatever factor
                # caused the regime change, not a real move size.
                continue
            tol = config.extreme_equality_tolerance_atr * atr_at_p2

            if kind == PivotKind.HIGH:
                price_cond = p2.value > p1.value - tol
                indicator_cond = ip2.value < ip1.value
            else:
                price_cond = p2.value < p1.value + tol
                indicator_cond = ip2.value > ip1.value

            if not (price_cond and indicator_cond):
                continue

            mag = magnitude_at(p2.bar_index)
            mag_at_p1 = magnitude_at(p1.bar_index)
            mag_reliable = not (pd.isna(mag) or mag <= 0 or not indicators.scale_consistent(mag_at_p1, mag))
            # Raw (pre-clip) values, kept on the row for anyone using them as
            # model features -- see Divergence's own field docstring for why
            # these aren't just recoverable from the clipped components.
            indicator_gap_raw = abs(ip2.value - ip1.value) / mag if mag_reliable else None
            price_move_atr = abs(p2.value - p1.value) / atr_at_p2
            duration_bars = p2.bar_index - p1.bar_index

            indicator_gap = (
                0.0 if indicator_gap_raw is None
                else _clip01(indicator_gap_raw / config.indicator_gap_cap)
            )
            price_move = _clip01(price_move_atr / config.price_move_cap)
            span = _clip01(duration_bars / config.span_cap_bars)
            strength = (
                weights["indicator_gap"] * indicator_gap
                + weights["price_move"] * price_move
                + weights["span"] * span
            )

            confirmed_at = max(pd.Timestamp(p2.confirmed_at), pd.Timestamp(ip2.confirmed_at))

            results.append(
                Divergence(
                    id=str(uuid.uuid4()),
                    ticker=ticker,
                    timeframe=Timeframe(timeframe),
                    indicator=IndicatorKind(indicator_name),
                    direction=direction,
                    p1_date=p1.timestamp,
                    p2_date=p2.timestamp,
                    p1_price=p1.value,
                    p2_price=p2.value,
                    i1_value=ip1.value,
                    i2_value=ip2.value,
                    strength=strength,
                    duration_bars=duration_bars,
                    price_move_atr=price_move_atr,
                    indicator_gap_raw=indicator_gap_raw,
                    appeared_at=p2.timestamp,
                    confirmed_at=confirmed_at.isoformat(),
                )
            )

    return results


def detect_for_indicator(
    bars: pd.DataFrame,
    indicator_name: str,
    indicator_series: pd.Series,
    config: DivergenceConfig,
    ticker: str,
    timeframe: Timeframe,
    price_cache: dict[int, tuple[list[Pivot], pd.Series]] | None = None,
) -> list[Divergence]:
    """Full pivot-pairing + evaluation pipeline for one indicator, given an
    already-computed `indicator_series` sharing `bars`' index. Kept separate
    from `detect_divergences` so tests can hand-construct both `bars` and
    `indicator_series` directly, without depending on the real talib-backed
    indicator computation for deterministic pivot placement.

    `price_cache`, if given, memoizes `_price_pivots_and_atr`'s result by the
    effective warmup value (see `_warmup_for`) -- price pivots/ATR depend
    only on `bars`/`config`/that offset, not on which indicator is being
    evaluated, so indicators sharing the same std_window-driven offset (any
    two of macd_hist/obv/volume) reuse one computation instead of repeating
    an identical O(n) ATR + pivot-detection pass per indicator.
    `detect_divergences` passes one shared cache across its whole
    `config.indicators` loop; direct callers (including this module's own
    tests) are unaffected since it defaults to None.
    """
    if len(bars) < 3 or len(indicator_series) < 3:
        return []

    warmup_bars = _warmup_for(indicator_name, config)
    if price_cache is not None and warmup_bars in price_cache:
        price_pivots, atr_s = price_cache[warmup_bars]
    else:
        price_pivots, atr_s = _price_pivots_and_atr(bars, config, warmup_bars)
        if price_cache is not None:
            price_cache[warmup_bars] = (price_pivots, atr_s)

    indicator_pivots, magnitude_at = _indicator_pivots(indicator_name, indicator_series, config, warmup_bars)
    paired = _pair_pivots(price_pivots, indicator_pivots, config.pairing_window)
    return _evaluate_pairs(
        price_pivots, paired, atr_s, magnitude_at, config, ticker, timeframe, indicator_name
    )


def compute_indicator_series(
    bars: pd.DataFrame, indicator_name: str, config: DivergenceConfig
) -> pd.Series:
    if indicator_name == "rsi":
        return indicators.rsi(bars["close"], config.rsi_period)
    if indicator_name == "macd_hist":
        _, _, hist = indicators.macd(bars["close"], *config.macd_params)
        return hist
    if indicator_name == "obv":
        return indicators.obv(bars["close"], bars["volume"])
    if indicator_name == "volume":
        # log + 5-bar SMA smoothing before the same rolling-std pivot
        # machinery as macd_hist/obv -- raw volume is far too spiky
        # bar-to-bar for a flat or even rolling-std threshold to produce
        # anything but noise-driven pivots.
        log_vol = np.log(bars["volume"].clip(lower=1e-9))
        return log_vol.rolling(5).mean()
    raise ValueError(f"Unknown divergence indicator: {indicator_name!r}")


def detect_divergences(
    bars: pd.DataFrame, ticker: str, timeframe: Timeframe, config: DivergenceConfig
) -> list[Divergence]:
    """Pure function over an already-loaded/validated bars frame -- runs
    `detect_for_indicator` for every indicator in `config.indicators`, sharing
    one price-pivot cache across the whole loop (see `detect_for_indicator`'s
    `price_cache` param), then walks each resulting divergence's outcome
    forward from its own `confirmed_at` (see `lifecycle.apply_outcome`).

    The outcome walk deliberately uses a fresh, *unwarmup-sliced* ATR series
    over the full `bars` frame -- unlike `atr_s` inside `_evaluate_pairs`
    (warmup-sliced to match whichever indicator's pivot-detection offset
    produced the pair), outcome tracking has nothing to do with pivot
    detection and needs to reach every bar after `confirmed_at`, which can
    fall well past any single indicator's own warmup-trimmed pivot series.
    """
    if len(bars) < 3:
        return []

    price_cache: dict[int, tuple[list[Pivot], pd.Series]] = {}
    results: list[Divergence] = []
    for name in config.indicators:
        series = compute_indicator_series(bars, name, config)
        results.extend(detect_for_indicator(bars, name, series, config, ticker, timeframe, price_cache))

    if results:
        outcome_atr = indicators.atr(bars, config.atr_period)
        for divergence in results:
            apply_outcome(bars, outcome_atr, divergence, config)

    return results


def detect(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: Timeframe | str,
    config: DivergenceConfig,
    as_of: str | pd.Timestamp | date | None = None,
) -> tuple[list[Divergence], DataQualityReport, str | None]:
    """Load+validate bars for (ticker, timeframe) up to `as_of`, detect
    divergences, and keep only those confirmed by `as_of`. Returns
    (divergences, quality_report, skip_reason) -- skip_reason is None on
    success, otherwise divergences is [] and quality_report still reflects
    what was loaded (so callers/CLI can report *why* a ticker was skipped).

    Bars are already truncated to `as_of` by `load_and_validate`, so every
    pivot's `confirmed_at` is already <= as_of by construction -- the
    explicit filter below is a defensive, spec-mandated belt-and-braces
    check, not dead weight covering a real gap in the truncation.
    """
    timeframe = Timeframe(timeframe)
    bars, report = data_mod.load_and_validate(conn, ticker, timeframe, as_of=as_of)

    if len(bars) < config.min_bars:
        reason = f"only {len(bars)} bars available (< min_bars={config.min_bars})"
        logger.warning("%s/%s: skipping divergence detection -- %s", ticker, timeframe.value, reason)
        return [], report, reason

    divergences = detect_divergences(bars, ticker, timeframe, config)

    if as_of is not None:
        as_of_ts = pd.Timestamp(as_of)
        divergences = [d for d in divergences if pd.Timestamp(d.confirmed_at) <= as_of_ts]

    return divergences, report, None

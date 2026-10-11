"""Per-ticker indicator features for the combined model (`VALIDATION_HARNESS.md`
§9 step 6, step 2b): volatility regime, volume structure and one oscillator,
on the harness's timing (row t = close of t). Every prior is null (`IDEAS.md`
§2: untested, or inconclusive in the MA study).

The list is the lean one (one column per idea, `IDEAS.md` §2's near-copy
rule), decided 2026-10-10:
- RSI(14) is the one oscillator. %K, Williams %R (= 100 - %K) and Bollinger %b
  are left out: M17 put RSI/%K at corr 0.86 with `dist_z_sma_20`, already in
  the model, and %b is another z-score of the close around SMA20.
- OBV slope, made scale-free, is the signed share of volume
  (`updown_volume_20`), so it isn't a second column.

Every column is a ratio, a share or a trailing percentile, so a later split or
dividend (which rescales every earlier adjusted price and volume) leaves it
unchanged. Up/down days use `TIE_TOLERANCE`, as ADX does (`ma_family.adx`):
a flat close on cent prices is neither up nor down, whatever float noise a
later rescaling adds. Zero-width windows (a flat price) are pinned to 0 for
the same reason, rather than left to rolling-sum residue.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.foundation.market_common import indicators
from src.models.features.ma_family import TIE_TOLERANCE
from src.signals.moving_averages.features import oscillators

BOLLINGER_WINDOW = 20
BOLLINGER_K = 2.0
PCTILE_WINDOW = 252          # one trading year of the ticker's own history
PCTILE_DECIMALS = 9
RVOL_WINDOW = 21
ATR_FAST, ATR_SLOW = 5, 63
VOLUME_WINDOW = 20

INDICATOR_COLUMNS = (
    "rsi_14", "bb_width_pctile", "atr_ratio_5_63", "rvol_21_pctile_252", "rel_volume_20", "updown_volume_20",
)


def trailing_pctile(x: pd.Series, window: int = PCTILE_WINDOW) -> pd.Series:
    """Where today's value sits among the trailing `window` values (today's
    included), as a percentile in (0, 1]: the ticker against its own history,
    never a full-sample statistic.

    `x` is rounded first. Two windows of cent prices can hold the same values
    (the price dropped equals the one added), so their widths or vols tie
    exactly; pandas' running-sum rolling std then breaks the tie in float
    after a later split or dividend, and the rank at t would depend on it
    (caught by the leakage gate)."""
    return x.round(PCTILE_DECIMALS).rolling(window, min_periods=window).rank(pct=True)


def bollinger_width(close: pd.Series, window: int = BOLLINGER_WINDOW, k: float = BOLLINGER_K) -> pd.Series:
    """Band width over the middle band, (upper - lower) / SMA = 2k sd / SMA;
    exactly 0 for a flat window."""
    sma = close.rolling(window, min_periods=window).mean()
    sd = close.rolling(window, min_periods=window).std(ddof=0)
    return (2 * k * sd / sma).mask(sd <= TIE_TOLERANCE * close.abs(), 0.0)


def up_down(close: pd.Series) -> pd.Series:
    """+1 / -1 / 0 for a close above / below / equal to the previous close
    (within `TIE_TOLERANCE`); NaN on the first bar."""
    diff = close.diff()
    eps = TIE_TOLERANCE * close.abs()
    sign = pd.Series(np.where(diff > eps, 1.0, np.where(diff < -eps, -1.0, 0.0)), index=close.index)
    return sign.where(diff.notna())


def ticker_features(bars: pd.DataFrame) -> pd.DataFrame:
    """One ticker's indicator columns from its bars (indexed by date; high,
    low, close, volume), each known at that date's close."""
    close, volume = bars["close"], bars["volume"].astype(float)

    rvol = close.pct_change().rolling(RVOL_WINDOW, min_periods=RVOL_WINDOW).std()
    rvol = rvol.mask(rvol <= TIE_TOLERANCE, 0.0)

    vol_sum = volume.rolling(VOLUME_WINDOW, min_periods=VOLUME_WINDOW).sum()
    signed = (up_down(close) * volume).rolling(VOLUME_WINDOW, min_periods=VOLUME_WINDOW).sum()
    atr_slow = indicators.atr(bars, ATR_SLOW)

    return pd.DataFrame({
        "rsi_14": oscillators.rsi(close, 14),
        "bb_width_pctile": trailing_pctile(bollinger_width(close)),
        # Below 1: a squeeze (recent range narrower than the quarter's); above: expansion.
        "atr_ratio_5_63": indicators.atr(bars, ATR_FAST) / atr_slow.where(atr_slow > 0),
        "rvol_21_pctile_252": trailing_pctile(rvol),
        # Today's volume over its trailing mean (today included); undefined on no
        # volume. Rounded: it gets a per-date rank, and exact ties across tickers
        # (e.g. round lots) mustn't be broken by a later split's float noise.
        "rel_volume_20": (volume / (vol_sum / VOLUME_WINDOW).where(vol_sum > 0)).round(PCTILE_DECIMALS),
        # (up-day volume - down-day volume) / all volume over the window: OBV's
        # 20-day change, scale-free. In [-1, 1].
        "updown_volume_20": signed / vol_sum.where(vol_sum > 0),
    }, index=close.index).astype("float32")

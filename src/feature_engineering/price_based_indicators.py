import pandas as pd
import talib


def moving_average(original_signal: pd.Series, window: int) -> pd.Series:
    return original_signal.rolling(window=window).mean()


def exponential_moving_average(
    original_signal: pd.Series, window: int
) -> pd.Series:
    return talib.EMA(original_signal, timeperiod=window)


def relative_strength_index(
    original_signal: pd.Series, window: int = 14
) -> pd.Series:
    return talib.RSI(original_signal, timeperiod=window)


def moving_average_convergence_divergence(
    original_signal: pd.Series,
    fastperiod: int = 12,
    slowperiod: int = 26,
    signalperiod: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd, macd_signal, macd_hist = talib.MACD(
        original_signal,
        fastperiod=fastperiod,
        slowperiod=slowperiod,
        signalperiod=signalperiod,
    )
    return macd, macd_signal, macd_hist


def bollinger_bands(
    original_signal: pd.Series,
    timeperiod: int = 20,
    nbdevup: int = 2,
    nbdevdn: int = 2,
    matype: int = 0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    upper_bb, middle_bb, lower_bb = talib.BBANDS(
        original_signal,
        timeperiod=timeperiod,
        nbdevup=nbdevup,
        nbdevdn=nbdevdn,
        matype=matype,
    )
    return upper_bb, middle_bb, lower_bb


def bollinger_band_width(
    upper_bb: pd.Series, lower_bb: pd.Series, middle_bb: pd.Series
) -> pd.Series:
    """Absolute band width normalized by the middle band (%): (upper - lower)
    / middle * 100. Widens in high-volatility regimes, squeezes in low ones."""
    return (upper_bb - lower_bb) / middle_bb * 100


def bollinger_band_width_atr(
    upper_bb: pd.Series, lower_bb: pd.Series, atr: pd.Series
) -> pd.Series:
    """Band width expressed in ATR units: (upper - lower) / atr. Lets width
    be compared across regimes/tickers independent of the price-vs-volatility
    normalization %-of-price uses; pass `average_true_range` from
    `trend_indicators.py` (same timeperiod as the bands, ideally)."""
    return (upper_bb - lower_bb) / atr

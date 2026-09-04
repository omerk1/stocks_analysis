import pandas as pd
import talib


def stochastic_oscillator(
    highs_signal: pd.Series,
    lows_signal: pd.Series,
    closes_signal: pd.Series,
    fastk_period: int = 14,
    slowk_period: int = 3,
    slowd_period: int = 3,
    slowk_matype: int = 0,
    slowd_matype: int = 0,
) -> tuple[pd.Series, pd.Series]:
    slow_k, slow_d = talib.STOCH(
        highs_signal,
        lows_signal,
        closes_signal,
        fastk_period=fastk_period,
        slowk_period=slowk_period,
        slowd_period=slowd_period,
        slowk_matype=slowk_matype,
        slowd_matype=slowd_matype,
    )
    return slow_k, slow_d


def commodity_channel_index(
    highs_signal: pd.Series,
    lows_signal: pd.Series,
    closes_signal: pd.Series,
    timeperiod: int = 20,
) -> pd.Series:
    return talib.CCI(
        highs_signal, lows_signal, closes_signal, timeperiod=timeperiod
    )


def rate_of_change(original_signal: pd.Series, timeperiod: int = 10) -> pd.Series:
    """Percent change vs. `timeperiod` bars ago: (price / price[-n] - 1) * 100."""
    return talib.ROC(original_signal, timeperiod=timeperiod)


def williams_r(
    highs_signal: pd.Series,
    lows_signal: pd.Series,
    closes_signal: pd.Series,
    timeperiod: int = 14,
) -> pd.Series:
    """Like the stochastic oscillator's %K but inverted/unscaled: ranges
    -100 (at the period low) to 0 (at the period high)."""
    return talib.WILLR(
        highs_signal, lows_signal, closes_signal, timeperiod=timeperiod
    )

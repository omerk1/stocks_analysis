import pandas as pd
import talib


def on_balance_volume(
    closes_signal: pd.Series,
    volumes_signal: pd.Series,
) -> pd.Series:
    """Cumulative volume, added on up-closes and subtracted on down-closes."""
    return talib.OBV(closes_signal, volumes_signal)


def money_flow_index(
    highs_signal: pd.Series,
    lows_signal: pd.Series,
    closes_signal: pd.Series,
    volumes_signal: pd.Series,
    timeperiod: int = 14,
) -> pd.Series:
    """Volume-weighted RSI: 0-100, conventionally overbought/oversold at 80/20."""
    return talib.MFI(
        highs_signal, lows_signal, closes_signal, volumes_signal, timeperiod=timeperiod
    )

import pandas as pd
import talib


class TrendIndicators:
    @staticmethod
    def average_directional_index(
        highs_signal: pd.Series,
        lows_signal: pd.Series,
        closes_signal: pd.Series,
        timeperiod: int = 20,
    ) -> pd.Series:
        return talib.ADX(
            highs_signal, lows_signal, closes_signal, timeperiod=timeperiod
        )

    @staticmethod
    def average_true_range(
        highs_signal: pd.Series,
        lows_signal: pd.Series,
        closes_signal: pd.Series,
        timeperiod: int = 20,
    ) -> pd.Series:
        return talib.ATR(
            highs_signal, lows_signal, closes_signal, timeperiod=timeperiod
        )

    @staticmethod
    def stop_and_reverse(
        highs_signal: pd.Series,
        lows_signal: pd.Series,
        acceleration: int = 0.02,
        maximum: int = 0.2,
    ) -> pd.Series:
        return talib.SAR(
            highs_signal, lows_signal, acceleration=acceleration, maximum=maximum
        )

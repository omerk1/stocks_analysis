import pandas as pd
import talib


class MomentumIndicators:
    @staticmethod
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

    @staticmethod
    def commodity_channel_index(
        highs_signal: pd.Series,
        lows_signal: pd.Series,
        closes_signal: pd.Series,
        timeperiod: int = 20,
    ) -> pd.Series:
        return talib.CCI(
            highs_signal, lows_signal, closes_signal, timeperiod=timeperiod
        )

import pandas as pd
import talib


class PriceBasedIndicators:
    @staticmethod
    def moving_average(original_signal: pd.Series, window: int) -> pd.Series:
        return original_signal.rolling(window=window).mean()

    @staticmethod
    def exponential_moving_average(
        original_signal: pd.Series, window: int
    ) -> pd.Series:
        return talib.EMA(original_signal, timeperiod=window)

    @staticmethod
    def relative_strength_index(
        original_signal: pd.Series, window: int = 14
    ) -> pd.Series:
        return talib.RSI(original_signal, timeperiod=window)

    @staticmethod
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

    @staticmethod
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

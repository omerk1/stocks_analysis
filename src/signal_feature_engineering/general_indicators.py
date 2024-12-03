import pandas as pd


class GeneralIndicators:
    @staticmethod
    def high_open_ratio(
        highs_signal: pd.Series,
        open_signals: pd.Series,
    ) -> pd.Series:
        return highs_signal / open_signals

    @staticmethod
    def low_open_ratio(
        lows_signal: pd.Series,
        open_signals: pd.Series,
    ) -> pd.Series:
        return lows_signal / open_signals

    @staticmethod
    def close_open_ratio(
        closes_signal: pd.Series,
        open_signals: pd.Series,
    ) -> pd.Series:
        return closes_signal / open_signals

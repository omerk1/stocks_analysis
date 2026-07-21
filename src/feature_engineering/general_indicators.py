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

    @staticmethod
    def overnight_gap(
        open_signals: pd.Series,
        closes_signal: pd.Series,
    ) -> pd.Series:
        """Today's open vs. the *prior* bar's close -- the overnight gap.
        First value is NaN (no prior close to compare against)."""
        return open_signals / closes_signal.shift(1) - 1

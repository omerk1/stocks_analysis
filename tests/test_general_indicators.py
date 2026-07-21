import pandas as pd

from src.feature_engineering.general_indicators import GeneralIndicators


def test_close_open_ratio():
    closes = pd.Series([110.0, 90.0])
    opens = pd.Series([100.0, 100.0])

    result = GeneralIndicators.close_open_ratio(closes, opens)

    assert result.tolist() == [1.1, 0.9]

import pandas as pd
import pytest

from src.foundation.feature_engineering import general_indicators


def test_close_open_ratio():
    closes = pd.Series([110.0, 90.0])
    opens = pd.Series([100.0, 100.0])

    result = general_indicators.close_open_ratio(closes, opens)

    assert result.tolist() == [1.1, 0.9]


def test_overnight_gap_first_value_is_nan():
    opens = pd.Series([100.0, 102.0, 105.0])
    closes = pd.Series([101.0, 103.0, 104.0])

    result = general_indicators.overnight_gap(opens, closes)

    assert pd.isna(result.iloc[0])


def test_overnight_gap_compares_to_prior_close():
    opens = pd.Series([100.0, 102.0, 105.0])
    closes = pd.Series([101.0, 103.0, 104.0])

    result = general_indicators.overnight_gap(opens, closes)

    assert result.iloc[1] == pytest.approx(102.0 / 101.0 - 1)
    assert result.iloc[2] == pytest.approx(105.0 / 103.0 - 1)

import numpy as np
import pandas as pd
import pytest

from src.foundation.feature_engineering import price_based_indicators


def test_bollinger_bands_upper_and_lower_straddle_middle():
    closes = pd.Series(np.random.default_rng(0).uniform(90, 110, 40))

    upper_bb, middle_bb, lower_bb = price_based_indicators.bollinger_bands(
        closes, timeperiod=20
    )

    valid = pd.DataFrame(
        {"upper": upper_bb, "middle": middle_bb, "lower": lower_bb}
    ).dropna()
    assert (valid["upper"] >= valid["middle"]).all()
    assert (valid["middle"] >= valid["lower"]).all()


def test_bollinger_band_width_matches_formula():
    upper_bb = pd.Series([110.0, 120.0, np.nan])
    lower_bb = pd.Series([90.0, 80.0, np.nan])
    middle_bb = pd.Series([100.0, 100.0, np.nan])

    result = price_based_indicators.bollinger_band_width(
        upper_bb, lower_bb, middle_bb
    )

    assert result.iloc[0] == pytest.approx(20.0)
    assert result.iloc[1] == pytest.approx(40.0)
    assert pd.isna(result.iloc[2])


def test_bollinger_band_width_widens_with_volatility():
    tight_upper = pd.Series([101.0])
    tight_lower = pd.Series([99.0])
    tight_middle = pd.Series([100.0])
    wide_upper = pd.Series([115.0])
    wide_lower = pd.Series([85.0])
    wide_middle = pd.Series([100.0])

    tight_width = price_based_indicators.bollinger_band_width(
        tight_upper, tight_lower, tight_middle
    )
    wide_width = price_based_indicators.bollinger_band_width(
        wide_upper, wide_lower, wide_middle
    )

    assert wide_width.iloc[0] > tight_width.iloc[0]


def test_bollinger_band_width_atr_matches_formula():
    upper_bb = pd.Series([110.0, 120.0])
    lower_bb = pd.Series([90.0, 80.0])
    atr = pd.Series([4.0, 5.0])

    result = price_based_indicators.bollinger_band_width_atr(upper_bb, lower_bb, atr)

    assert result.iloc[0] == pytest.approx(5.0)
    assert result.iloc[1] == pytest.approx(8.0)

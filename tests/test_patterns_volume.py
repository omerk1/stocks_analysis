import pandas as pd
import pytest

from src.patterns.volume import is_breakout_volume_confirmed, rel_volume, volume_sma


def test_rel_volume_normal_case():
    assert rel_volume(150.0, 100.0) == pytest.approx(1.5)


def test_rel_volume_none_when_sma_unavailable():
    assert rel_volume(150.0, float("nan")) is None
    assert rel_volume(150.0, 0.0) is None


def test_volume_sma_matches_rolling_mean():
    series = pd.Series([100.0, 200.0, 300.0, 400.0])
    sma = volume_sma(series, 2)
    assert sma.iloc[1] == pytest.approx(150.0)
    assert sma.iloc[3] == pytest.approx(350.0)


def test_is_breakout_volume_confirmed_threshold():
    assert is_breakout_volume_confirmed(140.0, 100.0, breakout_volume_mult=1.4)
    assert not is_breakout_volume_confirmed(130.0, 100.0, breakout_volume_mult=1.4)

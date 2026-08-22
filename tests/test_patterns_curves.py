import numpy as np
import pytest

from src.patterns.curves import fit_roundedness


def test_fit_roundedness_perfect_parabola_is_one():
    x = np.arange(21, dtype=float)
    prices = (x - 10) ** 2
    assert fit_roundedness(prices) == pytest.approx(1.0)


def test_fit_roundedness_direction_agnostic_inverted_parabola_is_also_one():
    x = np.arange(21, dtype=float)
    prices = -((x - 10) ** 2)
    assert fit_roundedness(prices) == pytest.approx(1.0)


def test_fit_roundedness_sharp_v_shape_scores_below_a_real_parabola():
    x = np.arange(21, dtype=float)
    prices = np.abs(x - 10) * 10
    assert fit_roundedness(prices) < 0.95


def test_fit_roundedness_constant_prices_is_one():
    # ss_tot == 0 -- trivially a perfect "fit", same convention as
    # trendlines.r_squared.
    assert fit_roundedness(np.full(10, 50.0)) == 1.0

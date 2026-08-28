import numpy as np
import pytest

from src.patterns.curves import fit_quadratic, fit_roundedness, max_single_bar_move_frac


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


def test_fit_quadratic_curvature_sign_distinguishes_cup_from_inverse():
    # Upward-opening (a cup / rounding bottom) vs. downward-opening (their
    # inverses). R² scores both close to 1.0 -- the sign is the only thing
    # separating them, which is why the detector needs it.
    t = np.arange(21, dtype=float)
    assert fit_quadratic(0.1 * (t - 10) ** 2 + 100.0).curvature > 0
    assert fit_quadratic(-0.1 * (t - 10) ** 2 + 100.0).curvature < 0


def test_fit_quadratic_apex_position_is_centred_for_a_real_bowl():
    t = np.arange(21, dtype=float)
    assert fit_quadratic(0.1 * (t - 10) ** 2 + 100.0).apex_position == pytest.approx(0.5)


def test_fit_quadratic_apex_falls_outside_window_for_a_monotone_path():
    # The failure R2 alone cannot catch: a straight decline fits a parabola
    # *arm* with a high R2, but its vertex sits far outside the window.
    prices = np.linspace(100.0, 50.0, 30)
    fit = fit_quadratic(prices)
    assert fit.r2 > 0.99
    assert not (0.0 <= fit.apex_position <= 1.0)


def test_max_single_bar_move_frac_flags_a_one_bar_gap():
    # A cliff: one bar covers 90% of the whole path's range.
    prices = np.array([100.0, 100.0, 100.0, 10.0, 10.0, 10.0])
    assert max_single_bar_move_frac(prices) == pytest.approx(1.0)


def test_max_single_bar_move_frac_small_for_a_smooth_curve():
    t = np.arange(41, dtype=float)
    assert max_single_bar_move_frac(0.1 * (t - 20) ** 2 + 100.0) < 0.15


def test_max_single_bar_move_frac_flat_path_is_zero():
    assert max_single_bar_move_frac(np.full(10, 50.0)) == 0.0

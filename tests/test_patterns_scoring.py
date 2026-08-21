import pytest

from src.market_common.models import Direction
from src.patterns.config import PatternConfig
from src.patterns.scoring import (
    apex_proximity_score,
    breakout_close_strength,
    duration_fit,
    hs_price_symmetry,
    hs_time_symmetry,
    point_count_score,
    price_symmetry,
    prior_trend_strength,
    range_monotonicity_score,
    score_pattern,
    volume_signature_score,
)


def test_price_symmetry_identical_prices_scores_one():
    assert price_symmetry(100.0, 100.0) == pytest.approx(1.0)


def test_price_symmetry_decreases_with_divergence():
    close = price_symmetry(100.0, 105.0)
    far = price_symmetry(100.0, 150.0)
    assert 0.0 < far < close < 1.0


def test_breakout_close_strength_bullish_scales_with_atr_move():
    # 0.5 ATR beyond the level, cap at 1.0 ATR -> 0.5
    score = breakout_close_strength(
        breakout_close=101.0, level_price=100.0, atr=2.0, direction=Direction.BULLISH, cap_atr=1.0
    )
    assert score == pytest.approx(0.5)


def test_breakout_close_strength_bearish_direction_flips_sign():
    score = breakout_close_strength(
        breakout_close=99.0, level_price=100.0, atr=2.0, direction=Direction.BEARISH, cap_atr=1.0
    )
    assert score == pytest.approx(0.5)


def test_breakout_close_strength_none_atr_is_zero():
    assert breakout_close_strength(101.0, 100.0, None, Direction.BULLISH, 1.0) == 0.0


def test_duration_fit_within_range_is_one():
    assert duration_fit(formation_bars=30, typical_min_bars=20, typical_max_bars=60) == 1.0


def test_duration_fit_too_short_ramps_up_from_zero():
    score = duration_fit(formation_bars=10, typical_min_bars=20, typical_max_bars=60)
    assert score == pytest.approx(0.5)


def test_duration_fit_too_long_decays_but_floors_at_point_three():
    score = duration_fit(formation_bars=6000, typical_min_bars=20, typical_max_bars=60)
    assert score == 0.3


def test_prior_trend_strength_clips_at_cap():
    assert prior_trend_strength(pct_move=15.0, cap_pct=30.0) == pytest.approx(0.5)
    assert prior_trend_strength(pct_move=60.0, cap_pct=30.0) == 1.0


def test_volume_signature_score_no_expansion_is_zero():
    assert volume_signature_score(rel_vol=1.0, cap_mult=1.8) == 0.0
    assert volume_signature_score(rel_vol=None, cap_mult=1.8) == 0.0


def test_volume_signature_score_scales_to_cap():
    assert volume_signature_score(rel_vol=1.8, cap_mult=1.8) == pytest.approx(1.0)
    assert volume_signature_score(rel_vol=1.4, cap_mult=1.8) == pytest.approx(0.5)


def test_score_pattern_combines_weighted_components():
    config = PatternConfig()
    components = {
        "geometric_cleanliness": 1.0,
        "volume_signature": 1.0,
        "duration_fit": 1.0,
        "prior_trend": 1.0,
        "breakout_strength": 1.0,
    }
    confidence, notes = score_pattern(components, config)
    assert confidence == pytest.approx(1.0)
    assert len(notes) == 5


def test_score_pattern_zero_components_scores_zero():
    config = PatternConfig()
    components = {k: 0.0 for k in config.scoring_weights}
    confidence, _ = score_pattern(components, config)
    assert confidence == 0.0


def test_hs_price_symmetry_identical_shoulders_scores_one():
    assert hs_price_symmetry(100.0, 100.0, 140.0) == pytest.approx(1.0)


def test_hs_price_symmetry_normalized_by_head_not_avg():
    # |100-110|/140 = 0.0714 -- distinct from price_symmetry's avg(a,b)
    # normalization (|100-110|/105 = 0.0952).
    assert hs_price_symmetry(100.0, 110.0, 140.0) == pytest.approx(1 - 10 / 140)


def test_hs_time_symmetry_equal_halves_scores_one():
    assert hs_time_symmetry(bars_ls_to_head=10, bars_head_to_rs=10, bars_ls_to_rs=20) == pytest.approx(1.0)


def test_hs_time_symmetry_lopsided_halves_scores_below_one():
    score = hs_time_symmetry(bars_ls_to_head=5, bars_head_to_rs=15, bars_ls_to_rs=20)
    assert score == pytest.approx(0.5)


def test_point_count_score_caps_at_one():
    assert point_count_score(n_touches=2, min_required=2) == pytest.approx(1.0)
    assert point_count_score(n_touches=5, min_required=2) == pytest.approx(1.0)
    assert point_count_score(n_touches=1, min_required=2) == pytest.approx(0.5)


def test_range_monotonicity_score_all_shrinking_is_one():
    assert range_monotonicity_score([40.0, 25.0, 10.0, 3.0]) == pytest.approx(1.0)


def test_range_monotonicity_score_widening_leg_penalized():
    # 40->25 shrinks, 25->30 widens, 30->10 shrinks -- 2 of 3 pairs shrink.
    assert range_monotonicity_score([40.0, 25.0, 30.0, 10.0]) == pytest.approx(2 / 3)


def test_range_monotonicity_score_fewer_than_two_legs_is_vacuously_one():
    assert range_monotonicity_score([40.0]) == 1.0
    assert range_monotonicity_score([]) == 1.0


def test_apex_proximity_score_scales_with_progress_to_apex():
    # Window spans bar 10->30, apex at bar 50 -- 20/40 = 0.5 of the way there.
    assert apex_proximity_score(window_start_bar=10, window_end_bar=30, apex_bar=50) == pytest.approx(0.5)


def test_apex_proximity_score_near_apex_scores_high():
    assert apex_proximity_score(window_start_bar=10, window_end_bar=48, apex_bar=50) == pytest.approx(0.95)

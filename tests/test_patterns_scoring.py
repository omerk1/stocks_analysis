import pytest

from src.market_common.models import Direction
from src.patterns.config import PatternConfig
from src.patterns.scoring import (
    breakout_close_strength,
    duration_fit,
    price_symmetry,
    prior_trend_strength,
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

import pandas as pd

from src.sr_lines.config import SRConfig
from src.sr_lines.models import Event, EventType
from src.sr_lines.scoring import score_line


def _flat_bars(n_days: int, price: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    return pd.DataFrame(
        {"open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1_000_000},
        index=idx,
    )


def _atr(bars: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=bars.index)


def _touch(date: str, reaction: float = 2.0) -> Event:
    return Event(type=EventType.TOUCH, start=date, end=date, penetration_atr=0.1, reaction_atr=reaction)


def _break(date: str) -> Event:
    return Event(type=EventType.BREAK, start=date, end=date, penetration_atr=1.0, reaction_atr=0.0)


def test_broken_line_touch_quality_does_not_decay_further_once_dead():
    events = [
        _touch("2020-01-10"),
        _touch("2020-01-20"),
        _break("2020-02-01"),
    ]
    config = SRConfig(window_years=3.0)

    bars_soon_after = _flat_bars(60)  # "now" = ~2020-03-25, shortly after the break
    bars_much_later = _flat_bars(600)  # "now" = ~2022-04, ~2 years after the break

    score_soon = score_line(events, bars_soon_after, _atr(bars_soon_after), 100.0, config)
    score_later = score_line(events, bars_much_later, _atr(bars_much_later), 100.0, config)

    assert score_soon.touch_quality == score_later.touch_quality


def test_active_line_touch_quality_does_decay_as_now_moves_forward():
    events = [_touch("2020-01-10"), _touch("2020-01-20")]  # no break -- still ACTIVE
    config = SRConfig(window_years=3.0)

    bars_soon_after = _flat_bars(60)
    bars_much_later = _flat_bars(600)

    score_soon = score_line(events, bars_soon_after, _atr(bars_soon_after), 100.0, config)
    score_later = score_line(events, bars_much_later, _atr(bars_much_later), 100.0, config)

    assert score_later.touch_quality < score_soon.touch_quality


def test_flipped_line_touch_quality_still_decays_against_now_not_frozen_at_break():
    events = [
        _touch("2020-01-10"),
        _break("2020-02-01"),
        _touch("2020-02-15"),  # respects the new side after the break -> FLIPPED
    ]
    config = SRConfig(window_years=3.0)

    bars_soon_after = _flat_bars(60)
    bars_much_later = _flat_bars(600)

    score_soon = score_line(events, bars_soon_after, _atr(bars_soon_after), 100.0, config)
    score_later = score_line(events, bars_much_later, _atr(bars_much_later), 100.0, config)

    assert score_later.touch_quality < score_soon.touch_quality


def test_role_reversal_scales_with_confirming_evidence_not_binary():
    config = SRConfig(window_years=3.0)
    bars = _flat_bars(60)
    atr = _atr(bars)

    one_confirmation = [_break("2020-02-01"), _touch("2020-02-15")]
    three_confirmations = [
        _break("2020-02-01"),
        _touch("2020-02-15"),
        _touch("2020-02-20"),
        _touch("2020-02-25"),
    ]

    score_one = score_line(one_confirmation, bars, atr, 100.0, config)
    score_three = score_line(three_confirmations, bars, atr, 100.0, config)

    assert 0 < score_one.role_reversal < 1.0
    assert score_three.role_reversal == 1.0
    assert score_one.role_reversal < score_three.role_reversal


def test_flip_is_sticky_even_after_an_unconfirmed_later_break():
    # Broke, was confirmed flipped, then broke *again* with no further
    # reclaim -- lifecycle.py's state is FLIPPED either way (there's no
    # separate "flipped then re-broken" state), so decay must not freeze:
    # freezing here would silently contradict a FLIPPED line's own state.
    events = [
        _touch("2020-01-10"),
        _break("2020-02-01"),
        _touch("2020-02-15"),  # confirms the flip
        _break("2020-06-01"),  # breaks again, never reclaimed
    ]
    config = SRConfig(window_years=3.0)

    bars_soon_after = _flat_bars(60)
    bars_much_later = _flat_bars(600)

    score_soon = score_line(events, bars_soon_after, _atr(bars_soon_after), 100.0, config)
    score_later = score_line(events, bars_much_later, _atr(bars_much_later), 100.0, config)

    assert score_later.touch_quality < score_soon.touch_quality

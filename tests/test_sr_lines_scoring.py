import pandas as pd
import pytest

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


def _body_fake(start: str, end: str) -> Event:
    return Event(type=EventType.BODY_FAKE, start=start, end=end, penetration_atr=0.5, reaction_atr=0.0)


def test_resilience_body_fake_decays_with_time_under_but_keeps_a_grace_floor():
    bars = _flat_bars(60)
    atr = _atr(bars)
    config = SRConfig(window_years=3.0, fakeout_reclaim_bars=5)
    idx = bars.index

    quick_reclaim = [_body_fake(idx[10].isoformat(), idx[11].isoformat())]  # 1 bar under
    slow_reclaim = [_body_fake(idx[10].isoformat(), idx[15].isoformat())]  # 5 bars under (the full window)

    score_quick = score_line(quick_reclaim, bars, atr, 100.0, config)
    score_slow = score_line(slow_reclaim, bars, atr, 100.0, config)

    assert score_quick.resilience > score_slow.resilience
    # Grace floor: even the slowest qualifying reclaim keeps meaningful
    # credit rather than decaying to ~0 -- exactly 0.3 * 0.35 here (fully
    # floored, since 5 bars under is the whole fakeout_reclaim_bars window).
    assert score_slow.resilience == pytest.approx(0.3 * 0.35, abs=0.001)
    # 1 bar under (the fastest a real BODY_FAKE can be -- reclaim always
    # happens on a later bar than the break) is close to, not at, full
    # credit: fraction_of_window=1/5=0.2 -> decay=1-(0.7*0.2)=0.86.
    assert score_quick.resilience == pytest.approx(0.35 * 0.86, abs=0.01)


def test_resilience_wick_fake_unaffected_by_duration_decay():
    # Same-bar by construction (start == end) -- always full flat credit.
    bars = _flat_bars(60)
    atr = _atr(bars)
    config = SRConfig(window_years=3.0)
    idx = bars.index

    events = [Event(type=EventType.WICK_FAKE, start=idx[10].isoformat(), end=idx[10].isoformat(),
                     penetration_atr=0.5, reaction_atr=0.0)]

    score = score_line(events, bars, atr, 100.0, config)

    assert score.resilience == pytest.approx(0.15, abs=0.001)


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


def _strong_flipped_events(bars: pd.DataFrame) -> list[Event]:
    # Plenty of touches, resilience-earning fakes (incl. quick body-fakes),
    # and a confirmed flip -- strong on every component *except* relevance.
    # Built from actual bar positions (not hardcoded date strings) so it
    # works regardless of how many periods the caller's `bars` fixture has.
    idx = bars.index
    return [
        _touch(idx[1].isoformat()), _touch(idx[2].isoformat()),
        Event(type=EventType.WICK_FAKE, start=idx[3].isoformat(), end=idx[3].isoformat(),
              penetration_atr=0.5, reaction_atr=0.0),
        Event(type=EventType.BODY_FAKE, start=idx[4].isoformat(), end=idx[5].isoformat(),
              penetration_atr=0.5, reaction_atr=0.0),
        Event(type=EventType.BODY_FAKE, start=idx[6].isoformat(), end=idx[7].isoformat(),
              penetration_atr=0.5, reaction_atr=0.0),
        _break(idx[8].isoformat()),
        _touch(idx[9].isoformat()), _touch(idx[10].isoformat()), _touch(idx[11].isoformat()),
    ]


def test_old_and_far_level_is_gated_down_despite_strong_historical_evidence():
    # Real AAPL finding this reproduces: a level with strong resilience/
    # role_reversal still scored 0.369 overall despite proximity=0.125,
    # because no single additive weight could suppress a level strong
    # everywhere else.
    config = SRConfig(window_years=3.0)
    bars_far_away = _flat_bars(600, price=300.0)  # candidate_center=100, price now 300 -- 3x away
    events = _strong_flipped_events(bars_far_away)

    score = score_line(events, bars_far_away, _atr(bars_far_away), 100.0, config)

    assert score.resilience > 0.5
    assert score.role_reversal == 1.0
    assert score.relevance_gate < 0.05
    assert score.total < 0.05  # gated down hard despite strong inner components


def test_recent_and_nearby_level_with_same_evidence_stays_highly_relevant():
    config = SRConfig(window_years=3.0)
    bars_nearby_recent = _flat_bars(20, price=100.5)  # "now" shortly after the events, price barely moved
    events = _strong_flipped_events(bars_nearby_recent)

    score = score_line(events, bars_nearby_recent, _atr(bars_nearby_recent), 100.0, config)

    assert score.relevance_gate > 0.85
    assert score.total > 0.3


def test_relevance_gate_is_the_product_of_proximity_and_recency():
    events = [_touch("2020-01-10")]
    config = SRConfig(window_years=3.0)
    bars = _flat_bars(600, price=150.0)

    score = score_line(events, bars, _atr(bars), 100.0, config)

    # proximity is independently reported; the gate must be proximity times
    # a (separately unreported) recency factor, so it can't exceed proximity.
    assert score.relevance_gate <= score.proximity


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

import pandas as pd
import pytest

from src.sr_lines.config import SRConfig
from src.sr_lines.models import Event, EventType
from src.sr_lines.scoring import regime_start, score_line


def _flat_bars(n_days: int, price: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    return pd.DataFrame(
        {"open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1_000_000},
        index=idx,
    )


def _atr(bars: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=bars.index)


def _touch(date: str, reaction: float = 2.0, volume: float | None = None) -> Event:
    return Event(type=EventType.TOUCH, start=date, end=date, penetration_atr=0.1, reaction_atr=reaction,
                 volume_ratio=volume)


def _break(date: str) -> Event:
    return Event(type=EventType.BREAK, start=date, end=date, penetration_atr=1.0, reaction_atr=0.0)


def _body_fake(start: str, end: str, volume: float | None = None) -> Event:
    return Event(type=EventType.BODY_FAKE, start=start, end=end, penetration_atr=0.5, reaction_atr=0.0,
                 volume_ratio=volume)


def test_resilience_body_fake_decays_with_time_under_but_keeps_a_grace_floor():
    bars = _flat_bars(60)
    atr = _atr(bars)
    config = SRConfig(window_years=3.0, fakeout_reclaim_bars=5)
    idx = bars.index

    # Placed near the end of the window (not idx[10]) so time-recency decay
    # is negligible for both -- isolates the reclaim-speed decay this test
    # is actually about, separate from test_resilience_decays_with_recency's
    # time dimension.
    quick_reclaim = [_body_fake(idx[-3].isoformat(), idx[-2].isoformat())]  # 1 bar under
    slow_reclaim = [_body_fake(idx[-7].isoformat(), idx[-2].isoformat())]  # 5 bars under (the full window)

    score_quick = score_line(quick_reclaim, bars, atr, 100.0, config)
    score_slow = score_line(slow_reclaim, bars, atr, 100.0, config)

    half_life_days = config.resolved_half_life_years() * 365.25
    recency_decay = 0.5 ** ((idx[-1] - idx[-2]).days / half_life_days)

    assert score_quick.resilience > score_slow.resilience
    # Grace floor: even the slowest qualifying reclaim keeps meaningful
    # credit rather than decaying to ~0 -- 0.3 * 0.35 here (fully floored,
    # since 5 bars under is the whole fakeout_reclaim_bars window), times
    # the small recency decay from ending 1 bar before "now".
    assert score_slow.resilience == pytest.approx(0.3 * 0.35 * recency_decay, abs=0.001)
    # 1 bar under (the fastest a real BODY_FAKE can be -- reclaim always
    # happens on a later bar than the break) is close to, not at, full
    # credit: fraction_of_window=1/5=0.2 -> decay=1-(0.7*0.2)=0.86.
    assert score_quick.resilience == pytest.approx(0.35 * 0.86 * recency_decay, abs=0.01)


def test_resilience_wick_fake_unaffected_by_duration_decay():
    # Same-bar by construction (start == end) -- always full flat credit.
    # Placed at the very last bar (= "now") so recency decay is exactly 1.0,
    # isolating this from the separate time-decay dimension (see
    # test_resilience_decays_with_recency).
    bars = _flat_bars(60)
    atr = _atr(bars)
    config = SRConfig(window_years=3.0)
    idx = bars.index

    events = [Event(type=EventType.WICK_FAKE, start=idx[-1].isoformat(), end=idx[-1].isoformat(),
                     penetration_atr=0.5, reaction_atr=0.0)]

    score = score_line(events, bars, atr, 100.0, config)

    assert score.resilience == pytest.approx(0.15, abs=0.001)


def test_resilience_decays_with_recency():
    # New: resilience previously had no time decay at all, unlike
    # touch_quality/role_reversal -- an old defended level stayed worth
    # exactly as much as a fresh one, and could saturate its 1.0 cap purely
    # from long accumulated history regardless of relevance. Same
    # exponential half-life decay as everywhere else, now applied here too.
    config = SRConfig(window_years=3.0)
    bars_soon_after = _flat_bars(60)
    bars_much_later = _flat_bars(600)
    idx_soon, idx_later = bars_soon_after.index, bars_much_later.index

    events_soon = [Event(type=EventType.WICK_FAKE, start=idx_soon[10].isoformat(), end=idx_soon[10].isoformat(),
                          penetration_atr=0.5, reaction_atr=0.0)]
    events_later = [Event(type=EventType.WICK_FAKE, start=idx_later[10].isoformat(), end=idx_later[10].isoformat(),
                           penetration_atr=0.5, reaction_atr=0.0)]

    score_soon = score_line(events_soon, bars_soon_after, _atr(bars_soon_after), 100.0, config)
    score_later = score_line(events_later, bars_much_later, _atr(bars_much_later), 100.0, config)

    assert score_soon.resilience > score_later.resilience
    assert score_later.resilience > 0.0  # never fully zeroed -- it's still real evidence


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
    # Post-break touches use a strong (cap-hitting) reaction so role_reversal
    # (now quality-weighted, not just counted) actually reaches near-full
    # credit when recent -- see test_role_reversal_scales_with_confirming_evidence_not_binary
    # for why a weak reaction wouldn't demonstrate "strong evidence" anymore.
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
        _touch(idx[9].isoformat(), reaction=5.0),
        _touch(idx[10].isoformat(), reaction=5.0),
        _touch(idx[11].isoformat(), reaction=5.0),
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

    # resilience is now recency-decayed too (same fix as role_reversal
    # below) -- events from ~2 years before "now" are real, but stale, not
    # the old flat "counts forever regardless of age" credit.
    assert 0 < score.resilience < 0.5
    # role_reversal is now quality-weighted (reaction x recency decay), same
    # lens as touch_quality -- confirmations from ~2 years before "now" (bar
    # 600 of a 600-bar window) are strong but stale, so this no longer hits
    # the old flat 1.0 the count-based formula gave regardless of age.
    assert 0 < score.role_reversal < 0.5
    assert score.relevance_gate < 0.05
    assert score.total < 0.05  # gated down hard despite strong inner components


def test_recent_and_nearby_level_with_same_evidence_stays_highly_relevant():
    config = SRConfig(window_years=3.0)
    bars_nearby_recent = _flat_bars(20, price=100.5)  # "now" shortly after the events, price barely moved
    events = _strong_flipped_events(bars_nearby_recent)

    score = score_line(events, bars_nearby_recent, _atr(bars_nearby_recent), 100.0, config)

    assert score.role_reversal > 0.85  # strong, recent confirmations -> near-full credit
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
    idx = bars.index
    now = idx[-1].isoformat()

    # Strong (cap-hitting), essentially-undecayed confirmations right at
    # "now" so this isolates count-scaling from the (separately-tested)
    # quality-weighting below.
    one_confirmation = [_break(idx[0].isoformat()), _touch(now, reaction=5.0)]
    three_confirmations = [
        _break(idx[0].isoformat()),
        _touch(idx[-3].isoformat(), reaction=5.0),
        _touch(idx[-2].isoformat(), reaction=5.0),
        _touch(now, reaction=5.0),
    ]

    score_one = score_line(one_confirmation, bars, atr, 100.0, config)
    score_three = score_line(three_confirmations, bars, atr, 100.0, config)

    assert 0 < score_one.role_reversal < 1.0
    assert score_three.role_reversal == pytest.approx(1.0, abs=0.02)
    assert score_one.role_reversal < score_three.role_reversal


def test_role_reversal_is_quality_weighted_not_just_counted():
    # Regression for the AAPL finding that survived the binary-to-proportional
    # fix: 3 confirmations *by raw count* used to always mean role_reversal=1.0
    # regardless of how weak or stale they were, letting a barely-confirmed
    # flip outscore a never-broken line with real touch-quality evidence. Same
    # count (3), same recency (all at "now"), only reaction strength differs.
    config = SRConfig(window_years=3.0)
    bars = _flat_bars(60)
    atr = _atr(bars)
    idx = bars.index
    now = idx[-1].isoformat()

    weak_confirmations = [
        _break(idx[0].isoformat()),
        _touch(idx[-3].isoformat(), reaction=0.1),
        _touch(idx[-2].isoformat(), reaction=0.1),
        _touch(now, reaction=0.1),
    ]
    strong_confirmations = [
        _break(idx[0].isoformat()),
        _touch(idx[-3].isoformat(), reaction=5.0),
        _touch(idx[-2].isoformat(), reaction=5.0),
        _touch(now, reaction=5.0),
    ]

    score_weak = score_line(weak_confirmations, bars, atr, 100.0, config)
    score_strong = score_line(strong_confirmations, bars, atr, 100.0, config)

    assert score_weak.role_reversal < 0.1
    assert score_strong.role_reversal == pytest.approx(1.0, abs=0.02)


def test_role_reversal_counts_a_resolved_body_fake_as_confirmation_but_not_a_pending_one():
    config = SRConfig(window_years=3.0)
    bars = _flat_bars(60)
    atr = _atr(bars)

    resolved = [_break("2020-02-01"), _body_fake("2020-02-10", "2020-02-12")]
    pending_only = [
        _break("2020-02-01"),
        Event(type=EventType.BODY_FAKE, start="2020-02-10", end="2020-02-12",
              penetration_atr=0.4, reaction_atr=0.0, pending=True),
    ]

    score_resolved = score_line(resolved, bars, atr, 100.0, config)
    score_pending = score_line(pending_only, bars, atr, 100.0, config)

    assert score_resolved.role_reversal > 0
    assert score_pending.role_reversal == 0


def test_diagonal_fit_penalty_is_capped_and_reduces_total():
    events = [_touch("2020-01-10", reaction=5.0), _touch("2020-01-20", reaction=5.0)]
    config = SRConfig(window_years=3.0)
    bars = _flat_bars(30)
    atr = _atr(bars)

    score_tight_fit = score_line(events, bars, atr, 100.0, config, diagonal=True, diagonal_fit_penalty=0.0)
    score_loose_fit = score_line(events, bars, atr, 100.0, config, diagonal=True, diagonal_fit_penalty=0.15)
    score_at_cap = score_line(events, bars, atr, 100.0, config, diagonal=True, diagonal_fit_penalty=0.3)
    # Far beyond the cap -- should clamp to the same penalty a fit right at
    # the cap would get, not keep dragging the score down further.
    score_way_over_cap = score_line(events, bars, atr, 100.0, config, diagonal=True, diagonal_fit_penalty=10.0)

    assert score_tight_fit.diagonal_penalty == 0.0
    assert score_loose_fit.diagonal_penalty == pytest.approx(0.15)
    assert score_way_over_cap.diagonal_penalty == pytest.approx(0.3)  # _DIAGONAL_PENALTY_CAP
    assert score_loose_fit.total < score_tight_fit.total
    assert score_way_over_cap.total == pytest.approx(score_at_cap.total)


def test_diagonal_duration_density_uses_a_fixed_reference_not_the_full_window():
    # Regression: a real PAAS run showed a genuinely strong, recent ~1-year
    # trendline (touch_quality 0.37, resilience 1.0, role_reversal 1.0 --
    # strong on every other axis) crushed to duration_density=0.089 purely
    # for not spanning the full 8-year long_term window, while multi-year
    # lines got this component almost for free just by being long. A
    # diagonal trendline that's held for ~1 year is already "mature" and
    # shouldn't be judged against the detection window's length the way a
    # horizontal level's multi-year persistence legitimately is.
    bars = _flat_bars(400, price=100.0)
    atr = _atr(bars)
    idx = bars.index
    events = [_touch(idx[0].isoformat()), _touch(idx[260].isoformat())]  # ~1 year apart
    config = SRConfig(window_years=8.0)  # long_term preset scale

    score_horizontal = score_line(events, bars, atr, 100.0, config, diagonal=False)
    score_diagonal = score_line(events, bars, atr, 100.0, config, diagonal=True)

    assert score_diagonal.duration_density > score_horizontal.duration_density
    assert score_diagonal.duration_density == pytest.approx(1.0, abs=0.05)
    assert score_horizontal.duration_density < 0.15  # ~1 year / 8 years, roughly what PAAS showed


def test_in_play_gate_suppresses_a_line_that_mostly_hovers_away_from_price():
    # Regression: a real AAPL run showed every line in a top-15 with
    # touch_quality/resilience/role_reversal all saturated at/near 1.0 (a
    # long-history line easily accumulates enough break/reclaim cycles to
    # hit those caps over many years) -- duration_density's old
    # ~0.20-of-0.90 additive weight couldn't meaningfully suppress a line
    # that spent most of its life extrapolating through empty space while
    # real price action happened elsewhere entirely ("hovering"). Construct
    # exactly that: identical events (so touch_quality/relevance_gate are
    # identical either way), but price sits far from the line for most of
    # the events' own span in one case and stays near it throughout in the
    # other -- only in_play_gate should differ, and it alone should
    # meaningfully suppress the total.
    n = 120
    idx = pd.bdate_range("2020-01-01", periods=n)
    near, far = 100.0, 300.0
    prices = [near if i < 10 or i >= n - 10 else far for i in range(n)]
    bars_hovering = pd.DataFrame(
        {"open": prices, "high": [p + 1 for p in prices], "low": [p - 1 for p in prices],
         "close": prices, "volume": 1_000_000},
        index=idx,
    )
    bars_tracking = _flat_bars(n, price=near)  # control: price stays near the line throughout
    config = SRConfig(window_years=3.0)

    events = [
        _touch(idx[1].isoformat(), reaction=5.0),
        _touch(idx[2].isoformat(), reaction=5.0),
        _break(idx[5].isoformat()),
        _touch(idx[n - 10].isoformat(), reaction=5.0),
        _touch(idx[n - 9].isoformat(), reaction=5.0),
        _touch(idx[n - 8].isoformat(), reaction=5.0),
    ]

    score_hovering = score_line(events, bars_hovering, _atr(bars_hovering), near, config)
    score_tracking = score_line(events, bars_tracking, _atr(bars_tracking), near, config)

    assert score_hovering.in_play_gate < 0.3
    assert score_tracking.in_play_gate > 0.9
    assert score_hovering.touch_quality == pytest.approx(score_tracking.touch_quality)
    assert score_hovering.relevance_gate == pytest.approx(score_tracking.relevance_gate)
    assert score_hovering.total < score_tracking.total * 0.5


def test_in_play_gate_judges_only_the_current_regime_not_a_years_old_dormant_gap():
    # Regression: a real PAAS trendline had a genuine ~3-year dormant gap
    # (price simply traded far away for years) before a real, decisive
    # breakout reactivated it -- a tightly-fit (fit_rms=0.07), genuinely real
    # trendline, not a coincidental fit. The old flat in_play_gate (fraction
    # of *all* time between first and last event) couldn't tell this apart
    # from the hovering case above: both look like "price was rarely near
    # this line" to a flat average, even though one is spurious and the
    # other is a real level with an ordinary multi-year quiet period.
    # Verified score before this fix: 0.032 (buried, wouldn't crack top-15).
    # After: 0.177 (top-ranked). Same event shape as the hovering test above
    # (touches/break near the start, touches at the end), but stretched over
    # >2 years so the gap exceeds `regime_gap_years` -- this is the
    # discriminating case the hovering test's ~0.4yr gap can't exercise.
    n = 700
    idx = pd.bdate_range("2020-01-01", periods=n)
    near, far = 100.0, 300.0
    prices = [near if i < 10 or i >= n - 10 else far for i in range(n)]
    bars = pd.DataFrame(
        {"open": prices, "high": [p + 1 for p in prices], "low": [p - 1 for p in prices],
         "close": prices, "volume": 1_000_000},
        index=idx,
    )
    config = SRConfig(window_years=3.0, regime_gap_years=1.0)

    events = [
        _touch(idx[1].isoformat(), reaction=5.0),
        _touch(idx[2].isoformat(), reaction=5.0),
        _break(idx[5].isoformat()),
        _touch(idx[n - 10].isoformat(), reaction=5.0),
        _touch(idx[n - 9].isoformat(), reaction=5.0),
        _touch(idx[n - 8].isoformat(), reaction=5.0),
    ]

    score = score_line(events, bars, _atr(bars), near, config)

    # Judged from the current regime (the final cluster) onward, price is
    # right at the line throughout -- high in_play_gate -- even though a
    # flat average over the *entire* first-to-last-event span would read as
    # mostly-hovering, the same shape the hovering test above suppresses.
    assert score.in_play_gate > 0.8


def test_regime_start_resets_after_a_gap_but_not_within_normal_quiet_periods():
    idx = pd.bdate_range("2020-01-01", periods=1500)

    # No gap larger than the threshold anywhere -- current regime is the
    # whole history, same as the old always-first-event behavior.
    continuous = [_touch(idx[i].isoformat()) for i in (0, 200, 400, 600, 800)]
    assert regime_start(continuous, gap_years=1.0) == pd.Timestamp(idx[0])

    # A single gap of ~3 years (roughly 750 business days) between the
    # second and third events -- everything before it is an earlier regime.
    dormant = [_touch(idx[i].isoformat()) for i in (0, 50, 1300, 1350, 1400)]
    assert regime_start(dormant, gap_years=1.0) == pd.Timestamp(idx[1300])


def test_touch_quality_rewards_high_volume_over_low_volume_at_equal_count_and_reaction():
    # "A level touched 4 times with high volume should be weighted much
    # higher than a peak touched once on low volume" -- same count, same
    # reaction strength, only volume differs.
    config = SRConfig(window_years=3.0)
    bars = _flat_bars(30)
    atr = _atr(bars)

    high_volume = [_touch("2020-01-10", reaction=2.0, volume=2.0), _touch("2020-01-20", reaction=2.0, volume=2.0)]
    low_volume = [_touch("2020-01-10", reaction=2.0, volume=0.2), _touch("2020-01-20", reaction=2.0, volume=0.2)]
    no_volume_data = [_touch("2020-01-10", reaction=2.0), _touch("2020-01-20", reaction=2.0)]

    score_high = score_line(high_volume, bars, atr, 100.0, config)
    score_low = score_line(low_volume, bars, atr, 100.0, config)
    score_none = score_line(no_volume_data, bars, atr, 100.0, config)

    assert score_high.touch_quality > score_low.touch_quality
    # Missing volume data is neutral, not penalized -- sits between the two.
    assert score_low.touch_quality < score_none.touch_quality < score_high.touch_quality


def test_resilience_rewards_high_volume_reclaims():
    config = SRConfig(window_years=3.0, fakeout_reclaim_bars=5)
    bars = _flat_bars(30)
    atr = _atr(bars)
    idx = bars.index

    high_volume = [_body_fake(idx[10].isoformat(), idx[11].isoformat(), volume=2.0)]
    low_volume = [_body_fake(idx[10].isoformat(), idx[11].isoformat(), volume=0.2)]

    score_high = score_line(high_volume, bars, atr, 100.0, config)
    score_low = score_line(low_volume, bars, atr, 100.0, config)

    assert score_high.resilience > score_low.resilience


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

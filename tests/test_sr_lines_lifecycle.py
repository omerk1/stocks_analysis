import math

import pandas as pd
import pytest

from src.sr_lines.candidates import DiagonalCandidate, HorizontalCandidate
from src.sr_lines.config import SRConfig
from src.sr_lines.lifecycle import build_line, dedup_lines, select_lines
from src.sr_lines.models import (
    Event,
    EventType,
    Line,
    LineKind,
    LineRole,
    LineState,
    Pivot,
    PivotKind,
    ScoreBreakdown,
    TouchCounts,
)


def _flat_bars(n_days: int = 60, price: float = 100.0) -> pd.DataFrame:
    # Calendar days, not business days -- several tests below hand-write
    # literal date strings and rely on flip_status.pair_break_reclaims'
    # bars_between (a bars.index.get_loc lookup) succeeding for a break's
    # confirming event. A real pipeline only ever produces event dates from
    # actual bars.index entries (see events.py), so this never bites in
    # production; it's purely a synthetic-fixture concern here.
    idx = pd.date_range("2020-01-01", periods=n_days, freq="D")
    return pd.DataFrame(
        {"open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1_000_000},
        index=idx,
    )


def _atr(bars: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=bars.index)


def _line(
    line_id: str, strength: float, center: float = 100.0, half_width: float = 1.0,
    state: LineState = LineState.ACTIVE, events: list[Event] | None = None,
) -> Line:
    events = events or []
    return Line(
        id=line_id,
        kind=LineKind.HORIZONTAL,
        role=LineRole.SUPPORT,
        state=state,
        center=center,
        half_width=half_width,
        slope=None,
        intercept=None,
        origin_index=None,
        first_touch="2020-01-01",
        last_event="2020-01-01",
        events=events,
        scores=ScoreBreakdown(total=strength),
        strength=strength,
        touch_counts=TouchCounts(breaks=sum(1 for e in events if e.type == EventType.BREAK)),
    )


def _touch(date: str, side: str | None = None) -> Event:
    return Event(type=EventType.TOUCH, start=date, end=date, penetration_atr=0.1, reaction_atr=1.0, side=side)


def _break(date: str, side: str | None = None) -> Event:
    return Event(type=EventType.BREAK, start=date, end=date, penetration_atr=1.0, reaction_atr=0.0, side=side)


def test_select_lines_defaults_to_fixed_top_n():
    lines = [_line(f"h{i}", strength) for i, strength in enumerate([0.9, 0.1, 0.5, 0.7, 0.3, 0.2])]
    config = SRConfig(top_n=3)

    selected = select_lines(lines, config)

    assert [line.id for line in selected] == ["h0", "h3", "h2"]


def test_select_lines_strength_floor_returns_everything_above_it_not_a_fixed_count():
    lines = [_line(f"h{i}", strength) for i, strength in enumerate([0.9, 0.1, 0.5, 0.7, 0.3, 0.2])]
    config = SRConfig(top_n=3)  # should be ignored when a floor is given

    selected = select_lines(lines, config, strength_floor=0.3)

    assert {line.id for line in selected} == {"h0", "h3", "h2", "h4"}


def test_dedup_merges_close_but_non_overlapping_zones():
    # Two zones each width=1.0 (half_width=0.5), centers 100 and 100.7 -> a
    # 0.2-wide gap between them, well under the default 0.6*avg_width=0.6
    # threshold. A real T (AT&T) run showed candidates.py producing several
    # zones exactly like this -- close enough to read as one area on a
    # chart, but not literally overlapping, so the old overlap-only check
    # let every one of them survive as visual clutter.
    strong = _line("strong", strength=0.8, center=100.0, half_width=0.5)
    weak_close = _line("weak_close", strength=0.3, center=100.7, half_width=0.5)
    far_away = _line("far_away", strength=0.5, center=110.0, half_width=0.5)
    config = SRConfig(dedup_overlap_threshold=0.6)
    bars = _flat_bars()

    deduped = dedup_lines([strong, weak_close, far_away], bars, _atr(bars), config)

    assert {line.id for line in deduped} == {"strong", "far_away"}


def test_dedup_does_not_merge_zones_separated_by_a_large_gap():
    a = _line("a", strength=0.8, center=100.0, half_width=0.5)
    b = _line("b", strength=0.5, center=105.0, half_width=0.5)  # 4.0 gap, way over threshold
    config = SRConfig(dedup_overlap_threshold=0.6)
    bars = _flat_bars()

    deduped = dedup_lines([a, b], bars, _atr(bars), config)

    assert {line.id for line in deduped} == {"a", "b"}


def test_dedup_rescores_the_survivor_from_the_merged_event_union():
    # Regression: dedup used to append the absorbed line's events onto the
    # survivor's `.events` for display but never recompute state/counts/score
    # from that union -- a merged line could end up rendering as ACTIVE with
    # a BREAK marker sitting on it, and its stale (pre-merge) strength never
    # reflected the merge for top-N ranking purposes.
    strong = _line(
        "strong", strength=0.8, center=100.0, half_width=0.5, state=LineState.ACTIVE,
        events=[_touch("2020-02-10")],
    )
    weak_broken = _line(
        "weak_broken", strength=0.3, center=100.4, half_width=0.5, state=LineState.BROKEN,
        events=[_break("2020-03-01")],
    )
    config = SRConfig(dedup_overlap_threshold=0.6)
    bars = _flat_bars()

    deduped = dedup_lines([strong, weak_broken], bars, _atr(bars), config)

    assert len(deduped) == 1
    survivor = deduped[0]
    assert survivor.id == "strong"
    assert {e.type for e in survivor.events} == {EventType.TOUCH, EventType.BREAK}
    # The union now genuinely contains a break with no confirming event --
    # the survivor must report that, not stay ACTIVE from its own pre-merge events.
    assert survivor.state == LineState.BROKEN
    assert survivor.touch_counts.breaks == 1
    assert survivor.broken_at == "2020-03-01"
    # Score must be recomputed from the union too, not left at the stale 0.8.
    assert survivor.strength != pytest.approx(0.8)


def test_absorb_recomputes_regime_start_from_the_merged_event_union():
    # regime_start is a pure function of the event timeline, so a merge that
    # pulls in events from a different period must recompute it too, same
    # as every other derived field _absorb already recomputes -- a stale
    # pre-merge regime_start would defeat the whole point of the fix (the
    # rendered box and in_play_gate would keep judging the line by an
    # outdated notion of "current regime").
    idx = pd.bdate_range("2020-01-01", periods=1500)
    strong = _line(
        "strong", strength=0.8, center=100.0, half_width=0.5, state=LineState.ACTIVE,
        events=[_touch(idx[10].isoformat())],
    )
    weak_close = _line(
        "weak_close", strength=0.3, center=100.4, half_width=0.5, state=LineState.ACTIVE,
        events=[_touch(idx[1300].isoformat())],  # ~3.4yr gap from strong's own event
    )
    config = SRConfig(dedup_overlap_threshold=0.6, regime_gap_years=1.0)
    bars = _flat_bars(1500)

    deduped = dedup_lines([strong, weak_close], bars, _atr(bars), config)

    assert len(deduped) == 1
    survivor = deduped[0]
    assert pd.Timestamp(survivor.regime_start) == pd.Timestamp(idx[1300])


def _minimal_candidate() -> HorizontalCandidate:
    pivot = Pivot(kind=PivotKind.LOW, timestamp="2020-01-01", value=100.0, confirmed_at="2020-01-05", threshold_at_pivot=1.0)
    return HorizontalCandidate(center=100.0, half_width=1.0, pivots=[pivot, pivot])


def test_build_line_sets_regime_start_from_the_event_timeline():
    candidate = _minimal_candidate()
    idx = pd.bdate_range("2020-01-01", periods=1500)
    events = [
        _touch(idx[0].isoformat()),
        _touch(idx[50].isoformat()),
        _touch(idx[1300].isoformat()),  # gap of ~3.4 years since the previous event
        _touch(idx[1350].isoformat()),
    ]
    config = SRConfig(regime_gap_years=1.0)
    bars = _flat_bars(1500)

    line = build_line(
        "h0", candidate, events, original_side="above", scores=ScoreBreakdown(), config=config,
        bars=bars, atr=_atr(bars),
    )

    assert line.regime_start == idx[1300].isoformat()
    assert line.regime_start != line.first_touch  # a real reset, not just coincidentally equal


def test_build_line_regime_start_falls_back_to_first_touch_with_no_gap():
    candidate = _minimal_candidate()
    events = [_touch("2020-01-10"), _touch("2020-01-20")]
    config = SRConfig(regime_gap_years=1.0)
    bars = _flat_bars()

    line = build_line(
        "h0", candidate, events, original_side="above", scores=ScoreBreakdown(), config=config,
        bars=bars, atr=_atr(bars),
    )

    # No gap large enough to reset the regime -- current regime starts at
    # the line's actual founding pivot (first_touch), same instant either
    # way (string formats can differ: pivot timestamps aren't always
    # isoformat in test fixtures, unlike in the real pipeline).
    assert pd.Timestamp(line.regime_start) == pd.Timestamp(line.first_touch) == pd.Timestamp("2020-01-01")


def test_touch_counts_side_rollups_split_by_event_side_and_sum_to_the_totals():
    candidate = _minimal_candidate()
    events = [
        _touch("2020-01-10", side="above"),
        _touch("2020-01-20", side="above"),
        _touch("2020-01-30", side="below"),
        _break("2020-02-10", side="above"),
    ]
    config = SRConfig()
    bars = _flat_bars()

    line = build_line(
        "h0", candidate, events, original_side="above", scores=ScoreBreakdown(), config=config,
        bars=bars, atr=_atr(bars),
    )

    tc = line.touch_counts
    assert tc.total_from_above == 2
    assert tc.total_from_below == 1
    assert tc.total_from_above + tc.total_from_below == tc.total
    assert tc.breaks_from_above == 1
    assert tc.breaks_from_below == 0
    assert tc.breaks_from_above + tc.breaks_from_below == tc.breaks


def test_state_and_flipped_at_agree_even_after_an_unconfirmed_later_break():
    # Regression: a real AAPL line with 6 breaks had state=FLIPPED (correct,
    # since an early break was confirmed) but flipped_at=None, because the
    # old code tracked "last break" independently of the "ever confirmed"
    # check used for state -- they must come from one shared computation.
    events = [
        _touch("2020-01-10"),
        _break("2020-02-01"),
        _touch("2020-02-15"),  # confirms the flip
        _break("2020-06-01"),  # breaks again, never reclaimed
        _break("2020-09-01"),
        _break("2021-01-01"),
    ]
    candidate = _minimal_candidate()
    bars = _flat_bars(300)

    line = build_line(
        "h0", candidate, events, original_side="above", scores=ScoreBreakdown(), config=SRConfig(),
        bars=bars, atr=_atr(bars),
    )

    assert line.state == LineState.FLIPPED
    assert line.flipped_at is not None
    assert line.broken_at is not None


def test_a_resolved_body_fake_after_a_break_confirms_the_flip_too():
    # A body-fake after a break is the same "undercut and rally" evidence
    # resilience.py already grades as weaker-but-real proof of respect for
    # the *new* side: price tried to fall back through toward the old side
    # and failed, closing back on the new side. Not just a clean touch or
    # wick-fake should be able to confirm a flip.
    events = [
        _break("2020-02-01"),
        Event(type=EventType.BODY_FAKE, start="2020-02-10", end="2020-02-12",
              penetration_atr=0.4, reaction_atr=0.0, pending=False,
              reclaimed=True, reclaimed_at="2020-02-12", bars_to_reclaim=2),
    ]
    candidate = _minimal_candidate()
    bars = _flat_bars()

    line = build_line(
        "h0", candidate, events, original_side="above", scores=ScoreBreakdown(), config=SRConfig(),
        bars=bars, atr=_atr(bars),
    )

    assert line.state == LineState.FLIPPED
    assert line.flipped_at == "2020-02-10"


def test_a_pending_body_fake_after_a_break_does_not_confirm_the_flip():
    # Still unresolved -- hasn't actually reclaimed yet, so it can't count as
    # proof the new side is being respected.
    events = [
        _break("2020-02-01"),
        Event(type=EventType.BODY_FAKE, start="2020-02-10", end="2020-02-12",
              penetration_atr=0.4, reaction_atr=0.0, pending=True),
    ]
    candidate = _minimal_candidate()
    bars = _flat_bars()

    line = build_line(
        "h0", candidate, events, original_side="above", scores=ScoreBreakdown(), config=SRConfig(),
        bars=bars, atr=_atr(bars),
    )

    assert line.state == LineState.BROKEN
    assert line.flipped_at is None


def _minimal_diagonal_candidate(
    slope: float = 0.001, intercept: float = math.log(100.0), origin_index: int = 0, half_width: float = 0.02,
) -> DiagonalCandidate:
    pivot = Pivot(
        kind=PivotKind.LOW, timestamp="2020-01-01", value=100.0,
        confirmed_at="2020-01-05", threshold_at_pivot=2.0, bar_index=0,
    )
    return DiagonalCandidate(slope=slope, intercept=intercept, origin_index=origin_index,
                              half_width=half_width, pivots=[pivot, pivot])


def _diag_line(
    line_id: str, strength: float, slope: float = 0.001, intercept: float = math.log(100.0),
    origin_index: int = 0, half_width: float = 0.02, events: list[Event] | None = None,
    first_touch: str = "2020-01-01",
) -> Line:
    events = events or []
    return Line(
        id=line_id, kind=LineKind.DIAGONAL, role=LineRole.SUPPORT, state=LineState.ACTIVE,
        center=None, half_width=half_width, slope=slope, intercept=intercept, origin_index=origin_index,
        first_touch=first_touch, last_event=first_touch, events=events,
        scores=ScoreBreakdown(total=strength), strength=strength,
        touch_counts=TouchCounts(breaks=sum(1 for e in events if e.type == EventType.BREAK)),
    )


def test_build_line_populates_diagonal_geometry_not_a_flat_center():
    candidate = _minimal_diagonal_candidate()
    bars = _flat_bars()

    line = build_line(
        "d0", candidate, events=[], original_side="above", scores=ScoreBreakdown(), config=SRConfig(),
        bars=bars, atr=_atr(bars),
    )

    assert line.kind == LineKind.DIAGONAL
    assert line.center is None  # diagonal has no single center -- price_at() instead
    assert line.slope == candidate.slope
    assert line.intercept == candidate.intercept
    assert line.origin_index == candidate.origin_index
    assert line.half_width == candidate.half_width


def test_dedup_merges_diagonal_lines_whose_bands_are_close_at_the_reference_bar():
    bars = _flat_bars(60)  # reference bar index = 59
    strong = _diag_line("strong", strength=0.8, intercept=math.log(100.0))
    weak_close = _diag_line("weak_close", strength=0.3, intercept=math.log(100.3))
    config = SRConfig(dedup_overlap_threshold=0.6)

    deduped = dedup_lines([strong, weak_close], bars, _atr(bars), config)

    assert {line.id for line in deduped} == {"strong"}


def test_dedup_does_not_pull_a_diagonal_survivors_first_touch_back_to_the_absorbed_lines():
    # Regression: a real AAPL line had first_touch pulled back to 2018-09
    # from an absorbed candidate, rendering its box across a period its own
    # fitted geometry (slope/intercept, unchanged by the merge) was never
    # actually fit against -- the fitted price 2 years before the survivor's
    # own earliest defining pivot had no relationship to real price that
    # far back. Valid for horizontal (constant bounds, so "touched earlier
    # too" always holds) but not diagonal, where the survivor's own
    # first_touch must stay put regardless of what gets absorbed into it.
    bars = _flat_bars(60)
    strong = _diag_line("strong", strength=0.8, intercept=math.log(100.0), first_touch="2020-01-15")
    weak_close = _diag_line(
        "weak_close", strength=0.3, intercept=math.log(100.3), first_touch="2020-01-02",
    )
    config = SRConfig(dedup_overlap_threshold=0.6)

    deduped = dedup_lines([strong, weak_close], bars, _atr(bars), config)

    assert len(deduped) == 1
    assert deduped[0].id == "strong"
    assert deduped[0].first_touch == "2020-01-15"  # survivor's own, not pulled back to 2020-01-02


def test_dedup_does_not_merge_diagonal_lines_with_different_slopes():
    # Two lines whose bands happen to coincide at "now" but diverge
    # everywhere else -- a real merge here would misrepresent both.
    bars = _flat_bars(60)
    up = _diag_line("up", strength=0.8, slope=0.01, intercept=math.log(100.0))
    down = _diag_line("down", strength=0.5, slope=-0.01, intercept=math.log(100.0))
    config = SRConfig(dedup_overlap_threshold=0.6, max_diagonal_slope_atr_per_bar=0.05)

    deduped = dedup_lines([up, down], bars, _atr(bars), config)

    assert {line.id for line in deduped} == {"up", "down"}


def test_dedup_never_merges_a_horizontal_line_with_a_diagonal_line():
    bars = _flat_bars(60)
    horizontal = _line("h0", strength=0.8, center=100.0, half_width=1.0)
    diagonal = _diag_line("d0", strength=0.5, slope=0.0, intercept=math.log(100.0), half_width=0.05)
    config = SRConfig(dedup_overlap_threshold=0.6)

    deduped = dedup_lines([horizontal, diagonal], bars, _atr(bars), config)

    assert {line.id for line in deduped} == {"h0", "d0"}

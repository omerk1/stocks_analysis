import pandas as pd
import pytest

from src.sr_lines.candidates import HorizontalCandidate
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
)


def _flat_bars(n_days: int = 60, price: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n_days)
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
        n_breaks=sum(1 for e in events if e.type == EventType.BREAK),
    )


def _touch(date: str) -> Event:
    return Event(type=EventType.TOUCH, start=date, end=date, penetration_atr=0.1, reaction_atr=1.0)


def _break(date: str) -> Event:
    return Event(type=EventType.BREAK, start=date, end=date, penetration_atr=1.0, reaction_atr=0.0)


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
    assert survivor.n_breaks == 1
    assert survivor.broken_at == "2020-03-01"
    # Score must be recomputed from the union too, not left at the stale 0.8.
    assert survivor.strength != pytest.approx(0.8)


def _minimal_candidate() -> HorizontalCandidate:
    pivot = Pivot(kind=PivotKind.LOW, timestamp="2020-01-01", price=100.0, confirmed_at="2020-01-05", atr_at_pivot=1.0)
    return HorizontalCandidate(center=100.0, half_width=1.0, pivots=[pivot, pivot])


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

    line = build_line("h0", candidate, events, original_side="above", scores=ScoreBreakdown())

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
              penetration_atr=0.4, reaction_atr=0.0, pending=False),
    ]
    candidate = _minimal_candidate()

    line = build_line("h0", candidate, events, original_side="above", scores=ScoreBreakdown())

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

    line = build_line("h0", candidate, events, original_side="above", scores=ScoreBreakdown())

    assert line.state == LineState.BROKEN
    assert line.flipped_at is None

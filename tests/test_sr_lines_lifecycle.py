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


def _line(line_id: str, strength: float, center: float = 100.0, half_width: float = 1.0) -> Line:
    return Line(
        id=line_id,
        kind=LineKind.HORIZONTAL,
        role=LineRole.SUPPORT,
        state=LineState.ACTIVE,
        center=center,
        half_width=half_width,
        slope=None,
        intercept=None,
        origin_index=None,
        first_touch="2020-01-01",
        last_event="2020-01-01",
        scores=ScoreBreakdown(total=strength),
        strength=strength,
    )


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

    deduped = dedup_lines([strong, weak_close, far_away], config)

    assert {line.id for line in deduped} == {"strong", "far_away"}


def test_dedup_does_not_merge_zones_separated_by_a_large_gap():
    a = _line("a", strength=0.8, center=100.0, half_width=0.5)
    b = _line("b", strength=0.5, center=105.0, half_width=0.5)  # 4.0 gap, way over threshold
    config = SRConfig(dedup_overlap_threshold=0.6)

    deduped = dedup_lines([a, b], config)

    assert {line.id for line in deduped} == {"a", "b"}


def _touch(date: str) -> Event:
    return Event(type=EventType.TOUCH, start=date, end=date, penetration_atr=0.1, reaction_atr=1.0)


def _break(date: str) -> Event:
    return Event(type=EventType.BREAK, start=date, end=date, penetration_atr=1.0, reaction_atr=0.0)


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

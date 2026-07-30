from src.sr_lines.config import SRConfig
from src.sr_lines.lifecycle import select_lines
from src.sr_lines.models import Line, LineKind, LineRole, LineState, ScoreBreakdown


def _line(line_id: str, strength: float) -> Line:
    return Line(
        id=line_id,
        kind=LineKind.HORIZONTAL,
        role=LineRole.SUPPORT,
        state=LineState.ACTIVE,
        center=100.0,
        half_width=1.0,
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

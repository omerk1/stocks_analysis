import pandas as pd

from src.sr_lines.models import (
    DataQualityReport,
    DetectionResult,
    Event,
    EventType,
    Line,
    LineKind,
    LineRole,
    LineState,
    ScoreBreakdown,
)
from src.sr_lines.plotting import _EVENT_MARKERS, render_review_chart


def _bars(n_days: int, price: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    return pd.DataFrame(
        {"open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1_000_000},
        index=idx,
    )


def _empty_result(as_of: str) -> DetectionResult:
    return DetectionResult(
        ticker="TEST", source="yfinance", as_of=as_of, config_snapshot={},
        data_quality=DataQualityReport(ticker="TEST", rows_loaded=0, rows_dropped=0, drop_rate=0.0),
        lines=[],
    )


def test_no_cutoff_marker_when_reference_date_is_the_last_bar():
    bars = _bars(30)
    result = _empty_result(bars.index[-1].isoformat())

    fig = render_review_chart(bars, result, reference_date=bars.index[-1])

    assert len(fig.layout.shapes) == 0


def test_cutoff_marker_shown_when_reference_date_is_before_the_last_bar():
    bars = _bars(30)
    reference_date = bars.index[10]  # a backtest: display extends past the as_of cutoff
    result = _empty_result(reference_date.isoformat())

    fig = render_review_chart(bars, result, reference_date=reference_date)

    assert len(fig.layout.shapes) == 1
    assert fig.layout.shapes[0].x0 == fig.layout.shapes[0].x1 == reference_date


def test_break_and_body_fake_markers_are_visually_distinct():
    # Regression: a real NVDA chart showed BODY_FAKE ("x", dark red) and
    # BREAK ("x-thin", darker red) reading as near-identical marks at normal
    # zoom -- easy to misread a nearby line's real break as sitting on a
    # zone that never actually broke. Symbol and color must both differ now.
    break_symbol, break_color, *_ = _EVENT_MARKERS[EventType.BREAK]
    body_fake_symbol, body_fake_color, *_ = _EVENT_MARKERS[EventType.BODY_FAKE]

    assert break_symbol != body_fake_symbol
    assert break_color != body_fake_color


def _line_with_break_and_flip(line_id: str) -> Line:
    events = [
        Event(type=EventType.BREAK, start="2020-01-10", end="2020-01-10",
              penetration_atr=1.0, reaction_atr=0.0),
        Event(type=EventType.TOUCH, start="2020-01-20", end="2020-01-20",
              penetration_atr=0.1, reaction_atr=1.0),
    ]
    return Line(
        id=line_id, kind=LineKind.HORIZONTAL, role=LineRole.FLIPPED, state=LineState.FLIPPED,
        center=100.0, half_width=1.0, slope=None, intercept=None, origin_index=None,
        first_touch="2020-01-01", last_event="2020-01-20", events=events,
        scores=ScoreBreakdown(total=0.5), strength=0.5,
        broken_at="2020-01-10", flipped_at="2020-01-20",
    )


def test_break_and_flip_annotations_include_the_line_id():
    # Regression: a bare "break"/"flip" label is ambiguous when two zones'
    # centers are only a few dollars apart -- compressed against the chart's
    # full price range, the label can visually read as belonging to whichever
    # nearby box it happens to land closest to, not the line it's actually for.
    bars = _bars(30)
    line = _line_with_break_and_flip("h7")
    result = DetectionResult(
        ticker="TEST", source="yfinance", as_of=bars.index[-1].isoformat(), config_snapshot={},
        data_quality=DataQualityReport(ticker="TEST", rows_loaded=30, rows_dropped=0, drop_rate=0.0),
        lines=[line],
    )

    fig = render_review_chart(bars, result, reference_date=bars.index[-1])

    annotation_texts = [a.text for a in fig.layout.annotations]
    assert "h7 break" in annotation_texts
    assert "h7 flip" in annotation_texts


def test_hover_text_includes_the_gate_components():
    # relevance_gate and in_play_gate are computed and stored on every
    # ScoreBreakdown but were silently missing from the chart itself,
    # forcing debugging via ad hoc scripts instead of just hovering.
    bars = _bars(30)
    line = _line_with_break_and_flip("h7")
    result = DetectionResult(
        ticker="TEST", source="yfinance", as_of=bars.index[-1].isoformat(), config_snapshot={},
        data_quality=DataQualityReport(ticker="TEST", rows_loaded=30, rows_dropped=0, drop_rate=0.0),
        lines=[line],
    )

    fig = render_review_chart(bars, result, reference_date=bars.index[-1])

    band_trace = next(t for t in fig.data if t.name and t.name.startswith("h7 ["))
    assert "relevance_gate=" in band_trace.hovertext
    assert "in_play_gate=" in band_trace.hovertext


def _diagonal_line(line_id: str) -> Line:
    events = [
        Event(type=EventType.BREAK, start="2020-01-10", end="2020-01-10",
              penetration_atr=1.0, reaction_atr=0.0),
        Event(type=EventType.TOUCH, start="2020-01-20", end="2020-01-20",
              penetration_atr=0.1, reaction_atr=1.0),
    ]
    return Line(
        id=line_id, kind=LineKind.DIAGONAL, role=LineRole.FLIPPED, state=LineState.FLIPPED,
        center=None, half_width=0.02, slope=0.01, intercept=4.6052, origin_index=0,  # ln(100) ~= 4.6052
        first_touch="2020-01-01", last_event="2020-01-20", events=events,
        scores=ScoreBreakdown(total=0.5), strength=0.5,
        broken_at="2020-01-10", flipped_at="2020-01-20",
    )


def test_diagonal_band_is_sloped_not_a_flat_rectangle():
    bars = _bars(30)
    line = _diagonal_line("d0")
    result = DetectionResult(
        ticker="TEST", source="yfinance", as_of=bars.index[-1].isoformat(), config_snapshot={},
        data_quality=DataQualityReport(ticker="TEST", rows_loaded=30, rows_dropped=0, drop_rate=0.0),
        lines=[line],
    )

    fig = render_review_chart(bars, result, reference_date=bars.index[-1])

    band_trace = next(t for t in fig.data if t.name and t.name.startswith("d0 ["))
    y = list(band_trace.y)
    # 5-point closed polygon: [lo0, lo1, hi1, hi0, lo0] -- lo0 must differ
    # from lo1 (and hi0 from hi1) for a genuinely sloped band, not a flat one.
    assert y[0] != y[1]
    assert y[2] != y[3]


def test_diagonal_markers_and_annotations_follow_price_at_not_a_flat_center():
    bars = _bars(30)
    line = _diagonal_line("d0")
    result = DetectionResult(
        ticker="TEST", source="yfinance", as_of=bars.index[-1].isoformat(), config_snapshot={},
        data_quality=DataQualityReport(ticker="TEST", rows_loaded=30, rows_dropped=0, drop_rate=0.0),
        lines=[line],
    )

    fig = render_review_chart(bars, result, reference_date=bars.index[-1])

    touch_trace = next(t for t in fig.data if t.name == "touch")
    expected_y = line.price_at(bars.index.get_loc(pd.Timestamp("2020-01-20")))
    assert touch_trace.y[0] == expected_y

    break_annotation = next(a for a in fig.layout.annotations if a.text == "d0 break")
    expected_break_y = line.price_at(bars.index.get_loc(pd.Timestamp("2020-01-10")))
    assert break_annotation.y == expected_break_y

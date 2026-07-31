import pandas as pd

from src.sr_lines.models import DetectionResult, DataQualityReport
from src.sr_lines.plotting import render_review_chart


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

import pandas as pd
import pytest

from src.foundation.market_common.models import Pivot, PivotKind, Timeframe
from src.signals.market_structure.backtest import (
    StructureOutcome,
    compute_outcomes,
    forward_return_pct,
    summarize,
)
from src.signals.market_structure.models import Direction, StructureEvent, TrendState


def _bars(closes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes))
    closes_s = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {"open": closes_s, "high": closes_s + 0.3, "low": closes_s - 0.3, "close": closes_s, "volume": 1000.0},
        index=idx,
    )


_STEP_BARS = _bars([100.0] * 11 + [90.0] * 5)


def _pivot(price: float = 100.0) -> Pivot:
    return Pivot(kind=PivotKind.LOW, timestamp="2020-01-01", value=price, confirmed_at="2020-01-01", threshold_at_pivot=1.0)


def _event(
    event: StructureEvent = StructureEvent.CHOCH, direction: Direction = Direction.BULLISH,
    broken_at: str = "", close: float = 100.0, event_id: str = "e1",
) -> TrendState:
    return TrendState(
        id=event_id, ticker="TST", timeframe=Timeframe.DAILY, event=event, direction=direction,
        broken_pivot=_pivot(), broken_at=broken_at, close=close, volume_confirmed=False,
    )


def test_forward_return_pct_bullish_is_raw_price_return():
    event = _event(direction=Direction.BULLISH, broken_at=_STEP_BARS.index[10].isoformat(), close=100.0)
    assert forward_return_pct(_STEP_BARS, event, 3) == pytest.approx(-0.10)


def test_forward_return_pct_bearish_is_negated_so_a_price_drop_is_a_positive_return():
    event = _event(direction=Direction.BEARISH, broken_at=_STEP_BARS.index[10].isoformat(), close=100.0)
    assert forward_return_pct(_STEP_BARS, event, 3) == pytest.approx(0.10)


def test_forward_return_pct_none_past_end_of_bars():
    event = _event(broken_at=_STEP_BARS.index[10].isoformat(), close=100.0)
    assert forward_return_pct(_STEP_BARS, event, 100) is None


def test_compute_outcomes_one_per_event_bos_has_no_whipsaw_verdict():
    bars = _bars([100.0] * 20)
    events = [_event(event=StructureEvent.BOS, broken_at=bars.index[5].isoformat())]

    outcomes = compute_outcomes(events, bars, horizons=(3,))

    assert len(outcomes) == 1
    assert outcomes[0].whipsawed is None


def test_compute_outcomes_choch_whipsawed_true_when_opposite_choch_follows_within_window():
    bars = _bars([100.0] * 30)
    first = _event(
        event=StructureEvent.CHOCH, direction=Direction.BULLISH, broken_at=bars.index[5].isoformat(), event_id="e1",
    )
    reversal = _event(
        event=StructureEvent.CHOCH, direction=Direction.BEARISH, broken_at=bars.index[15].isoformat(), event_id="e2",
    )

    outcomes = compute_outcomes([first, reversal], bars, horizons=(3,), whipsaw_bars=20)
    by_id = {o.event_id: o for o in outcomes}

    assert by_id["e1"].whipsawed is True
    # e2's own whipsaw_bars window (break_idx 15 + 20 = 35) reaches past
    # the last available bar (index 29) -- right-censored, not a genuine
    # "did not whipsaw" (see test_compute_outcomes_choch_whipsawed_none_when_window_extends_past_available_bars).
    assert by_id["e2"].whipsawed is None


def test_compute_outcomes_choch_whipsawed_false_outside_the_window():
    bars = _bars([100.0] * 30)
    first = _event(
        event=StructureEvent.CHOCH, direction=Direction.BULLISH, broken_at=bars.index[5].isoformat(), event_id="e1",
    )
    reversal = _event(
        event=StructureEvent.CHOCH, direction=Direction.BEARISH, broken_at=bars.index[27].isoformat(), event_id="e2",
    )

    outcomes = compute_outcomes([first, reversal], bars, horizons=(3,), whipsaw_bars=5)

    assert next(o for o in outcomes if o.event_id == "e1").whipsawed is False


def test_compute_outcomes_choch_whipsawed_none_when_window_extends_past_available_bars():
    # A CHoCH 10 bars from the end of history with whipsaw_bars=60: only 10
    # of the 60 bars needed to rule out a reversal actually exist. No
    # opposite CHoCH occurred in the data available -- but that's "not
    # observable yet", not "the regime survived a 60-bar window it was
    # never actually tested against".
    bars = _bars([100.0] * 20)
    event = _event(event=StructureEvent.CHOCH, direction=Direction.BULLISH, broken_at=bars.index[10].isoformat())

    outcomes = compute_outcomes([event], bars, horizons=(3,), whipsaw_bars=60)

    assert outcomes[0].whipsawed is None


def _outcome(event: str, direction: str, r: float, whipsawed: bool | None = None) -> StructureOutcome:
    return StructureOutcome(
        event_id=f"m{r}", ticker="TST", timeframe="daily", event=event, direction=direction,
        broken_at="2020-01-01", break_bar=1, forward_returns={5: r}, whipsawed=whipsawed,
    )


def test_summarize_groups_by_event_and_direction():
    outcomes = [
        _outcome("choch", "bullish", 0.05, whipsawed=False),
        _outcome("choch", "bullish", 0.03, whipsawed=True),
        _outcome("bos", "bearish", -0.02),
    ]

    result = summarize(outcomes, horizons=(5,))

    assert set(result.index) == {"choch_bullish", "bos_bearish"}
    assert result.loc["choch_bullish", "n"] == 2
    assert result.loc["choch_bullish", "whipsaw_rate"] == pytest.approx(0.5)
    # BOS never carries a whipsaw verdict -- rate is NaN (pandas coerces
    # the column to float64 once another bucket's row has a real value),
    # not 0.
    assert pd.isna(result.loc["bos_bearish", "whipsaw_rate"])
    assert result.loc["bos_bearish", "mean_return_5b"] == pytest.approx(-0.02)


def test_summarize_empty_outcomes_carries_expected_columns():
    cols = summarize([], horizons=(10,)).columns
    for name in (
        "mean_return_10b", "median_return_10b", "wins_return_10b", "std_return_10b",
        "risk_adj_return_10b", "p10_return_10b", "p90_return_10b", "n_resolved_10b",
    ):
        assert name in cols
    assert "whipsaw_rate" in cols

import pandas as pd

from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.lifecycle import apply_outcome
from src.signals.divergences.models import Direction, Divergence, IndicatorKind
from src.foundation.market_common.models import Timeframe


def _bars(rows: list[tuple], start: str = "2020-01-01") -> pd.DataFrame:
    """rows: list of (high, low, close)"""
    idx = pd.date_range(start, periods=len(rows), freq="D")
    df = pd.DataFrame(
        [(h, low, c, c) for h, low, c in rows],
        columns=["high", "low", "close", "open"], index=idx,
    )
    return df[["open", "high", "low", "close"]]


def _divergence(direction: Direction, p2_price: float, confirmed_at: str) -> Divergence:
    return Divergence(
        id="d1", ticker="TEST", timeframe=Timeframe.DAILY, indicator=IndicatorKind.RSI,
        direction=direction, p1_date="2020-01-01", p2_date=confirmed_at,
        p1_price=100.0, p2_price=p2_price, i1_value=30.0, i2_value=40.0, strength=0.5,
        duration_bars=10, price_move_atr=2.0, appeared_at=confirmed_at, confirmed_at=confirmed_at,
    )


def test_bullish_favorable_move_is_the_atr_normalized_best_high_above_p2():
    # p2_price=95 (the bullish divergence's own low). Highs after
    # confirmed_at climb: 96, 98, 105 -> best favorable = (105-95)/2 = 5.0,
    # reached 3 bars after confirmed_at.
    dates = pd.date_range("2020-01-11", periods=4, freq="D")
    rows = [(95.5, 95.0, 95.2), (96.0, 95.2, 95.5), (98.0, 96.0, 97.0), (105.0, 100.0, 104.0)]
    bars = _bars(rows, start=dates[0].isoformat())
    atr = pd.Series(2.0, index=bars.index)
    divergence = _divergence(Direction.BULLISH, p2_price=95.0, confirmed_at="2020-01-10")
    config = DivergenceConfig(outcome_window_bars=10)

    apply_outcome(bars, atr, divergence, config)

    assert divergence.max_favorable_move_atr == 5.0
    assert divergence.bars_to_max_favorable_move == 4
    assert divergence.invalidated is False
    assert divergence.outcome_computed_through == bars.index[-1].isoformat()


def test_bearish_favorable_move_is_the_atr_normalized_best_low_below_p2():
    dates = pd.date_range("2020-01-11", periods=3, freq="D")
    rows = [(105.0, 104.0, 104.5), (104.0, 100.0, 101.0), (101.0, 90.0, 91.0)]
    bars = _bars(rows, start=dates[0].isoformat())
    atr = pd.Series(2.0, index=bars.index)
    divergence = _divergence(Direction.BEARISH, p2_price=105.0, confirmed_at="2020-01-10")
    config = DivergenceConfig(outcome_window_bars=10)

    apply_outcome(bars, atr, divergence, config)

    # best favorable = (105 - 90) / 2 = 7.5, at bar 3
    assert divergence.max_favorable_move_atr == 7.5
    assert divergence.bars_to_max_favorable_move == 3
    assert divergence.invalidated is False


def test_bullish_invalidated_when_price_makes_a_new_lower_low():
    dates = pd.date_range("2020-01-11", periods=3, freq="D")
    rows = [(96.0, 95.0, 95.5), (95.0, 90.0, 91.0), (98.0, 96.0, 97.0)]  # bar1 low=90 < p2_price=95
    bars = _bars(rows, start=dates[0].isoformat())
    atr = pd.Series(2.0, index=bars.index)
    divergence = _divergence(Direction.BULLISH, p2_price=95.0, confirmed_at="2020-01-10")
    config = DivergenceConfig(outcome_window_bars=10)

    apply_outcome(bars, atr, divergence, config)

    assert divergence.invalidated is True
    assert divergence.invalidated_at == bars.index[1].isoformat()
    # Invalidation doesn't stop tracking the favorable move -- both are
    # reported independently.
    assert divergence.max_favorable_move_atr is not None


def test_bearish_invalidated_when_price_makes_a_new_higher_high():
    dates = pd.date_range("2020-01-11", periods=2, freq="D")
    rows = [(112.0, 108.0, 110.0), (105.0, 100.0, 102.0)]  # bar0 high=112 > p2_price=110
    bars = _bars(rows, start=dates[0].isoformat())
    atr = pd.Series(2.0, index=bars.index)
    divergence = _divergence(Direction.BEARISH, p2_price=110.0, confirmed_at="2020-01-10")
    config = DivergenceConfig(outcome_window_bars=10)

    apply_outcome(bars, atr, divergence, config)

    assert divergence.invalidated is True
    assert divergence.invalidated_at == bars.index[0].isoformat()


def test_no_bars_after_confirmed_at_leaves_outcome_unresolved():
    bars = _bars([(101.0, 99.0, 100.0)], start="2020-01-10")  # only bar IS confirmed_at itself
    atr = pd.Series(2.0, index=bars.index)
    divergence = _divergence(Direction.BULLISH, p2_price=95.0, confirmed_at="2020-01-10")
    config = DivergenceConfig()

    apply_outcome(bars, atr, divergence, config)

    assert divergence.outcome_computed_through is None
    assert divergence.max_favorable_move_atr is None
    assert divergence.bars_to_max_favorable_move is None
    assert divergence.invalidated is False


def test_outcome_window_bounds_how_far_the_walk_looks():
    dates = pd.date_range("2020-01-11", periods=5, freq="D")
    # A huge favorable move sits at bar 4, but the window only allows 2 bars.
    rows = [(96.0, 95.0, 95.5)] * 3 + [(200.0, 195.0, 198.0), (96.0, 95.0, 95.5)]
    bars = _bars(rows, start=dates[0].isoformat())
    atr = pd.Series(2.0, index=bars.index)
    divergence = _divergence(Direction.BULLISH, p2_price=95.0, confirmed_at="2020-01-10")
    config = DivergenceConfig(outcome_window_bars=2)

    apply_outcome(bars, atr, divergence, config)

    assert divergence.outcome_computed_through == bars.index[1].isoformat()
    assert divergence.max_favorable_move_atr == 0.5  # (96-95)/2, not the bar-4 spike

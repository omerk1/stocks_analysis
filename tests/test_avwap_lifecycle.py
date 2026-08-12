import pandas as pd
import pytest

from src.avwap.config import AvwapConfig
from src.avwap.lifecycle import apply_interaction_tracking
from src.avwap.models import AnchoredVwap, AnchorStatus, AnchorType
from src.market_common.models import Timeframe


def _bars(rows: list[tuple], start: str = "2020-01-01") -> pd.DataFrame:
    """rows: list of (close, high, low, volume); open unused by this module."""
    idx = pd.date_range(start, periods=len(rows), freq="D")
    df = pd.DataFrame(
        [(c, h, low, c, v) for c, h, low, v in rows],
        columns=["open", "high", "low", "close", "volume"], index=idx,
    )
    return df


def _anchor(anchor_date: str) -> AnchoredVwap:
    return AnchoredVwap(
        id="a1", ticker="TEST", timeframe=Timeframe.DAILY, anchor_date=anchor_date,
        anchor_types=frozenset({AnchorType.ATH}), status=AnchorStatus.ACTIVE,
    )


def test_no_crosses_when_close_always_matches_the_running_average():
    bars = _bars([(100, 100, 100, 100)] * 4, start="2020-01-01")
    atr = pd.Series(2.0, index=bars.index)
    anchor = _anchor(bars.index[0].isoformat())
    config = AvwapConfig(price_source="close")

    apply_interaction_tracking(bars, atr, anchor, config)

    assert anchor.n_crosses == 0
    assert anchor.pct_bars_above == 1.0
    assert anchor.pct_bars_below == 0.0
    assert anchor.last_cross_date is None


def test_crosses_counted_when_close_moves_to_the_other_side_of_the_line():
    # price_source="close", constant volume -> avwap is a plain running
    # average of close. closes=[100,100,90,90,110,110]:
    # avwap: 100, 100, 96.67, 95, 98, 100
    # diff:  0,   0,   -6.67, -5, 12, 10 (tolerance = 0.3*2.0 = 0.6)
    # Bars 0-1 sit exactly on the line (inside tolerance, ambiguous). Bar 2
    # is the *first* bar to clearly commit to a side ("below") -- a
    # bootstrap, not a cross, same convention sr_lines/fibonacci already
    # use for establishing an initial side. Only bar 4 (below -> above) is
    # a real crossover.
    rows = [(c, c, c, 100) for c in [100, 100, 90, 90, 110, 110]]
    bars = _bars(rows)
    atr = pd.Series(2.0, index=bars.index)
    anchor = _anchor(bars.index[0].isoformat())
    config = AvwapConfig(price_source="close")

    apply_interaction_tracking(bars, atr, anchor, config)

    assert anchor.n_crosses == 1
    assert anchor.last_cross_date == bars.index[4].isoformat()
    assert anchor.pct_bars_above == pytest.approx(4 / 6)
    assert anchor.pct_bars_below == pytest.approx(2 / 6)


def test_daily_chatter_within_tolerance_does_not_inflate_n_crosses():
    # Regression: bar0 (huge volume) anchors avwap near 100; bar1 (tiny
    # volume, so it barely moves the running average) establishes a clear
    # "below" side. Bars 2-9 then chatter +-0.1 around the still-~100
    # average every single day (tiny volume again) -- well inside the
    # 0.3*atr=0.6 tolerance band, so this must NOT count as 8 separate
    # crosses just because the sign of (close - avwap) flips daily. Only
    # the real move back above in the final bar is a genuine cross.
    closes = [100.0, 95.0, 100.1, 99.9, 100.1, 99.9, 100.1, 99.9, 100.1, 99.9, 130.0]
    volumes = [1_000_000] + [1] * 10
    rows = [(c, c, c, v) for c, v in zip(closes, volumes)]
    bars = _bars(rows)
    atr = pd.Series(2.0, index=bars.index)
    anchor = _anchor(bars.index[0].isoformat())
    config = AvwapConfig(price_source="close", distance_tolerance_atr=0.3)

    apply_interaction_tracking(bars, atr, anchor, config)

    assert anchor.n_crosses == 1
    assert anchor.last_cross_date == bars.index[-1].isoformat()


def test_distance_atr_and_reaction_only_counted_within_tolerance():
    # closes=[100,100,100,120], constant volume -> avwap = 100,100,100,105.
    # First three bars: close == avwap exactly (a touch); bar3 (close=120,
    # avwap=105) is 7.5 ATR away -- well outside the default 0.3 tolerance,
    # so it never counts as a touch, only as the final distance_atr snapshot.
    rows = [
        (100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100),
        (120, 130, 110, 100),
    ]
    bars = _bars(rows)
    atr = pd.Series(2.0, index=bars.index)
    anchor = _anchor(bars.index[0].isoformat())
    config = AvwapConfig(price_source="close", distance_tolerance_atr=0.3, touch_reaction_window_bars=10)

    apply_interaction_tracking(bars, atr, anchor, config)

    assert anchor.distance_atr == (120 - 105) / 2.0
    # Every touch bar's forward-favorable-move is dominated by bar3's
    # high=130 -> (130 - 100) / atr(2.0) = 15.0 for all three.
    assert anchor.avg_reaction_atr_on_touch == 15.0
    assert anchor.current_value == 105.0
    assert anchor.updated_through == bars.index[-1].isoformat()


def test_anchor_date_after_all_available_bars_leaves_defaults():
    bars = _bars([(100, 100, 100, 100)])
    atr = pd.Series(2.0, index=bars.index)
    anchor = _anchor("2020-06-01")  # well after the only available bar
    config = AvwapConfig()

    apply_interaction_tracking(bars, atr, anchor, config)

    assert anchor.current_value is None
    assert anchor.n_crosses == 0
    assert anchor.pct_bars_above is None
    assert anchor.avg_reaction_atr_on_touch is None

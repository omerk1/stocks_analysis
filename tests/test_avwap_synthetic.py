import math

import pandas as pd
import pytest

from src.signals.avwap.anchors import discover_anchor_dates
from src.signals.avwap.compute import anchored_vwap
from src.signals.avwap.config import AvwapConfig
from src.signals.avwap.models import AnchorStatus, AnchorType, is_pure_cycle
from src.foundation.market_common.models import Timeframe


def _bars(rows, start: str = "2020-01-01"):
    """rows: list of (open, high, low, close, volume)"""
    idx = pd.bdate_range(start, periods=len(rows))
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    return df


# ---------------------------------------------------------------------------
# M1: anchored_vwap (tests 1-5) -- independent of anchor discovery
# ---------------------------------------------------------------------------

def test_cumulative_hlc3_avwap_matches_hand_computed_values():
    bars = _bars([
        (10, 12, 8, 10, 100),   # hlc3 = 10, pv = 1000
        (10, 14, 10, 12, 200),  # hlc3 = 12, pv = 2400
        (12, 13, 11, 12, 50),   # hlc3 = 12, pv = 600
    ])
    anchor = bars.index[0]

    result = anchored_vwap(bars, anchor, price_source="hlc3")

    expected_0 = 1000 / 100
    expected_1 = (1000 + 2400) / (100 + 200)
    expected_2 = (1000 + 2400 + 600) / (100 + 200 + 50)
    assert result.iloc[0] == pytest.approx(expected_0)
    assert result.iloc[1] == pytest.approx(expected_1)
    assert result.iloc[2] == pytest.approx(expected_2)


def test_bars_before_anchor_date_are_nan():
    bars = _bars([
        (10, 11, 9, 10, 100),
        (10, 11, 9, 10, 100),
        (10, 11, 9, 10, 100),
        (10, 11, 9, 10, 100),
    ])
    anchor = bars.index[2]

    result = anchored_vwap(bars, anchor, price_source="close")

    assert math.isnan(result.iloc[0])
    assert math.isnan(result.iloc[1])
    assert not math.isnan(result.iloc[2])
    assert not math.isnan(result.iloc[3])


def test_zero_volume_bar_is_a_no_op_not_a_reset():
    bars = _bars([
        (10, 11, 9, 10, 100),   # anchor bar
        (20, 21, 19, 20, 0),    # zero volume -- should not move the AVWAP
        (10, 11, 9, 10, 100),
    ])
    anchor = bars.index[0]

    result = anchored_vwap(bars, anchor, price_source="close")

    assert result.iloc[1] == pytest.approx(result.iloc[0])
    assert result.iloc[0] == pytest.approx(10.0)
    # bar 2 blends bar 0 and bar 2 (both close=10, both vol=100) -- the
    # zero-volume bar 1 contributed nothing, so the running average is
    # exactly 10, not skewed toward the skipped bar's price of 20.
    assert result.iloc[2] == pytest.approx(10.0)


def test_still_zero_cumulative_volume_at_a_bar_is_nan_not_error_or_inf():
    bars = _bars([
        (10, 11, 9, 10, 0),
        (10, 11, 9, 10, 0),
        (10, 11, 9, 10, 100),
    ])
    anchor = bars.index[0]

    result = anchored_vwap(bars, anchor, price_source="close")

    assert math.isnan(result.iloc[0])
    assert math.isnan(result.iloc[1])
    assert not math.isnan(result.iloc[2])
    assert math.isfinite(result.iloc[2])


def test_close_price_source_differs_from_hlc3():
    bars = _bars([
        (10, 20, 0, 10, 100),   # hlc3 = 10, close = 10 -- same on bar 0
        (10, 30, 0, 20, 200),   # hlc3 = 50/3, close = 20 -- diverge here
    ])
    anchor = bars.index[0]

    hlc3_result = anchored_vwap(bars, anchor, price_source="hlc3")
    close_result = anchored_vwap(bars, anchor, price_source="close")

    expected_close_1 = (10 * 100 + 20 * 200) / (100 + 200)
    hlc3_bar1 = (30 + 0 + 20) / 3.0  # high=30, low=0, close=20
    expected_hlc3_1 = (10 * 100 + hlc3_bar1 * 200) / (100 + 200)

    assert close_result.iloc[1] == pytest.approx(expected_close_1)
    assert hlc3_result.iloc[1] == pytest.approx(expected_hlc3_1)
    assert close_result.iloc[1] != pytest.approx(hlc3_result.iloc[1])


# ---------------------------------------------------------------------------
# M2/M3: anchor discovery (tests 6-9) -- dedup, caps, staleness
# ---------------------------------------------------------------------------

def _flat_bars(n: int, start: str = "2020-01-01", price: float = 100.0, half_range: float = 0.5) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"open": price, "high": price + half_range, "low": price - half_range, "close": price, "volume": 1000.0},
        index=idx,
    )


def _config(**overrides) -> AvwapConfig:
    # cycle_scale_mult effectively infinite -- disables cycle-pivot
    # discovery entirely, so tests 6/9 that only care about ath/atl/52w
    # aren't at the mercy of incidental cycle pivots forming in a short
    # synthetic series.
    defaults = dict(warmup_bars=0, cycle_scale_mult=1.0e9, trailing_window_bars={"daily": 5, "weekly": 52})
    defaults.update(overrides)
    return AvwapConfig(**defaults)


def test_single_high_and_low_produce_correct_ath_atl_anchors():
    bars = _flat_bars(40)
    ath_date = bars.index[5]
    atl_date = bars.index[10]
    bars.loc[ath_date, "high"] = 1000.0
    bars.loc[atl_date, "low"] = 1.0
    config = _config()  # 52w window (5 bars) is far from bars 5/10 in a 40-bar series

    anchors = discover_anchor_dates(bars, "TEST", Timeframe.DAILY, config)

    ath_anchor = next(a for a in anchors if a.anchor_date == ath_date.isoformat())
    atl_anchor = next(a for a in anchors if a.anchor_date == atl_date.isoformat())
    assert AnchorType.ATH in ath_anchor.anchor_types
    assert AnchorType.ATL in atl_anchor.anchor_types
    assert ath_anchor.status == AnchorStatus.ACTIVE
    assert atl_anchor.status == AnchorStatus.ACTIVE


def _zigzag_swing_bars() -> pd.DataFrame:
    """60 warmup-friendly flat bars (default warmup_bars=50 skips exactly
    into the point ATR(14) is already fully formed) followed by a clean
    50 -> 300 -> 60 -> 70 zigzag: a LOW pivot at the 50 bar (confirmed by
    the swing to 300) and a HIGH pivot at the 300 bar (confirmed by the
    swing back down to 60) -- see market_common/pivots.py's own zigzag test
    for the same plateau-swing construction this borrows from.
    """
    bars = _flat_bars(60)
    swing = pd.DataFrame(
        {
            "open": [50.0, 300.0, 60.0, 70.0],
            "high": [50.5, 300.5, 60.5, 70.5],
            "low": [49.5, 299.5, 59.5, 69.5],
            "close": [50.0, 300.0, 60.0, 70.0],
            "volume": [1000.0] * 4,
        },
        index=pd.bdate_range(bars.index[-1] + pd.Timedelta(days=1), periods=4),
    )
    return pd.concat([bars, swing])


def test_same_date_ath_and_recent_cycle_high_collapse_into_one_anchor_row():
    bars = _zigzag_swing_bars()
    peak_date = bars.index[61]  # the close=300.0 bar -- both global ATH and the cycle high
    assert bars.loc[peak_date, "close"] == 300.0

    config = _config(
        warmup_bars=50, cycle_scale_mult=8.0, trailing_window_bars={"daily": 2, "weekly": 52},
    )

    anchors = discover_anchor_dates(bars, "TEST", Timeframe.DAILY, config)

    matches = [a for a in anchors if a.anchor_date == peak_date.isoformat()]
    assert len(matches) == 1
    assert matches[0].anchor_types == frozenset({AnchorType.ATH, AnchorType.CYCLE_HIGH})


def test_cap_trims_oldest_pure_cycle_anchors_first_and_never_protected_ones():
    bars = _flat_bars(60)
    bars.loc[bars.index[10], "high"] = 5000.0  # global ATH, well outside the swings below
    bars.loc[bars.index[20], "low"] = -500.0   # global ATL

    # Wilder ATR compounds fast after each big swing, so cycle_scale_mult
    # has to stay small here for later swings to still clear their (now
    # elevated) reversal threshold -- verified directly against
    # market_common.pivots.detect_pivots before writing this fixture, not
    # hand-derived.
    swing_closes = [50.0, 300.0, 60.0, 280.0, 70.0, 260.0]
    swing = pd.DataFrame(
        {
            "open": swing_closes,
            "high": [c + 0.5 for c in swing_closes],
            "low": [c - 0.5 for c in swing_closes],
            "close": swing_closes,
            "volume": [1000.0] * len(swing_closes),
        },
        index=pd.bdate_range(bars.index[-1] + pd.Timedelta(days=1), periods=len(swing_closes)),
    )
    bars = pd.concat([bars, swing])

    config_uncapped = _config(
        warmup_bars=50, cycle_scale_mult=1.0, max_cycle_anchors=6, max_anchors_total=1000,
        trailing_window_bars={"daily": 252, "weekly": 52},  # whole series -> 52w collapses onto ath/atl
    )
    uncapped = discover_anchor_dates(bars, "TEST", Timeframe.DAILY, config_uncapped)
    pure_cycle_dates = sorted(a.anchor_date for a in uncapped if is_pure_cycle(a.anchor_types))
    protected_dates = {a.anchor_date for a in uncapped if not is_pure_cycle(a.anchor_types)}

    assert len(pure_cycle_dates) == 6  # matches max_cycle_anchors -- confirms the fixture as designed
    assert bars.index[10].isoformat() in protected_dates
    assert bars.index[20].isoformat() in protected_dates

    config_capped = _config(
        warmup_bars=50, cycle_scale_mult=1.0, max_cycle_anchors=6, max_anchors_total=5,
        trailing_window_bars={"daily": 252, "weekly": 52},
    )
    capped = discover_anchor_dates(bars, "TEST", Timeframe.DAILY, config_capped)
    # Exceeding the cap demotes the oldest pure-cycle anchors to stale rather
    # than deleting them outright -- every anchor discovered this run is
    # still returned (and so still gets its current_value/updated_through
    # refreshed by detect() below), just not all of them ACTIVE.
    active_dates = {a.anchor_date for a in capped if a.status == AnchorStatus.ACTIVE}
    stale_dates = {a.anchor_date for a in capped if a.status == AnchorStatus.STALE}

    assert len(capped) == len(uncapped)
    assert len(active_dates) == 5
    assert stale_dates == set(pure_cycle_dates[:3])   # oldest 3 demoted to stale
    assert set(pure_cycle_dates[3:]) <= active_dates  # newest 3 still active
    assert protected_dates <= active_dates            # never trimmed


def test_52w_low_anchor_goes_stale_then_reactivates():
    bars = _flat_bars(20)
    bars.loc[bars.index[0], "high"] = 200.0   # ATH, well away from the 52w window
    bars.loc[bars.index[1], "low"] = 1.0      # ATL, well away from the 52w window
    x_date = bars.index[18]
    bars.loc[x_date, "low"] = 50.0            # the only low inside the trailing window

    config = _config(trailing_window_bars={"daily": 5, "weekly": 52})

    anchors_1 = discover_anchor_dates(bars, "TEST", Timeframe.DAILY, config)
    anchor_x_1 = next(a for a in anchors_1 if a.anchor_date == x_date.isoformat())
    assert anchor_x_1.anchor_types == frozenset({AnchorType.WEEK_52_LOW})
    assert anchor_x_1.status == AnchorStatus.ACTIVE

    previous_after_1 = {a.anchor_date: a.anchor_types for a in anchors_1}

    # Extend past X with new bars whose lower low pushes X out of the
    # trailing window entirely -- X holds no other role, so it should go
    # stale, not disappear.
    extra_idx = pd.bdate_range(bars.index[-1] + pd.Timedelta(days=1), periods=6)
    extra = pd.DataFrame(
        {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0}, index=extra_idx
    )
    y_date = extra_idx[-1]
    extra.loc[y_date, "low"] = 10.0
    bars_extended = pd.concat([bars, extra])

    anchors_2 = discover_anchor_dates(
        bars_extended, "TEST", Timeframe.DAILY, config, previous_anchor_types=previous_after_1
    )
    anchor_x_2 = next(a for a in anchors_2 if a.anchor_date == x_date.isoformat())
    assert anchor_x_2.status == AnchorStatus.STALE
    assert anchor_x_2.anchor_types == frozenset({AnchorType.WEEK_52_LOW})  # preserved, not cleared

    anchor_y_2 = next(a for a in anchors_2 if a.anchor_date == y_date.isoformat())
    assert anchor_y_2.status == AnchorStatus.ACTIVE
    assert AnchorType.WEEK_52_LOW in anchor_y_2.anchor_types

    # Re-running against the original (unextended) window with anchors_2's
    # stale state as "previous" -- X's role legitimately re-qualifies, so
    # it must flip back to active, anchor_types recomputed fresh.
    previous_after_2 = {a.anchor_date: a.anchor_types for a in anchors_2}
    anchors_3 = discover_anchor_dates(
        bars, "TEST", Timeframe.DAILY, config, previous_anchor_types=previous_after_2
    )
    anchor_x_3 = next(a for a in anchors_3 if a.anchor_date == x_date.isoformat())
    assert anchor_x_3.status == AnchorStatus.ACTIVE
    assert anchor_x_3.anchor_types == frozenset({AnchorType.WEEK_52_LOW})

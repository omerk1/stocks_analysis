import numpy as np
import pandas as pd
import pytest

from src.signals.volume_profile.compute import (
    build_profile, distribute_uniform_hl, row_edges, value_area_rows,
)


def _bars(rows, start="2020-01-01"):
    """rows: list of (open, high, low, close, volume)"""
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def test_single_bar_spreads_volume_evenly_and_ties_resolve_to_central_lower_row():
    bars = _bars([(10.0, 20.0, 10.0, 15.0, 1000.0)])
    p = build_profile(bars, bars.index[0], row_count=10)

    np.testing.assert_allclose(p.edges, np.arange(10.0, 21.0))
    np.testing.assert_allclose(p.up, np.full(10, 100.0))
    np.testing.assert_allclose(p.down, np.zeros(10))
    # Every row tied at 100; mids 14.5 and 15.5 are equidistant from the
    # profile's VWAP (15) -> the lower one.
    assert p.poc_row == 4
    assert p.poc == pytest.approx(14.5)
    # Value area: 100 -> equal pairs above/below added together (+400 ->
    # 500) -> equal again (+400 -> 900 >= 700). Rows 0..8.
    assert (p.va_low_row, p.va_high_row) == (0, 8)
    assert p.val == pytest.approx(10.0)
    assert p.vah == pytest.approx(19.0)
    assert p.n_bars == 1


def test_two_overlapping_bars_hand_computed():
    # Bar 1: 10-12, 100 vol, up (close 11 >= open 10) -> 50 in rows 10-11, 11-12.
    # Bar 2: 11-14, 300 vol, down (close 11.5 < open 12) -> 100 in each of
    # rows 11-12, 12-13, 13-14.
    bars = _bars([(10.0, 12.0, 10.0, 11.0, 100.0), (12.0, 14.0, 11.0, 11.5, 300.0)])
    p = build_profile(bars, bars.index[0], row_count=4)

    np.testing.assert_allclose(p.edges, [10.0, 11.0, 12.0, 13.0, 14.0])
    np.testing.assert_allclose(p.up, [50.0, 50.0, 0.0, 0.0])
    np.testing.assert_allclose(p.down, [0.0, 100.0, 100.0, 100.0])
    assert p.poc_row == 1 and p.poc == pytest.approx(11.5)
    # target 280: 150 -> pair above (200) beats row below (50) -> 350.
    assert (p.val, p.vah) == (pytest.approx(11.0), pytest.approx(14.0))


def test_value_area_adds_the_larger_adjacent_pair_until_target():
    total = np.array([1.0, 5.0, 2.0, 10.0, 3.0, 1.0, 8.0])
    # target 0.7*30 = 21. From POC row 3 (10): below pair 5+2=7 beats above
    # pair 3+1=4 -> 17, lo=1. Then above pair 4 beats below row 1 -> 21, stop.
    assert value_area_rows(total, 3, 0.70) == (1, 5)


def test_value_area_stops_at_profile_edges():
    total = np.array([10.0, 1.0, 1.0])
    assert value_area_rows(total, 0, 0.99) == (0, 2)


def test_poc_tie_between_non_adjacent_rows_goes_to_the_one_nearer_vwap():
    # Two equal spikes of volume at rows spanning 10-11 and 13-14, with a
    # small extra bar pulling VWAP toward the upper one.
    bars = _bars([
        (10.0, 11.0, 10.0, 10.5, 100.0),
        (13.0, 14.0, 13.0, 13.5, 100.0),
        (12.0, 12.9, 12.1, 12.5, 0.0),
    ])
    p = build_profile(bars, bars.index[0], row_count=4)
    assert p.total[0] == pytest.approx(p.total[3])
    # VWAP of the profile = (10.5*100 + 13.5*100)/200 = 12.0: equidistant ->
    # lower row. Add volume on the upper side and the tie-break flips.
    assert p.poc_row == 0
    bars.iloc[2, bars.columns.get_loc("volume")] = 1.0
    p2 = build_profile(bars, bars.index[0], row_count=4)
    assert p2.total[0] == pytest.approx(p2.total[3])
    assert p2.poc_row == 3


def test_zero_range_bar_lands_in_one_row_including_on_the_top_edge():
    edges = np.array([10.0, 11.0, 12.0])
    w = distribute_uniform_hl(np.array([11.0, 12.0, 10.0]), np.array([11.0, 12.0, 10.0]), edges)
    # Interior edge -> upper row; top edge -> last row; bottom edge -> first.
    np.testing.assert_allclose(w, [[0.0, 1.0], [0.0, 1.0], [1.0, 0.0]])


def test_flat_window_gets_a_padded_grid_not_a_division_by_zero():
    bars = _bars([(5.0, 5.0, 5.0, 5.0, 10.0), (5.0, 5.0, 5.0, 5.0, 20.0)])
    p = build_profile(bars, bars.index[0], row_count=3)
    assert p.total.sum() == pytest.approx(30.0)
    assert p.val <= 5.0 <= p.vah


def test_log_rows_have_equal_ratios_and_volume_is_spread_uniformly_in_price():
    edges = row_edges(1.0, 100.0, 2, "log")
    np.testing.assert_allclose(edges, [1.0, 10.0, 100.0])
    bars = _bars([(1.0, 100.0, 1.0, 50.0, 99.0)])
    log_p = build_profile(bars, bars.index[0], row_count=2, row_scale="log")
    lin_p = build_profile(bars, bars.index[0], row_count=2, row_scale="linear")
    # Uniform in *price*: the 1-10 row holds 9/99 of the range, 10-100 holds 90/99.
    np.testing.assert_allclose(log_p.total, [9.0, 90.0])
    np.testing.assert_allclose(lin_p.total, [49.5, 49.5])
    # Log row mid is geometric.
    assert log_p.mids[1] == pytest.approx(np.sqrt(1000.0))


def test_log_rows_reject_non_positive_prices():
    with pytest.raises(ValueError):
        row_edges(0.0, 10.0, 5, "log")


def test_bars_before_anchor_are_ignored():
    bars = _bars([
        (50.0, 60.0, 50.0, 55.0, 1_000_000.0),  # huge pre-anchor volume elsewhere
        (10.0, 20.0, 10.0, 15.0, 1000.0),
    ])
    with_pre = build_profile(bars, bars.index[1], row_count=10)
    only_post = build_profile(bars.iloc[1:], bars.index[1], row_count=10)
    np.testing.assert_allclose(with_pre.edges, only_post.edges)
    np.testing.assert_allclose(with_pre.total, only_post.total)
    assert with_pre.n_bars == 1


def test_up_down_split_by_close_vs_open():
    bars = _bars([
        (10.0, 12.0, 10.0, 12.0, 100.0),  # up
        (12.0, 12.0, 10.0, 12.0, 50.0),   # close == open -> up
        (12.0, 12.0, 10.0, 10.0, 30.0),   # down
    ])
    p = build_profile(bars, bars.index[0], row_count=2)
    assert p.up.sum() == pytest.approx(150.0)
    assert p.down.sum() == pytest.approx(30.0)


def test_no_bars_or_no_volume_returns_none():
    bars = _bars([(10.0, 11.0, 9.0, 10.0, 0.0)])
    assert build_profile(bars, bars.index[0]) is None
    assert build_profile(bars, "2030-01-01") is None


def test_unknown_distribution_or_scale_raises():
    bars = _bars([(10.0, 11.0, 9.0, 10.0, 1.0)])
    with pytest.raises(ValueError):
        build_profile(bars, bars.index[0], volume_distribution="tick")
    with pytest.raises(ValueError):
        build_profile(bars, bars.index[0], row_scale="sqrt")


def test_hourly_bars_on_the_anchor_date_are_included():
    idx = pd.to_datetime(["2020-01-02 14:30", "2020-01-02 15:30", "2020-01-03 14:30"])
    bars = pd.DataFrame(
        {"open": 10.0, "high": 11.0, "low": 10.0, "close": 10.5, "volume": [1.0, 2.0, 3.0]}, index=idx,
    )
    p = build_profile(bars, "2020-01-02", row_count=2)
    assert p.n_bars == 3
    assert p.total.sum() == pytest.approx(6.0)

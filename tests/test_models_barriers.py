import numpy as np
import pandas as pd
import pytest

from src.models.labels.barriers import LONG, SHORT, BarrierCell, barrier_labels, v1_grid

WARMUP = 30  # flat bars, true range 1.0 -> ATR(14) = 1.0
CELL = BarrierCell(horizon=5, upper=2.0, lower=1.0)


def _bars(path, ticker="AAA", start="2020-01-01"):
    """WARMUP flat bars at 100 (high 100.5 / low 99.5), then `path` as
    (open, high, low, close) tuples. The decision row is the last warm-up bar;
    entry is the first path bar's open."""
    rows = [(100.0, 100.5, 99.5, 100.0)] * WARMUP + list(path)
    days = pd.bdate_range(start, periods=len(rows))
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"ticker": ticker, "date": days, "open": o, "high": h, "low": l, "close": c})


def _decision(labels, bars):
    return labels[labels["date"] == bars["date"].iloc[WARMUP - 1]].iloc[0]


def _flat(n):
    return [(100.0, 100.4, 99.6, 100.0)] * n


def test_atr_is_the_one_known_at_the_decision_close():
    bars = _bars(_flat(10))
    row = _decision(barrier_labels(bars, [CELL]), bars)
    assert row["atr"] == pytest.approx(1.0)
    # A huge bar right after the decision must not leak into its ATR.
    wild = _bars([(100.0, 150.0, 50.0, 100.0)] + _flat(9))
    assert _decision(barrier_labels(wild, [CELL]), wild)["atr"] == pytest.approx(1.0)


def test_target_first():
    bars = _bars([(100.0, 100.4, 99.6, 100.0), (100.0, 102.5, 99.8, 102.2)] + _flat(8))
    row = _decision(barrier_labels(bars, [CELL]), bars)
    assert (row["hit"], row["hit_day"]) == (1, 2)
    assert row["exit_price"] == pytest.approx(102.0)
    assert row["ret"] == pytest.approx(0.02)
    assert not row["tie"]


def test_stop_first():
    bars = _bars([(100.0, 100.4, 98.8, 99.0)] + _flat(9))
    row = _decision(barrier_labels(bars, [CELL]), bars)
    assert (row["hit"], row["hit_day"]) == (-1, 1)
    assert row["exit_price"] == pytest.approx(99.0)


def test_same_bar_tie_counts_as_the_stop():
    bars = _bars([(100.0, 102.5, 98.8, 101.0)] + _flat(9))
    row = _decision(barrier_labels(bars, [CELL]), bars)
    assert row["hit"] == -1 and row["tie"]


def test_gap_through_the_stop_fills_at_the_open():
    bars = _bars([(100.0, 100.4, 99.6, 100.0), (97.5, 97.8, 97.0, 97.2)] + _flat(8))
    row = _decision(barrier_labels(bars, [CELL]), bars)
    assert row["hit"] == -1
    assert row["exit_price"] == pytest.approx(97.5)
    assert row["ret"] == pytest.approx(-0.025)


def test_gap_through_the_target_fills_at_the_open_even_if_the_bar_also_reaches_the_stop():
    bars = _bars([(100.0, 100.4, 99.6, 100.0), (103.0, 103.5, 98.5, 99.0)] + _flat(8))
    row = _decision(barrier_labels(bars, [CELL]), bars)
    assert row["hit"] == 1 and not row["tie"]
    assert row["exit_price"] == pytest.approx(103.0)


def test_neither_barrier_exits_at_the_close_of_the_horizon():
    path = [(100.0, 100.4, 99.6, 100.1), (100.1, 100.5, 99.7, 100.2), (100.2, 100.6, 99.8, 100.3),
            (100.3, 100.7, 99.9, 100.4), (100.4, 100.8, 100.0, 100.5)] + _flat(5)
    bars = _bars(path)
    row = _decision(barrier_labels(bars, [CELL]), bars)
    assert row["hit"] == 0 and np.isnan(row["hit_day"])
    assert row["exit_price"] == pytest.approx(100.5)
    assert row["label_end_date"] == bars["date"].iloc[WARMUP - 1 + 5]


def test_short_side_mirrors_the_barriers():
    bars = _bars([(100.0, 100.4, 97.8, 98.0)] + _flat(9))
    row = _decision(barrier_labels(bars, [CELL], side=SHORT), bars)
    assert row["hit"] == 1
    assert row["exit_price"] == pytest.approx(98.0)
    assert row["ret"] == pytest.approx(0.02)
    stop = _bars([(100.0, 101.2, 99.8, 101.0)] + _flat(9))
    assert _decision(barrier_labels(stop, [CELL], side=SHORT), stop)["hit"] == -1


def test_mfe_and_mae_cover_the_whole_horizon_in_atr_units():
    bars = _bars([(100.0, 101.5, 99.6, 101.0), (101.0, 101.2, 99.2, 99.5)] + _flat(8))
    row = _decision(barrier_labels(bars, [CELL]), bars)
    assert row["mfe_atr"] == pytest.approx(1.5)
    assert row["mae_atr"] == pytest.approx(0.8)


def test_window_past_the_dataset_end_is_nan_even_if_a_barrier_was_already_hit():
    bars = _bars([(100.0, 102.5, 99.8, 102.2), (102.0, 102.2, 101.8, 102.0)])
    row = _decision(barrier_labels(bars, [CELL]), bars)
    assert np.isnan(row["hit"]) and pd.isna(row["label_end_date"])


def test_a_ticker_that_ends_before_the_dataset_resolves_on_its_last_bar():
    early = _bars([(100.0, 100.4, 99.6, 100.0), (100.0, 100.3, 99.7, 99.9)], ticker="GONE")
    other = _bars(_flat(20), ticker="STAY")
    labels = barrier_labels(pd.concat([early, other]), [CELL])
    row = _decision(labels[labels["ticker"] == "GONE"], early)
    assert row["hit"] == 0 and row["truncated"]
    assert row["exit_price"] == pytest.approx(99.9)
    assert row["label_end_date"] == early["date"].iloc[-1]


def test_rows_before_atr_warmup_are_nan():
    bars = _bars(_flat(10))
    labels = barrier_labels(bars, [CELL])
    assert labels.iloc[:5]["hit"].isna().all()


def test_bars_after_data_end_are_refused():
    bars = _bars(_flat(10))
    with pytest.raises(ValueError, match="data_end"):
        barrier_labels(bars, [CELL], data_end=bars["date"].iloc[20])


def test_v1_grid_is_the_designed_45_cells():
    grid = v1_grid()
    assert len(grid) == 45
    assert {c.horizon for c in grid} == {5, 10, 21, 42, 63}


def test_a_non_trading_data_end_does_not_make_live_tickers_look_delisted():
    # data_end on a Saturday: every ticker's last bar is before it, but none ended.
    bars = pd.concat([_bars(_flat(20), ticker="AAA"), _bars(_flat(20), ticker="BBB")])
    last = bars["date"].max()
    saturday = last + pd.Timedelta(days=(5 - last.dayofweek) % 7 or 7)
    assert saturday.dayofweek == 5
    labels = barrier_labels(bars, [CELL], data_end=saturday)
    tail = labels.groupby("ticker").tail(CELL.horizon)
    assert tail["hit"].isna().all() and not tail["truncated"].any()


def test_a_ticker_missing_only_its_last_sessions_is_not_treated_as_delisted():
    live = _bars(_flat(20), ticker="AAA")
    gappy = _bars(_flat(18), ticker="BBB")  # last 2 sessions missing, within DELISTING_GAP
    labels = barrier_labels(pd.concat([live, gappy]), [CELL])
    assert not labels["truncated"].any()


def test_non_iso_date_strings_are_ordered_by_date_not_text():
    bars = _bars([(100.0, 102.5, 99.8, 102.2)] + _flat(9))
    as_text = bars.assign(date=bars["date"].dt.strftime("%-m/%-d/%Y")).sample(frac=1, random_state=0)
    expected = barrier_labels(bars, [CELL]).dropna(subset=["hit"]).reset_index(drop=True)
    got = barrier_labels(as_text, [CELL]).dropna(subset=["hit"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(got, expected)


def test_calendar_lets_a_chunk_of_early_ending_tickers_resolve_as_delisted():
    # Labeled alone, a ticker that stopped trading looks like the dataset's end:
    # its last windows are NaN. Given the full calendar, they resolve as truncated.
    bars = _bars(_flat(3))
    decision = bars["date"].iloc[WARMUP - 1]
    alone = _decision(barrier_labels(bars, [CELL]), bars)
    assert np.isnan(alone["hit"])
    calendar = pd.bdate_range(bars["date"].iloc[0], periods=len(bars) + 40)
    full = barrier_labels(bars, [CELL], data_end=calendar[-1], calendar=calendar)
    row = full[full["date"] == decision].iloc[0]
    assert row["truncated"] and row["hit"] == 0

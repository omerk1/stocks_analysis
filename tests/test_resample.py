import numpy as np
import pandas as pd

from src.foundation.data_processing.resample import to_monthly, to_weekly


def _daily(rows):
    """rows: list of (date_str, open, high, low, close, volume[, is_partial])"""
    records = []
    for row in rows:
        date_str, o, h, l, c, v = row[:6]
        is_partial = row[6] if len(row) > 6 else 0
        records.append((date_str, o, h, l, c, v, is_partial))
    df = pd.DataFrame(
        records, columns=["timestamp", "open", "high", "low", "close", "volume", "is_partial"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def test_empty_input_returns_empty_with_columns():
    result = to_weekly(_daily([]).iloc[0:0])
    assert result.empty
    assert list(result.columns) == ["open", "high", "low", "close", "volume", "is_partial"]


def test_complete_week_aggregates_ohlcv_and_is_not_partial():
    # Mon 2024-01-01 .. Fri 2024-01-05
    daily = _daily(
        [
            ("2024-01-01", 100, 105, 99, 102, 1000),
            ("2024-01-02", 102, 103, 98, 99, 1100),
            ("2024-01-03", 99, 110, 97, 108, 1200),
            ("2024-01-04", 108, 109, 104, 106, 1300),
            ("2024-01-05", 106, 107, 100, 101, 1400),
        ]
    )

    result = to_weekly(daily, as_of="2024-02-01")

    assert len(result) == 1
    row = result.iloc[0]
    assert result.index[0] == pd.Timestamp("2024-01-01")  # labeled by week start (Monday)
    assert row["open"] == 100  # Monday's open
    assert row["close"] == 101  # Friday's close
    assert row["high"] == 110
    assert row["low"] == 97
    assert row["volume"] == 1000 + 1100 + 1200 + 1300 + 1400
    assert row["is_partial"] == 0


def test_in_progress_week_is_flagged_partial():
    daily = _daily(
        [
            ("2024-01-01", 100, 105, 99, 102, 1000),
            ("2024-01-02", 102, 103, 98, 99, 1100),
        ]
    )

    result = to_weekly(daily, as_of="2024-01-02")

    assert result.iloc[0]["is_partial"] == 1


def test_week_is_closed_the_saturday_right_after_friday():
    # Regression guard: a week shouldn't need to wait until the *next* Monday
    # to be considered closed -- Saturday (the day after the last trading day)
    # is enough, since W-SUN's nominal end is Sunday but no trading happens Sat/Sun.
    daily = _daily(
        [
            ("2024-01-01", 100, 105, 99, 102, 1000),
            ("2024-01-02", 102, 103, 98, 99, 1100),
            ("2024-01-03", 99, 110, 97, 108, 1200),
            ("2024-01-04", 108, 109, 104, 106, 1300),
            ("2024-01-05", 106, 107, 100, 101, 1400),
        ]
    )

    result = to_weekly(daily, as_of="2024-01-06")  # Saturday

    assert result.iloc[0]["is_partial"] == 0


def test_period_label_is_stable_as_more_days_arrive():
    # Guards against the bug where labeling by "last seen day" would shift the
    # row's primary key as new days are appended to a still-open period,
    # leaving stale duplicate rows instead of updating in place.
    first_run = _daily(
        [
            ("2024-01-01", 100, 105, 99, 102, 1000),
            ("2024-01-02", 102, 103, 98, 99, 1100),
        ]
    )
    second_run = _daily(
        [
            ("2024-01-01", 100, 105, 99, 102, 1000),
            ("2024-01-02", 102, 103, 98, 99, 1100),
            ("2024-01-03", 99, 110, 97, 108, 1200),
        ]
    )

    label_1 = to_weekly(first_run, as_of="2024-01-02").index[0]
    label_2 = to_weekly(second_run, as_of="2024-01-03").index[0]

    assert label_1 == label_2 == pd.Timestamp("2024-01-01")


def test_is_partial_propagates_from_constituent_daily_bar():
    # Even though the calendar week is over, one of its daily bars is itself
    # still marked partial (e.g. a same-day fetch quirk) -- the weekly bar
    # should inherit that.
    daily = _daily(
        [
            ("2024-01-01", 100, 105, 99, 102, 1000),
            ("2024-01-02", 102, 103, 98, 99, 1100),
            ("2024-01-03", 99, 110, 97, 108, 1200),
            ("2024-01-04", 108, 109, 104, 106, 1300),
            ("2024-01-05", 106, 107, 100, 101, 1400, 1),  # still marked partial
        ]
    )

    result = to_weekly(daily, as_of="2024-02-01")

    assert result.iloc[0]["is_partial"] == 1


def test_volume_sum_ignores_nan_but_all_nan_stays_nan():
    daily = _daily(
        [
            ("2024-01-01", 100, 105, 99, 102, 1000),
            ("2024-01-02", 102, 103, 98, 99, np.nan),
        ]
    )
    result = to_weekly(daily, as_of="2024-02-01")
    assert result.iloc[0]["volume"] == 1000

    all_nan_daily = _daily(
        [
            ("2024-01-01", 100, 105, 99, 102, np.nan),
        ]
    )
    result_all_nan = to_weekly(all_nan_daily, as_of="2024-02-01")
    assert pd.isna(result_all_nan.iloc[0]["volume"])


def test_monthly_aggregates_full_month():
    daily = _daily(
        [
            ("2024-01-02", 100, 105, 99, 102, 1000),
            ("2024-01-15", 102, 120, 98, 115, 1100),
            ("2024-01-31", 115, 116, 110, 112, 1200),
        ]
    )

    result = to_monthly(daily, as_of="2024-03-01")

    assert result.index[0] == pd.Timestamp("2024-01-01")
    row = result.iloc[0]
    assert row["open"] == 100
    assert row["close"] == 112
    assert row["high"] == 120
    assert row["low"] == 98
    assert row["is_partial"] == 0


def test_monthly_in_progress_is_flagged_partial():
    daily = _daily([("2024-01-02", 100, 105, 99, 102, 1000)])
    result = to_monthly(daily, as_of="2024-01-15")
    assert result.iloc[0]["is_partial"] == 1

import pandas as pd

from src.foundation.market_common.macro import as_of_join


def _macro(rows):
    """rows: list of (date, value, published_at, first_published_value)"""
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "value": [r[1] for r in rows],
            "published_at": [r[2] for r in rows],
            "first_published_value": [r[3] for r in rows],
        }
    )


def test_forward_fills_between_publications():
    macro = _macro(
        [
            ("2020-01-01", 1.0, "2020-01-05", 10.0),
            ("2020-02-01", 2.0, "2020-02-05", 20.0),
        ]
    )
    bar_dates = pd.to_datetime(["2020-01-05", "2020-01-20", "2020-02-04", "2020-02-05", "2020-03-01"])

    result = as_of_join(bar_dates, macro)

    assert list(result) == [10.0, 10.0, 10.0, 20.0, 20.0]


def test_no_value_before_the_first_publication():
    # The whole point: even though the first row's *period* (date) is
    # 2020-01-01, it wasn't actually known until 2020-01-05 -- a bar dated
    # before that must not see it.
    macro = _macro([("2020-01-01", 1.0, "2020-01-05", 10.0)])
    bar_dates = pd.to_datetime(["2019-12-31", "2020-01-01", "2020-01-04", "2020-01-05"])

    result = as_of_join(bar_dates, macro)

    assert result.iloc[:3].isna().all()
    assert result.iloc[3] == 10.0


def test_a_later_period_never_leaks_before_its_own_publication_date():
    # A period's own `date` is later than another period's `published_at`
    # here -- must still only apply from its own publication date, not from
    # its period-label date (which would be a look-ahead leak).
    macro = _macro(
        [
            ("2020-01-01", 1.0, "2020-03-01", 10.0),  # published late (delayed catch-up)
            ("2020-02-01", 2.0, "2020-02-10", 20.0),  # published on time, sooner than the above
        ]
    )
    bar_dates = pd.to_datetime(["2020-02-15", "2020-03-01"])

    result = as_of_join(bar_dates, macro)

    # 2020-02-15: only the Feb-published (2020-02-10) value is knowable yet.
    assert result.iloc[0] == 20.0
    # 2020-03-01: the delayed Jan-period value (published_at) now overtakes it.
    assert result.iloc[1] == 10.0


def test_same_day_published_series_behaves_like_a_plain_reindex_ffill():
    macro = _macro(
        [
            ("2020-01-01", 1.0, "2020-01-01", 1.0),
            ("2020-01-02", 2.0, "2020-01-02", 2.0),
            ("2020-01-03", 3.0, "2020-01-03", 3.0),
        ]
    )
    bar_dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])

    result = as_of_join(bar_dates, macro)

    assert list(result) == [1.0, 2.0, 3.0]


def test_rows_with_no_published_at_are_dropped_not_joined():
    macro = _macro(
        [
            ("2020-01-01", 1.0, None, 1.0),
            ("2020-02-01", 2.0, "2020-02-05", 20.0),
        ]
    )
    bar_dates = pd.to_datetime(["2020-01-15", "2020-02-10"])

    result = as_of_join(bar_dates, macro)

    assert result.iloc[0] is None or pd.isna(result.iloc[0])
    assert result.iloc[1] == 20.0


def test_a_tie_in_published_at_keeps_the_later_periods_value():
    macro = _macro(
        [
            ("2020-01-01", 1.0, "2020-03-01", 10.0),
            ("2020-02-01", 2.0, "2020-03-01", 20.0),  # same publication day, later period
        ]
    )
    bar_dates = pd.to_datetime(["2020-03-01"])

    result = as_of_join(bar_dates, macro)

    assert result.iloc[0] == 20.0


def test_empty_macro_frame_returns_all_nan():
    macro = _macro([])
    bar_dates = pd.to_datetime(["2020-01-01", "2020-01-02"])

    result = as_of_join(bar_dates, macro)

    assert result.isna().all()
    assert list(result.index) == list(bar_dates)


def test_result_preserves_original_bar_date_order():
    # bar_dates handed in out of order must come back out in the same order.
    macro = _macro([("2020-01-01", 1.0, "2020-01-01", 10.0)])
    bar_dates = pd.to_datetime(["2020-01-05", "2020-01-01", "2020-01-03"])

    result = as_of_join(bar_dates, macro)

    assert list(result.index) == list(bar_dates)
    assert list(result) == [10.0, 10.0, 10.0]

import pandas as pd
import pytest

from src.data_processing import db
from src.data_processing.market_cap import (
    detect_split_events,
    historical_market_cap,
    reconcile_market_cap,
)


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _dates(strs):
    return pd.to_datetime(strs)


def _bars(dates, closes):
    df = pd.DataFrame(
        {
            "timestamp": _dates(dates),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000] * len(dates),
            "is_partial": [0] * len(dates),
        }
    ).set_index("timestamp")
    return df


def test_reconcile_market_cap_hand_computed_across_a_4_for_1_split():
    # Ground truth: real_price/real_shares/real_market_cap per day, with a
    # real 4-for-1 split between day 3 and day 4 (values chosen to differ
    # day-to-day so a multiply-vs-divide direction bug can't accidentally
    # cancel out and pass by symmetry).
    #   day1: 800 x 100   = 80,000
    #   day2: 820 x 100   = 82,000
    #   day3: 840 x 100   = 84,000
    #   [4-for-1 split]
    #   day4: 215 x 400   = 86,000   (215 == 860/4)
    #   day5: 220 x 400   = 88,000
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]

    # bars_1d stores the split-adjusted price: real_price / cumulative_ratio.
    # Pre-split days are divided by 4 (one split still ahead of them);
    # post-split days aren't divided at all (no further splits ahead).
    adjusted_prices = pd.Series([200.0, 205.0, 210.0, 215.0, 220.0], index=_dates(dates))

    # shares_outstanding stores the raw, un-rescaled count that actually
    # existed on each date.
    raw_shares = pd.Series([100, 100, 100, 400, 400], index=_dates(dates))

    result = reconcile_market_cap(adjusted_prices, raw_shares)

    expected = pd.Series([80_000.0, 82_000.0, 84_000.0, 86_000.0, 88_000.0], index=_dates(dates))
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False)
    assert list(result["cumulative_split_ratio"]) == pytest.approx([4.0, 4.0, 4.0, 1.0, 1.0])


def test_reconcile_market_cap_reverse_split():
    # 1-for-10 reverse split: real shares divided by 10, real price
    # multiplied by 10, between day1 and day2.
    #   day1: 5 x 10_000_000     = 50,000,000
    #   day2: 52 x 1_000_000     = 52,000,000
    dates = ["2024-01-01", "2024-01-02"]
    # Pre-split day's adjusted price is *multiplied* by 10 (divided by the
    # 0.1 cumulative ratio) to match today's post-reverse-split scale.
    adjusted_prices = pd.Series([50.0, 52.0], index=_dates(dates))
    raw_shares = pd.Series([10_000_000, 1_000_000], index=_dates(dates))

    result = reconcile_market_cap(adjusted_prices, raw_shares)

    expected = pd.Series([50_000_000.0, 52_000_000.0], index=_dates(dates))
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False)
    assert result["cumulative_split_ratio"].iloc[0] == pytest.approx(0.1)
    assert result["cumulative_split_ratio"].iloc[1] == pytest.approx(1.0)


def test_reconcile_market_cap_two_splits_compound():
    # Two splits in sequence (2-for-1, then 3-for-1): a date before both
    # must be scaled by their product (6x), not just the nearer one. Raw
    # shares increase at each split (100 -> 200 -> 600), the opposite
    # direction of the reverse-split test above.
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    adjusted_prices = pd.Series([100.0, 203.0, 210.0], index=_dates(dates))
    raw_shares = pd.Series([100, 200, 600], index=_dates(dates))

    result = reconcile_market_cap(adjusted_prices, raw_shares)

    # day1 real price = 100 * 6 = 600, real shares = 100 -> 60,000
    # day2 real price = 203 * 3 = 609, real shares = 200 -> 121,800
    # day3 real price = 210 * 1 = 210, real shares = 600 -> 126,000
    expected = pd.Series([60_000.0, 121_800.0, 126_000.0], index=_dates(dates))
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False)
    assert list(result["cumulative_split_ratio"]) == pytest.approx([6.0, 3.0, 1.0])


def test_reconcile_market_cap_ignores_organic_share_count_drift():
    # Ordinary buyback-driven share-count decline (well under the split
    # detection threshold) must not be mistaken for a split -- no ratio
    # applied, market cap is just price x shares throughout.
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    adjusted_prices = pd.Series([100.0, 101.0, 102.0], index=_dates(dates))
    raw_shares = pd.Series([1_000_000, 990_000, 980_000], index=_dates(dates))

    result = reconcile_market_cap(adjusted_prices, raw_shares)

    assert (result["cumulative_split_ratio"] == 1.0).all()
    expected = adjusted_prices * raw_shares
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False)


def test_reconcile_market_cap_as_of_fills_sparse_shares_series():
    # shares_outstanding is a sparse, filing-date-only series -- a price
    # date between two filings should use the most recent filing on/before
    # it, not require an exact-date match.
    prices = pd.Series(
        [10.0, 11.0, 12.0, 13.0],
        index=_dates(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
    )
    shares = pd.Series([1000], index=_dates(["2024-01-01"]))

    result = reconcile_market_cap(prices, shares)

    assert (result["shares_outstanding_used"] == 1000).all()
    expected = prices * 1000
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False)


def test_reconcile_market_cap_price_dates_before_first_filing_are_nan():
    prices = pd.Series(
        [10.0, 11.0, 12.0],
        index=_dates(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    shares = pd.Series([1000], index=_dates(["2024-01-03"]))

    result = reconcile_market_cap(prices, shares)

    assert result["market_cap"].iloc[:2].isna().all()
    assert result["market_cap"].iloc[2] == pytest.approx(12_000.0)


def test_reconcile_market_cap_empty_inputs_return_empty_frame():
    empty = pd.Series(dtype="float64")
    result = reconcile_market_cap(empty, empty)

    assert result.empty
    assert list(result.columns) == ["market_cap", "shares_outstanding_used", "cumulative_split_ratio"]


def test_detect_split_events_flags_large_jump_only():
    shares = pd.Series(
        [1_000_000, 990_000, 980_000, 3_920_000],
        index=_dates(["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]),
    )

    events = detect_split_events(shares)

    assert list(events.index) == list(_dates(["2024-04-01"]))
    assert events.iloc[0] == pytest.approx(4.0)


def test_detect_split_events_no_events_when_no_jump():
    shares = pd.Series(
        [1_000_000, 990_000, 985_000],
        index=_dates(["2024-01-01", "2024-02-01", "2024-03-01"]),
    )

    assert detect_split_events(shares).empty


def test_historical_market_cap_reads_from_db_and_reconciles(conn):
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
    # 2-for-1 split between day2 and day3.
    adjusted_closes = [50.0, 51.0, 102.0, 104.0]
    db.upsert_bars(conn, "bars_1d", "TEST", db.POLYGON, _bars(dates, adjusted_closes))

    raw_shares = pd.Series([100, 100, 200, 200], index=_dates(dates), name="shares_outstanding")
    db.upsert_shares_outstanding(conn, "TEST", db.YFINANCE, raw_shares)

    result = historical_market_cap(conn, "TEST", price_source=db.POLYGON, shares_source=db.YFINANCE)

    expected = pd.Series([10_000.0, 10_200.0, 20_400.0, 20_800.0], index=_dates(dates))
    # check_freq=False: db.read_bars' parsed DatetimeIndex carries an
    # inferred freq ("D") that a plain pd.to_datetime(list) index doesn't --
    # a storage-layer artifact, not a value difference.
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False, check_freq=False)


def test_historical_market_cap_empty_when_no_data(conn):
    result = historical_market_cap(conn, "MISSING")
    assert result.empty

from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.data_processing import db
from src.data_processing.market_cap import historical_market_cap, reconcile_market_cap
from src.market_common.indicators import scale_consistent


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


def _splits(dates_ratios):
    """Build a splits DataFrame shaped like `PolygonClient.get_splits`'s
    output (execution_date/ratio at minimum -- split_from/split_to aren't
    consumed by `reconcile_market_cap`, so omitted here for brevity)."""
    dates, ratios = zip(*dates_ratios) if dates_ratios else ((), ())
    return pd.DataFrame({"execution_date": _dates(list(dates)), "ratio": list(ratios)})


def test_reconcile_market_cap_hand_computed_across_a_4_for_1_split():
    # Ground truth: real_price/real_shares/real_market_cap per day, with a
    # real 4-for-1 split between day 3 and day 4 (values chosen to differ
    # day-to-day so a multiply-vs-divide direction bug can't accidentally
    # cancel out and pass by symmetry).
    #   day1: 800 x 100   = 80,000
    #   day2: 820 x 100   = 82,000
    #   day3: 840 x 100   = 84,000
    #   [4-for-1 split, execution_date = day4]
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

    splits = _splits([("2024-01-04", 4.0)])

    result = reconcile_market_cap(adjusted_prices, raw_shares, splits)

    expected = pd.Series([80_000.0, 82_000.0, 84_000.0, 86_000.0, 88_000.0], index=_dates(dates))
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False)
    assert list(result["cumulative_split_ratio"]) == pytest.approx([4.0, 4.0, 4.0, 1.0, 1.0])


def test_reconcile_market_cap_understates_during_a_real_style_filing_lag_window():
    # Documents a known, real caveat (see market_cap.py's module docstring)
    # rather than leaving it as an undocumented landmine: shares_outstanding
    # can carry a filing dated on/after a split's true execution date that
    # still holds the stale pre-split count -- confirmed directly on real
    # AAPL data (the entry literally dated 2020-08-31, AAPL's real split
    # day, still reports the pre-split share count; it doesn't update to
    # the post-split count until an entry dated 2020-10-22). This mirrors
    # that exact pattern: a stale filing dated on the split day itself,
    # and a fresh filing only much later.
    dates = ["2024-01-05", "2024-01-10", "2024-02-01", "2024-03-05"]
    # bars_1d has no such lag -- prices are correctly split-adjusted from
    # the true execution date onward, same as real data.
    prices = pd.Series([50.0, 52.0, 53.0, 54.0], index=_dates(dates))
    # A stale filing dated exactly on the split day (still the pre-split
    # count), then no update until well after -- same shape as real AAPL.
    shares = pd.Series([100, 100, 400], index=_dates(["2024-01-01", "2024-01-10", "2024-03-01"]))
    splits = _splits([("2024-01-10", 4.0)])

    result = reconcile_market_cap(prices, shares, splits)

    # Correct before the split (uses the 2024-01-01 filing, still ahead of
    # the split so cumulative_split_ratio scales it up).
    assert result.loc["2024-01-05", "market_cap"] == pytest.approx(50.0 * 100 * 4)
    # Understated on/after the split, through the lag window: the stale
    # 2024-01-10 filing (100) is used verbatim since no split is left
    # *ahead* of these dates (cumulative_split_ratio is correctly 1.0) --
    # the real count was already 400, so this is 4x too low.
    assert result.loc["2024-01-10", "market_cap"] == pytest.approx(52.0 * 100 * 1)
    assert result.loc["2024-02-01", "market_cap"] == pytest.approx(53.0 * 100 * 1)
    # Correct again once shares_outstanding's own filing catches up.
    assert result.loc["2024-03-05", "market_cap"] == pytest.approx(54.0 * 400 * 1)


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
    splits = _splits([("2024-01-02", 0.1)])

    result = reconcile_market_cap(adjusted_prices, raw_shares, splits)

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
    splits = _splits([("2024-01-02", 2.0), ("2024-01-03", 3.0)])

    result = reconcile_market_cap(adjusted_prices, raw_shares, splits)

    # day1 real price = 100 * 6 = 600, real shares = 100 -> 60,000
    # day2 real price = 203 * 3 = 609, real shares = 200 -> 121,800
    # day3 real price = 210 * 1 = 210, real shares = 600 -> 126,000
    expected = pd.Series([60_000.0, 121_800.0, 126_000.0], index=_dates(dates))
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False)
    assert list(result["cumulative_split_ratio"]) == pytest.approx([6.0, 3.0, 1.0])


def test_reconcile_market_cap_no_splits_is_plain_price_times_shares():
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    adjusted_prices = pd.Series([100.0, 101.0, 102.0], index=_dates(dates))
    raw_shares = pd.Series([1_000_000, 990_000, 980_000], index=_dates(dates))

    result = reconcile_market_cap(adjusted_prices, raw_shares, splits=None)

    assert (result["cumulative_split_ratio"] == 1.0).all()
    expected = adjusted_prices * raw_shares
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False)


def test_reconcile_market_cap_empty_splits_frame_is_plain_price_times_shares():
    dates = ["2024-01-01", "2024-01-02"]
    adjusted_prices = pd.Series([100.0, 101.0], index=_dates(dates))
    raw_shares = pd.Series([1_000_000, 1_000_000], index=_dates(dates))
    empty_splits = pd.DataFrame(columns=["execution_date", "ratio"])

    result = reconcile_market_cap(adjusted_prices, raw_shares, empty_splits)

    assert (result["cumulative_split_ratio"] == 1.0).all()


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


# --- Regression fixture -----------------------------------------------------
#
# market_cap.py used to detect splits statistically from where
# shares_outstanding itself jumps by a large ratio (reusing
# market_common.indicators.scale_consistent at a tighter threshold), rather
# than reading them explicitly from Polygon's splits reference endpoint.
# That approach is no longer shipped in production -- it anchored a split to
# whatever date shares_outstanding's filing lag happened to surface the jump
# on, not the true corporate-action date (real AAPL data: the 2020-08-31
# split's raw share-count jump doesn't show up until 2020-10-22). It's kept
# here only to prove the explicit-split-data path reproduces the exact same
# result the old inferred-data path did on the same validated scenario.


def _events_from_shares_jumps(shares: pd.Series, min_ratio: float = 1.5) -> pd.Series:
    """The old statistical split-inference logic, preserved only as a
    regression-test fixture (see module docstring above)."""
    shares = shares.dropna().sort_index()
    events: dict = {}
    prev_value = None
    for date, value in shares.items():
        if prev_value is not None and not scale_consistent(prev_value, value, max_ratio=min_ratio):
            events[date] = value / prev_value
        prev_value = value
    return pd.Series(events, dtype="float64", name="ratio").rename_axis("execution_date")


def test_explicit_splits_reproduce_the_old_statistical_inference_result():
    # Same 4-for-1 scenario as the hand-computed test above. The old
    # jump-detection logic (over `raw_shares`) and the new explicit-splits
    # path must agree exactly on this previously-validated case.
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    adjusted_prices = pd.Series([200.0, 205.0, 210.0, 215.0, 220.0], index=_dates(dates))
    raw_shares = pd.Series([100, 100, 100, 400, 400], index=_dates(dates))

    inferred_events = _events_from_shares_jumps(raw_shares)
    inferred_splits = inferred_events.reset_index()

    explicit_splits = _splits([("2024-01-04", 4.0)])

    result_inferred = reconcile_market_cap(adjusted_prices, raw_shares, inferred_splits)
    result_explicit = reconcile_market_cap(adjusted_prices, raw_shares, explicit_splits)

    pd.testing.assert_frame_equal(result_inferred, result_explicit)
    expected = pd.Series([80_000.0, 82_000.0, 84_000.0, 86_000.0, 88_000.0], index=_dates(dates))
    pd.testing.assert_series_equal(result_explicit["market_cap"], expected, check_names=False)


def test_historical_market_cap_reads_from_db_and_reconciles(conn):
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
    # 2-for-1 split between day2 and day3.
    adjusted_closes = [50.0, 51.0, 102.0, 104.0]
    db.upsert_bars(conn, "bars_1d", "TEST", db.POLYGON, _bars(dates, adjusted_closes))

    raw_shares = pd.Series([100, 100, 200, 200], index=_dates(dates), name="shares_outstanding")
    db.upsert_shares_outstanding(conn, "TEST", db.YFINANCE, raw_shares)

    polygon_client = MagicMock()
    polygon_client.get_splits.return_value = _splits([("2024-01-03", 2.0)])

    result = historical_market_cap(
        conn, "TEST", polygon_client, price_source=db.POLYGON, shares_source=db.YFINANCE
    )

    expected = pd.Series([10_000.0, 10_200.0, 20_400.0, 20_800.0], index=_dates(dates))
    # check_freq=False: db.read_bars' parsed DatetimeIndex carries an
    # inferred freq ("D") that a plain pd.to_datetime(list) index doesn't --
    # a storage-layer artifact, not a value difference.
    pd.testing.assert_series_equal(result["market_cap"], expected, check_names=False, check_freq=False)
    polygon_client.get_splits.assert_called_once_with("TEST")


def test_historical_market_cap_empty_when_no_data(conn):
    polygon_client = MagicMock()
    polygon_client.get_splits.return_value = _splits([])

    result = historical_market_cap(conn, "MISSING", polygon_client)

    assert result.empty

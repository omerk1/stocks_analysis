import pandas as pd
import pytest

from src.signals.breadth.compute import advance_decline_line, compute_breadth
from src.signals.breadth.config import BreadthConfig
from src.foundation.data_processing import db

_DATES = pd.bdate_range("2020-01-01", periods=10)


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": _DATES, "open": closes, "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes], "close": closes, "volume": [1000] * len(closes),
            "is_partial": [0] * len(closes),
        }
    ).set_index("timestamp")


def _config(**overrides) -> BreadthConfig:
    cfg = BreadthConfig(indices=["test_idx"], sma_periods=(3,), ema_periods=(), price_source=db.YFINANCE)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_pct_above_sma_excludes_warmup_and_matches_hand_computation(conn):
    # AAA rises every day, BBB falls every day, CCC stays flat.
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_bars(conn, "bars_1d", "BBB", db.YFINANCE, _bars([19, 18, 17, 16, 15, 14, 13, 12, 11, 10]))
    db.upsert_bars(conn, "bars_1d", "CCC", db.YFINANCE, _bars([10, 10, 10, 10, 10, 10, 10, 10, 10, 10]))
    membership = pd.DataFrame(
        {"ticker": ["AAA", "BBB", "CCC"], "start_date": [_DATES[0]] * 3, "end_date": [None, None, None]}
    )
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config())

    # SMA(3) needs 3 points -- NaN (dropped from the mean, not counted as
    # "below") for the first 2 days.
    assert result["pct_above_sma3"].iloc[:2].isna().all()
    # Day 3 (2020-01-03): AAA close=12 sma=(10+11+12)/3=11 -> above.
    # BBB close=17 sma=(19+18+17)/3=18 -> below. CCC close=10 sma=10 -> not above (equal).
    assert result["pct_above_sma3"].iloc[2] == pytest.approx(1 / 3)


def test_a_ticker_leaving_the_index_stops_contributing_after_its_end_date(conn):
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_bars(conn, "bars_1d", "BBB", db.YFINANCE, _bars([19, 18, 17, 16, 15, 14, 13, 12, 11, 10]))
    db.upsert_bars(conn, "bars_1d", "CCC", db.YFINANCE, _bars([10] * 10))
    membership = pd.DataFrame(
        {"ticker": ["AAA", "BBB", "CCC"], "start_date": [_DATES[0]] * 3, "end_date": [None, None, _DATES[4]]}
    )
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config())

    assert result["n_constituents"].loc[_DATES[4]] == 3
    assert result["n_constituents"].loc[_DATES[5]] == 2
    assert result["n_with_data"].loc[_DATES[5]] == 2


def test_a_ticker_joining_late_is_excluded_before_its_start_date(conn):
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10] * 10))
    db.upsert_bars(conn, "bars_1d", "DDD", db.YFINANCE, _bars([10] * 10))
    membership = pd.DataFrame(
        {"ticker": ["AAA", "DDD"], "start_date": [_DATES[0], _DATES[5]], "end_date": [None, None]}
    )
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config())

    assert result["n_constituents"].loc[_DATES[0]] == 1
    assert result["n_constituents"].loc[_DATES[5]] == 2


def test_n_with_data_reflects_a_real_price_gap_independent_of_membership(conn):
    # BBB is a member the whole window but is simply missing a bars_1d row
    # on one date (a real data gap, not a membership change).
    aaa = _bars([10] * 10)
    bbb = _bars([10] * 10).drop(_DATES[3])
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, aaa)
    db.upsert_bars(conn, "bars_1d", "BBB", db.YFINANCE, bbb)
    membership = pd.DataFrame({"ticker": ["AAA", "BBB"], "start_date": [_DATES[0]] * 2, "end_date": [None, None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config())

    assert result["n_constituents"].loc[_DATES[3]] == 2
    assert result["n_with_data"].loc[_DATES[3]] == 1


def test_ad_ratio_is_null_when_nothing_declined(conn):
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config())

    assert result["n_declining"].iloc[1] == 0
    assert pd.isna(result["ad_ratio"].iloc[1])


def test_golden_cross_is_nan_unless_both_50_and_200_are_configured(conn):
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10] * 10))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config(sma_periods=(3,)))

    assert result["pct_golden_cross"].isna().all()


def test_start_end_filter_the_output_but_not_the_warmup(conn):
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config(), start=_DATES[5].isoformat())

    assert result.index.min() == _DATES[5]
    # SMA(3) is still valid here (warmed up on the full series, not just
    # the post-start window) -- not NaN just because start trims the output.
    assert pd.notna(result["pct_above_sma3"].iloc[0])


def test_empty_membership_returns_empty_frame(conn):
    result = compute_breadth(conn, "nonexistent_idx", _config())
    assert result.empty


def test_unknown_weighting_raises(conn):
    with pytest.raises(ValueError, match="cap_weighting_typo"):
        compute_breadth(conn, "test_idx", _config(weighting="cap_weighting_typo"))


def _shares(conn, ticker: str, value: float) -> None:
    db.upsert_shares_outstanding(
        conn, ticker, db.YFINANCE, pd.Series([value], index=[_DATES[0]], name="shares_outstanding")
    )


def test_cap_weighted_pct_above_sma_weights_by_market_cap_not_count(conn):
    # AAA (small share count -> small market cap) rises above its SMA(3);
    # BBB (huge share count -> huge market cap) stays below its own. Equal-
    # weight would call this 50% (1 of 2 tickers above); cap-weighted
    # should be dominated by BBB's much larger market cap instead.
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_bars(conn, "bars_1d", "BBB", db.YFINANCE, _bars([19, 18, 17, 16, 15, 14, 13, 12, 11, 10]))
    _shares(conn, "AAA", 100)
    _shares(conn, "BBB", 10_000)
    membership = pd.DataFrame({"ticker": ["AAA", "BBB"], "start_date": [_DATES[0]] * 2, "end_date": [None, None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config(weighting="cap"))

    # Day 3 (2020-01-03): AAA close=12 sma=11 -> above, cap=12*100=1200.
    # BBB close=17 sma=18 -> below, cap=17*10000=170000.
    day3 = result["pct_above_sma3"].iloc[2]
    assert day3 == pytest.approx(1200 / (1200 + 170000))
    # Confirms this genuinely differs from the equal-weight answer (0.5),
    # not just a coincidentally-similar number.
    assert day3 < 0.01


def test_cap_weighted_n_advancing_is_a_market_cap_dollar_sum_not_a_count(conn):
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_bars(conn, "bars_1d", "BBB", db.YFINANCE, _bars([19, 18, 17, 16, 15, 14, 13, 12, 11, 10]))
    _shares(conn, "AAA", 100)
    _shares(conn, "BBB", 10_000)
    membership = pd.DataFrame({"ticker": ["AAA", "BBB"], "start_date": [_DATES[0]] * 2, "end_date": [None, None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config(weighting="cap"))

    # Day 2 (2020-01-02): AAA close=11 (advancing from 10), cap=11*100=1100.
    # BBB close=18 (declining from 19), cap=18*10000=180000.
    assert result["n_advancing"].iloc[1] == pytest.approx(1100)
    assert result["n_declining"].iloc[1] == pytest.approx(180000)


def test_cap_weighted_excludes_a_member_with_no_market_cap_data_yet(conn):
    # AAA has real shares_outstanding; BBB has price data but none at all
    # (e.g. not backfilled yet) -- BBB should be excluded from the cap-
    # weighted aggregate entirely, not treated as a wrong 0 weight.
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_bars(conn, "bars_1d", "BBB", db.YFINANCE, _bars([19, 18, 17, 16, 15, 14, 13, 12, 11, 10]))
    _shares(conn, "AAA", 100)
    membership = pd.DataFrame({"ticker": ["AAA", "BBB"], "start_date": [_DATES[0]] * 2, "end_date": [None, None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config(weighting="cap"))

    # AAA close=12 > sma3=11 -> 100% of the (cap-)weighted universe that
    # actually has a market cap, since BBB contributes to neither side.
    assert result["pct_above_sma3"].iloc[2] == pytest.approx(1.0)
    # n_constituents/n_with_data stay unweighted counts regardless -- BBB
    # still counts there, it's only excluded from the *weighted* metrics.
    assert result["n_constituents"].iloc[2] == 2
    assert result["n_with_data"].iloc[2] == 2


def test_cap_weighted_returns_empty_when_no_member_has_any_market_cap_data(conn):
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10] * 10))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_breadth(conn, "test_idx", _config(weighting="cap"))
    assert result.empty


def test_cap_weighted_applies_the_local_splits_cache_to_the_cumulative_ratio(conn):
    # Confirms db.read_splits-sourced local splits actually reach the
    # market-cap reconciliation (not silently ignored), by comparing two
    # otherwise-identical setups that differ only in whether a split is
    # registered. AAA rises every day, so it's "advancing" (price-based,
    # not cap-based -- market cap only sizes *how much* an advance/decline
    # counts, same as real cap-weighted A/D indicators) on every date
    # either way; what differs is the *weight*. cumulative_split_ratio is
    # 2.0 for dates strictly before a registered split's execution date
    # and 1.0 from the split onward -- so day1's (the first date with a
    # valid prior_close at all, hence the first date that can register as
    # "advancing") cap-weighted n_advancing should be exactly 2x with the
    # split registered vs. without it (11 x 2.0 x 100 = 2200 vs.
    # 11 x 1.0 x 100 = 1100), while a date past the split (already
    # ratio=1.0 either way) is identical in both.
    def _setup(register_split: bool) -> None:
        connection = db.get_connection(":memory:")
        db.create_tables(connection)
        db.upsert_bars(connection, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
        _shares(connection, "AAA", 100)
        if register_split:
            db.upsert_splits(
                connection, "AAA", db.POLYGON,
                pd.DataFrame({"execution_date": [_DATES[4]], "split_from": [1.0], "split_to": [2.0], "ratio": [2.0]}),
            )
        membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [None]})
        db.replace_index_membership(connection, "test_idx", membership)
        return connection

    with_split = compute_breadth(_setup(True), "test_idx", _config(weighting="cap"))
    without_split = compute_breadth(_setup(False), "test_idx", _config(weighting="cap"))

    assert with_split["n_advancing"].iloc[1] == pytest.approx(2200)
    assert without_split["n_advancing"].iloc[1] == pytest.approx(1100)
    # Past the split boundary (ratio=1.0 either way), the two agree.
    assert with_split["n_advancing"].iloc[5] == without_split["n_advancing"].iloc[5] == pytest.approx(1500)


def test_advance_decline_line_is_a_cumulative_sum_of_net_advances():
    breadth = pd.DataFrame({"net_advances": [1, -2, 3, 0]}, index=pd.bdate_range("2020-01-01", periods=4))

    result = advance_decline_line(breadth)

    assert list(result) == [1, -1, 2, 2]

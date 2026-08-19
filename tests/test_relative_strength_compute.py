import pandas as pd
import pytest

from src.data_processing import db
from src.relative_strength.compute import (
    compute_sector_vs_market,
    compute_stock_vs_market,
    compute_stock_vs_sector,
)
from src.relative_strength.config import RelativeStrengthConfig

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


def _sector_row(ticker, sector):
    return {"ticker": ticker, "sector": sector, "industry": "n/a"}


def _config(**overrides) -> RelativeStrengthConfig:
    cfg = RelativeStrengthConfig(
        indices=["test_idx"], market_benchmark="SPY", mansfield_period=2,
        rs_rating_windows=(2, 3), rs_rating_weights=(0.5, 0.5), price_source=db.YFINANCE,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_stock_vs_market_rs_ratio_matches_hand_computation(conn):
    db.upsert_bars(conn, "bars_1d", "SPY", db.YFINANCE, _bars([100, 101, 102, 103, 104, 105, 106, 107, 108, 109]))
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 12, 14, 16, 18, 20, 22, 24, 26, 28]))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_stock_vs_market(conn, "test_idx", _config())

    row0 = result[result["date"] == _DATES[0]].iloc[0]
    assert row0["rs_ratio"] == pytest.approx(10 / 100)
    assert row0["benchmark"] == "SPY"


def test_mansfield_is_computed_on_weekly_bars_not_daily(conn):
    # 6 full Mon-Fri business weeks. SPY flat, AAA rising every day. If
    # rs_mansfield were (still) derived from the daily ratio, it would
    # change every single day; derived from weekly-resampled closes, it can
    # only change once a week (at each week's completed close) -- so it
    # must be identical across every trading day within the same calendar
    # week, even though rs_ratio itself changes daily.
    weekly_dates = pd.bdate_range("2020-01-06", periods=30)
    spy_closes = [100.0] * 30
    aaa_closes = [10 + 0.5 * i for i in range(30)]

    def _frame(closes):
        return pd.DataFrame(
            {
                "timestamp": weekly_dates, "open": closes, "high": [c + 0.5 for c in closes],
                "low": [c - 0.5 for c in closes], "close": closes, "volume": [1000] * 30,
                "is_partial": [0] * 30,
            }
        ).set_index("timestamp")

    db.upsert_bars(conn, "bars_1d", "SPY", db.YFINANCE, _frame(spy_closes))
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _frame(aaa_closes))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [weekly_dates[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_stock_vs_market(conn, "test_idx", _config(mansfield_period=2))

    result = result.set_index("date").sort_index()
    result["week"] = result.index.to_period("W-SUN")
    per_week_distinct_values = result.groupby("week")["rs_mansfield"].nunique(dropna=False)
    assert (per_week_distinct_values <= 1).all()
    # And it isn't just uniformly NaN/constant everywhere -- real week-to-
    # week variation exists once warmed up (period=2 weeks).
    assert result["rs_mansfield"].dropna().nunique() > 1


def test_a_ticker_with_no_completed_weekly_bar_yet_gets_nan_mansfield_not_a_crash(conn):
    # Regression: a ticker with daily bars but not yet one full completed
    # trading week (e.g. just added to index_membership a few days ago)
    # used to crash the whole compute_stock_vs_market run -- the empty
    # weekly-Mansfield fallback had a default RangeIndex, and reindexing
    # that with method="ffill" against rs_ratio's DatetimeIndex raised
    # TypeError: Cannot compare dtypes int64 and datetime64[us].
    db.upsert_bars(conn, "bars_1d", "SPY", db.YFINANCE, _bars([100.0] * 10))
    short_dates = _DATES[:3]
    aaa = pd.DataFrame(
        {
            "timestamp": short_dates, "open": [10.0] * 3, "high": [10.5] * 3, "low": [9.5] * 3,
            "close": [10.0] * 3, "volume": [1000] * 3, "is_partial": [0] * 3,
        }
    ).set_index("timestamp")
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, aaa)
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [short_dates[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_stock_vs_market(conn, "test_idx", _config())

    assert len(result) == 3
    assert result["rs_mansfield"].isna().all()


def test_stock_vs_market_rs_rating_ranks_within_the_index(conn):
    db.upsert_bars(conn, "bars_1d", "SPY", db.YFINANCE, _bars([100] * 10))
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_bars(conn, "bars_1d", "BBB", db.YFINANCE, _bars([19, 18, 17, 16, 15, 14, 13, 12, 11, 10]))
    membership = pd.DataFrame({"ticker": ["AAA", "BBB"], "start_date": [_DATES[0]] * 2, "end_date": [None, None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_stock_vs_market(conn, "test_idx", _config())

    last = result[result["date"] == _DATES[-1]].set_index("ticker")
    assert last.loc["AAA", "rs_rating"] > last.loc["BBB", "rs_rating"]


def test_a_ticker_leaving_the_index_stops_contributing_after_its_end_date(conn):
    db.upsert_bars(conn, "bars_1d", "SPY", db.YFINANCE, _bars([100] * 10))
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [_DATES[4]]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_stock_vs_market(conn, "test_idx", _config())

    assert result["date"].max() == _DATES[4]


def test_empty_membership_returns_empty_frame(conn):
    result = compute_stock_vs_market(conn, "nonexistent_idx", _config())
    assert result.empty


def test_missing_benchmark_data_returns_empty_frame(conn):
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10] * 10))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_stock_vs_market(conn, "test_idx", _config())
    assert result.empty


def test_stock_vs_sector_uses_sector_etf_as_benchmark(conn):
    db.upsert_bars(conn, "bars_1d", "XLK", db.YFINANCE, _bars([50] * 10))
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_ticker_sector(conn, pd.DataFrame([_sector_row("AAA", "Technology")]))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_stock_vs_sector(conn, "test_idx", _config())

    assert not result.empty
    assert (result["benchmark"] == "XLK").all()


def test_stock_vs_sector_rs_rating_only_ranks_within_same_sector(conn):
    db.upsert_bars(conn, "bars_1d", "XLK", db.YFINANCE, _bars([50] * 10))
    db.upsert_bars(conn, "bars_1d", "XLF", db.YFINANCE, _bars([50] * 10))
    # AAA (Tech) rises; BBB (Tech) falls; CCC (Financial) rises just like AAA.
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_bars(conn, "bars_1d", "BBB", db.YFINANCE, _bars([19, 18, 17, 16, 15, 14, 13, 12, 11, 10]))
    db.upsert_bars(conn, "bars_1d", "CCC", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_ticker_sector(
        conn,
        pd.DataFrame(
            [
                _sector_row("AAA", "Technology"),
                _sector_row("BBB", "Technology"),
                _sector_row("CCC", "Financial Services"),
            ]
        ),
    )
    membership = pd.DataFrame(
        {"ticker": ["AAA", "BBB", "CCC"], "start_date": [_DATES[0]] * 3, "end_date": [None, None, None]}
    )
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_stock_vs_sector(conn, "test_idx", _config())

    last = result[result["date"] == _DATES[-1]].set_index("ticker")
    # AAA is the sole riser among its 2-member Tech peer group -> top percentile.
    assert last.loc["AAA", "rs_rating"] == 100.0
    assert last.loc["BBB", "rs_rating"] == 50.0
    # CCC is alone in its sector -> always the whole (1-member) peer group.
    assert last.loc["CCC", "rs_rating"] == 100.0


def test_stock_vs_sector_skips_a_ticker_with_no_sector_on_file(conn):
    db.upsert_bars(conn, "bars_1d", "XLK", db.YFINANCE, _bars([50] * 10))
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE, _bars([10] * 10))
    membership = pd.DataFrame({"ticker": ["AAA"], "start_date": [_DATES[0]], "end_date": [None]})
    db.replace_index_membership(conn, "test_idx", membership)

    result = compute_stock_vs_sector(conn, "test_idx", _config())
    assert result.empty


def test_sector_vs_market_ranks_the_sector_etfs(conn):
    db.upsert_bars(conn, "bars_1d", "SPY", db.YFINANCE, _bars([100] * 10))
    db.upsert_bars(conn, "bars_1d", "XLK", db.YFINANCE, _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]))
    db.upsert_bars(conn, "bars_1d", "XLF", db.YFINANCE, _bars([19, 18, 17, 16, 15, 14, 13, 12, 11, 10]))

    result = compute_sector_vs_market(conn, _config())

    last = result[result["date"] == _DATES[-1]].set_index("sector")
    assert last.loc["Technology", "rs_rating"] > last.loc["Financial Services", "rs_rating"]
    assert (result["benchmark"] == "SPY").all()


def test_sector_vs_market_empty_when_no_sector_etf_data(conn):
    db.upsert_bars(conn, "bars_1d", "SPY", db.YFINANCE, _bars([100] * 10))

    result = compute_sector_vs_market(conn, _config())
    assert result.empty

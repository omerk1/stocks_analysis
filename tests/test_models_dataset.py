import logging

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing.ticker_renames import apply_renames
from src.models import dataset
from src.models.dataset import HoldoutError, LiquidityFloor, build_labels, check_holdout, read_labels, universe_mask
from src.models.labels.barriers import barrier_labels, v1_grid

DAYS = pd.bdate_range("2019-06-03", "2022-03-31")
TR_SCALE = 0.9  # total-return closes sit below traded closes (dividends)


def _walk(seed, n, start=100.0):
    rng = np.random.default_rng(seed)
    return start * np.exp(np.cumsum(rng.normal(0, 0.015, n)))


def _store_bars(conn, ticker, days, close, volume):
    close = np.asarray(close, dtype=float)
    opn = np.concatenate([[close[0]], close[:-1]])
    for source, scale in ((db.YFINANCE_SPLIT_ONLY, 1.0), (db.YFINANCE, TR_SCALE)):
        frame = pd.DataFrame({
            "open": opn * scale, "high": np.maximum(opn, close) * scale * 1.01,
            "low": np.minimum(opn, close) * scale * 0.99, "close": close * scale,
            "volume": volume, "is_partial": 0,
        }, index=days)
        db.upsert_bars(conn, "bars_1d", ticker, source, frame)


@pytest.fixture
def conn():
    c = db.get_connection(":memory:")
    db.create_tables(c)
    n = len(DAYS)
    _store_bars(c, "AAA", DAYS, _walk(1, n), 1_000_000)          # ~$100M/day: liquid
    _store_bars(c, "BBB", DAYS, _walk(2, n), 50_000)             # ~$5M/day: illiquid
    _store_bars(c, "META", DAYS, _walk(3, n), 1_000_000)         # prices live under the new symbol
    late = DAYS[DAYS >= "2020-03-02"]
    _store_bars(c, "CCC", late, _walk(4, len(late)), 1_000_000)  # history starts inside the window
    # $21M traded, $18.9M on total-return prices: liquid only on the traded basis.
    _store_bars(c, "DDD", DAYS, np.full(n, 100.0), 210_000)
    _store_bars(c, "PENNY", DAYS, np.full(n, 0.5), 100_000_000)  # $50M/day but trades under $1
    gone = DAYS[DAYS <= "2020-06-30"]
    _store_bars(c, "GONE", gone, _walk(5, len(gone)), 1_000_000)  # delisted mid-window
    db.replace_index_membership(c, "sp500", pd.DataFrame([
        ("AAA", "2020-01-01", "2020-06-30"),
        ("BBB", "2019-01-01", None),
        ("FB", "2019-01-01", None),
        ("CCC", "2020-01-01", None),
        ("DDD", "2019-01-01", None),
        ("PENNY", "2019-01-01", None),
        ("GONE", "2019-01-01", "2020-06-30"),
        ("OLDSYM", "2019-01-01", None),
    ], columns=["ticker", "start_date", "end_date"]))
    db.replace_index_membership(c, "nasdaq100", pd.DataFrame([
        ("BBB", "2020-01-01", None),
    ], columns=["ticker", "start_date", "end_date"]))
    db.upsert_ticker_rename(c, {"old_ticker": "FB", "new_ticker": "META", "status": "matched",
                                "valid_from": "2012-05-18", "valid_to": "2022-06-08"})
    # A matched rename whose window doesn't cover these rows: the symbol stays.
    db.upsert_ticker_rename(c, {"old_ticker": "OLDSYM", "new_ticker": "AAA", "status": "matched",
                                "valid_from": "2005-01-01", "valid_to": "2008-01-01"})
    yield c
    c.close()


# ---------------------------------------------------------------- H1

def test_holdout_lock_refuses_dates_past_the_boundary():
    check_holdout("2021-12-31")
    with pytest.raises(HoldoutError):
        check_holdout("2022-01-03")


def test_opening_the_holdout_is_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="src.models.dataset"):
        check_holdout("2022-01-03", open_holdout=True)
    assert "HOLDOUT OPEN" in caplog.text


def test_universe_refuses_holdout_and_records_when_opened(conn):
    with pytest.raises(HoldoutError):
        universe_mask(conn, "2021-06-01", "2022-02-01")
    u = universe_mask(conn, "2021-06-01", "2022-02-01", open_holdout=True)
    assert u.attrs["spec"]["open_holdout"] is True
    assert u["date"].max() > dataset.HOLDOUT_END
    assert universe_mask(conn, "2021-06-01", "2021-12-31").attrs["spec"]["open_holdout"] is False


# ---------------------------------------------------------------- H3 membership

def test_membership_matches_per_date_as_of_queries(conn):
    u = universe_mask(conn, "2020-01-01", "2021-12-31", indices=("sp500", "nasdaq100"))
    for d in pd.to_datetime(["2020-01-02", "2020-06-30", "2020-07-01", "2021-12-31"]):
        expected = set()
        for name in ("sp500", "nasdaq100"):
            expected |= set(apply_renames(conn, db.read_index_membership(conn, name, as_of=d))["ticker"])
        assert set(u.loc[u["date"] == d, "ticker"]) == expected


def test_end_date_is_inclusive(conn):
    u = universe_mask(conn, "2020-01-01", "2020-12-31")
    aaa = u.loc[u["ticker"] == "AAA", "date"]
    assert aaa.max() == pd.Timestamp("2020-06-30")
    assert aaa.min() == pd.Timestamp("2020-01-01")  # the fixture's calendar is plain business days


def test_renamed_member_keeps_its_prices_and_out_of_window_rename_does_not_apply(conn):
    u = universe_mask(conn, "2020-01-01", "2020-12-31")
    assert "FB" not in set(u["ticker"])
    meta = u[u["ticker"] == "META"]
    assert len(meta) and meta["has_bars"].all() and meta["liquid"].all()
    old = u[u["ticker"] == "OLDSYM"]  # rename window 2005-2008: not applied, so no prices
    assert len(old) and not old["has_bars"].any() and not old["eligible"].any()


def test_index_flags_per_row(conn):
    u = universe_mask(conn, "2020-01-01", "2020-12-31", indices=("sp500", "nasdaq100"))
    bbb = u[u["ticker"] == "BBB"]
    assert bbb["in_sp500"].all() and bbb["in_ndx100"].all()
    assert not u.loc[u["ticker"] == "AAA", "in_ndx100"].any()


def test_unstored_and_unknown_indices_raise(conn):
    with pytest.raises(NotImplementedError):
        universe_mask(conn, "2020-01-01", "2020-12-31", indices=("r1000_proxy",))
    with pytest.raises(ValueError):
        universe_mask(conn, "2020-01-01", "2020-12-31", indices=("dow30",))


# ---------------------------------------------------------------- H3 liquidity + eligibility

def test_liquidity_floor(conn):
    u = universe_mask(conn, "2020-01-01", "2020-12-31").set_index("ticker")
    assert u.loc["AAA", "liquid"].all()
    assert not u.loc["BBB", "liquid"].any()


def test_liquidity_uses_traded_prices(conn):
    u = universe_mask(conn, "2020-01-01", "2020-12-31")
    ddd = u[u["ticker"] == "DDD"]
    assert ddd["dollar_volume_20d"].iloc[-1] == pytest.approx(21e6)
    assert ddd["liquid"].all()


def test_liquidity_is_not_known_during_warmup(conn):
    u = universe_mask(conn, "2020-01-01", "2020-12-31")
    ccc = u[u["ticker"] == "CCC"].reset_index(drop=True)
    no_bars = ccc[~ccc["has_bars"]]
    assert (no_bars["date"] < pd.Timestamp("2020-03-02")).all() and not no_bars["eligible"].any()
    traded = ccc[ccc["has_bars"]].reset_index(drop=True)
    assert traded["dollar_volume_20d"].iloc[:19].isna().all()
    assert not traded["liquid"].iloc[:19].any() and not traded["eligible"].iloc[:19].any()
    assert traded["liquid"].iloc[19]


def test_dollar_volume_ignores_the_future(conn):
    bars = dataset.read_bars_bulk(conn, ["AAA"], dataset.UNIVERSE_BASIS, "2019-06-01", "2021-12-31")
    base = dataset.trailing_dollar_volume(bars)
    t = 300
    perturbed = bars.copy()
    perturbed.loc[t + 1:, ["close", "volume"]] *= 50
    assert dataset.trailing_dollar_volume(perturbed).iloc[: t + 1].equals(base.iloc[: t + 1])


def test_dollar_volume_refuses_total_return_bars(conn):
    bars = dataset.read_bars_bulk(conn, ["AAA"], dataset.LABEL_BASIS, "2019-06-01", "2021-12-31")
    with pytest.raises(ValueError):
        dataset.trailing_dollar_volume(bars)


def test_history_breaks_mark_penny_rows_ineligible(conn):
    u = universe_mask(conn, "2020-01-01", "2020-12-31")
    penny = u[u["ticker"] == "PENNY"]
    assert penny["liquid"].all() and not penny["history_eligible"].any() and not penny["eligible"].any()


def test_price_floor_uses_the_traded_close(conn):
    floors = {"sp500": LiquidityFloor(1e6, min_price=95.0)}
    u = universe_mask(conn, "2020-01-01", "2020-12-31", floors=floors)
    assert u.loc[u["ticker"] == "DDD", "liquid"].all()  # traded 100 passes; total-return 90 would not
    assert u.attrs["spec"]["floors"]["sp500"] == {"min_dollar_volume": 1e6, "min_price": 95.0}


# ---------------------------------------------------------------- labels

def _rows(conn, start="2020-01-01", end="2021-12-31", open_holdout=False):
    u = universe_mask(conn, start, end, open_holdout=open_holdout)
    return u[u["has_bars"]]


def test_label_cache_round_trip_matches_barrier_labels(conn, tmp_path):
    rows = _rows(conn)
    build_labels(conn, rows, 21, tmp_path, chunk_size=2)
    cached = read_labels(tmp_path, 21)
    assert cached.attrs["manifest"]["open_holdout"] is False
    assert len(cached) == len(rows) * 9
    assert cached["atr"].dtype == np.float32

    bars = dataset.read_bars_bulk(conn, ["AAA"], dataset.LABEL_BASIS, "2019-01-01", "2021-12-31")
    direct = barrier_labels(bars, [c for c in v1_grid() if c.horizon == 21], data_end="2021-12-31")
    direct = direct[direct["date"].isin(rows.loc[rows["ticker"] == "AAA", "date"])]
    mine = cached[cached["ticker"] == "AAA"]
    key = ["date", "upper", "lower"]
    merged = mine.merge(direct, on=key, suffixes=("", "_d"))
    assert len(merged) == len(mine)
    np.testing.assert_array_equal(merged["hit"].to_numpy(), merged["hit_d"].astype("float32").to_numpy())
    np.testing.assert_allclose(merged["ret"], merged["ret_d"], rtol=1e-5)
    close = bars.set_index("date")["close"]
    np.testing.assert_allclose(mine["close_t"], close.reindex(mine["date"]).to_numpy(), rtol=1e-6)


def test_labels_never_read_past_the_holdout(conn, tmp_path):
    build_labels(conn, _rows(conn), 21, tmp_path)
    labels = read_labels(tmp_path, 21)
    ddd = labels[labels["ticker"] == "DDD"]
    # The DB has bars into 2022, but a window crossing 2021-12-31 stays NaN:
    # 2021-12-02 + 21 business days is exactly 2021-12-31, the last complete one.
    assert ddd.loc[ddd["date"] == "2021-12-02", "hit"].notna().all()
    assert ddd.loc[ddd["date"] > "2021-12-02", "hit"].isna().all()
    assert labels["label_end_date"].max() <= dataset.HOLDOUT_END
    with pytest.raises(HoldoutError):
        read_labels(tmp_path, 21, end="2022-01-31")


def test_holdout_built_cache_needs_the_flag_to_read(conn, tmp_path):
    rows = _rows(conn, "2021-06-01", "2022-02-28", open_holdout=True)
    with pytest.raises(HoldoutError):
        build_labels(conn, rows, 21, tmp_path)
    build_labels(conn, rows, 21, tmp_path, open_holdout=True)
    with pytest.raises(HoldoutError):
        read_labels(tmp_path, 21)
    assert read_labels(tmp_path, 21, open_holdout=True)["date"].max() > dataset.HOLDOUT_END


def test_delisting_is_detected_when_labeled_in_its_own_chunk(conn, tmp_path):
    rows = _rows(conn)
    build_labels(conn, rows[rows["ticker"].isin(["GONE", "AAA"])], 21, tmp_path, chunk_size=1)
    gone = read_labels(tmp_path, 21)
    gone = gone[gone["ticker"] == "GONE"]
    near_end = gone[(gone["date"] > "2020-06-01") & (gone["date"] < gone["date"].max())]
    # Its history ends long before the dataset does: windows resolve on the last
    # bar (its own last row has no bar after it, so stays NaN).
    assert near_end["truncated"].any() and near_end["hit"].notna().all()


def test_build_labels_rejects_a_horizon_outside_the_grid(conn, tmp_path):
    with pytest.raises(ValueError):
        build_labels(conn, _rows(conn), 7, tmp_path)


def test_delisting_is_detected_when_only_early_ended_names_are_labeled(conn, tmp_path):
    # No ticker that traded to the end is in this call; the calendar still comes
    # from every index member, so GONE resolves as delisted.
    rows = _rows(conn)
    build_labels(conn, rows[rows["ticker"] == "GONE"], 21, tmp_path)
    gone = read_labels(tmp_path, 21)
    near_end = gone[(gone["date"] > "2020-06-01") & (gone["date"] < gone["date"].max())]
    assert near_end["truncated"].any() and near_end["hit"].notna().all()

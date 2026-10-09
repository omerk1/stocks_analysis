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


def test_a_cache_built_for_another_grid_is_refused(conn, tmp_path):
    """A cache from before the 2026-10-06 rescale (fixed-ATR cells, U=1) keeps
    the same column names; its manifest must make it unreadable."""
    import json
    build_labels(conn, _rows(conn, "2021-01-04", "2021-06-30"), 21, tmp_path)
    manifest_path = dataset.label_path(tmp_path, 21).with_suffix(".json")
    manifest = json.loads(manifest_path.read_text())
    manifest["cells"] = [{"upper": u, "lower": d} for u in (1.0, 2.0, 3.0) for d in (1.0, 1.5, 2.0)]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(dataset.StaleLabelCacheError):
        read_labels(tmp_path, 21)


def test_a_cache_built_with_another_disputes_list_is_refused(conn, tmp_path, monkeypatch):
    """Labels built before a data fix adds disputes still hold the rows it
    drops; the cache must be rebuilt, not read."""
    from src.foundation.market_common import price_disputes
    build_labels(conn, _rows(conn, "2021-01-04", "2021-06-30"), 21, tmp_path)
    read_labels(tmp_path, 21)
    monkeypatch.setattr(dataset, "DISPUTED_DAYS",
                        dataset.DISPUTED_DAYS + (price_disputes.DisputedDay("AAA", None, "yfinance", "reused"),))
    with pytest.raises(dataset.StaleLabelCacheError):
        read_labels(tmp_path, 21)


def test_read_labels_can_take_one_cell(conn, tmp_path):
    build_labels(conn, _rows(conn, "2021-01-04", "2021-06-30"), 21, tmp_path)
    one = read_labels(tmp_path, 21, cell=(2, 1.5))
    every = read_labels(tmp_path, 21)
    assert set(zip(one["upper"], one["lower"])) == {(2.0, 1.5)}
    assert len(one) == len(every) // 9


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


# ---------------------------------------------------------------- Tiingo fallback

def _store_tiingo(conn, ticker, days, close, volume, scale=1.0):
    close = np.asarray(close, dtype=float) * scale
    for source, s in ((db.TIINGO_SPLIT_ONLY, 1.0), (db.TIINGO, TR_SCALE)):
        frame = pd.DataFrame({"open": close * s, "high": close * s * 1.01, "low": close * s * 0.99,
                              "close": close * s, "volume": volume, "is_partial": 0}, index=days)
        db.upsert_bars(conn, "bars_1d", ticker, source, frame)


def _add_member(conn, ticker, start="2019-01-01", end=None):
    current = db.read_index_membership(conn, "sp500")[["ticker", "start_date", "end_date"]]
    rows = pd.concat([current, pd.DataFrame([(ticker, start, end)], columns=current.columns)])
    db.replace_index_membership(conn, "sp500", rows)


def test_a_member_with_only_tiingo_bars_is_in_the_universe_and_labeled(conn, tmp_path):
    _store_tiingo(conn, "DELIST", DAYS, _walk(6, len(DAYS)), 1_000_000)
    _add_member(conn, "DELIST")

    mask = universe_mask(conn, "2020-01-01", "2021-06-30")
    rows = mask[mask["ticker"] == "DELIST"]

    assert rows["has_bars"].all() and rows["eligible"].any()
    assert mask.attrs["spec"]["price_sources"][db.TIINGO_SPLIT_ONLY] == 1

    path = build_labels(conn, rows[["ticker", "date"]], 21, tmp_path)
    labels = read_labels(tmp_path, 21)
    assert set(labels["ticker"]) == {"DELIST"} and labels["hit"].notna().any()
    assert json_manifest(path)["price_sources"] == {db.TIINGO: 1}


def json_manifest(path):
    import json
    return json.loads(path.with_suffix(".json").read_text())


def test_yfinance_wins_and_sources_are_never_spliced(conn):
    # Tiingo bars for a yfinance ticker (10x off, extending past its history) are ignored entirely.
    _store_tiingo(conn, "CCC", DAYS, np.full(len(DAYS), 1.0), 1_000_000, scale=10)

    bars = dataset.read_bars_bulk(conn, ["CCC"], dataset.LABEL_BASIS, "2019-06-01", "2021-12-31", fallback=True)
    yf = dataset.read_bars_bulk(conn, ["CCC"], dataset.LABEL_BASIS, "2019-06-01", "2021-12-31")

    pd.testing.assert_frame_equal(bars, yf)
    assert bars["date"].min() >= pd.Timestamp("2020-03-02")


def test_without_fallback_tiingo_bars_are_not_read(conn):
    _store_tiingo(conn, "DELIST", DAYS, _walk(6, len(DAYS)), 1_000_000)

    assert dataset.read_bars_bulk(conn, ["DELIST"], dataset.LABEL_BASIS, "2019-06-01", "2021-12-31").empty


def test_tiingo_members_use_tiingo_splits_for_the_traded_close(conn):
    _store_tiingo(conn, "RSPLIT", DAYS, np.full(len(DAYS), 100.0), 1_000_000)
    _add_member(conn, "RSPLIT")
    split = pd.DataFrame({"execution_date": [pd.Timestamp("2021-06-01")], "split_from": [20.0],
                          "split_to": [1.0], "ratio": [0.05]})
    db.upsert_splits(conn, "RSPLIT", db.TIINGO, split)

    mask = universe_mask(conn, "2021-01-04", "2021-12-31").set_index(["ticker", "date"])

    assert mask.loc[("RSPLIT", pd.Timestamp("2021-05-28")), "unadjusted_close"] == pytest.approx(5.0)
    assert mask.loc[("RSPLIT", pd.Timestamp("2021-06-01")), "unadjusted_close"] == pytest.approx(100.0)


def test_a_preferred_ticker_is_read_from_tiingo_on_both_bases(conn, monkeypatch):
    from src.foundation.market_common import price_basis
    monkeypatch.setattr(price_basis, "PREFER_TIINGO", {"AAA": "test"})
    _store_tiingo(conn, "AAA", DAYS, np.full(len(DAYS), 50.0), 1_000_000)

    for basis in (dataset.LABEL_BASIS, dataset.UNIVERSE_BASIS):
        bars = dataset.read_bars_bulk(conn, ["AAA", "BBB"], basis, "2019-06-01", "2021-12-31", fallback=True)
        assert bars.loc[bars["ticker"] == "AAA", "close"].round(4).isin([50.0, 50.0 * TR_SCALE]).all()
        assert bars.attrs["price_sources"][price_basis.FALLBACK_SOURCE_BY_BASIS[basis]] == 1
    # without the fallback (every other module) the listing is ignored
    plain = dataset.read_bars_bulk(conn, ["AAA"], dataset.LABEL_BASIS, "2019-06-01", "2021-12-31")
    assert not plain["close"].round(4).eq(50.0 * TR_SCALE).all()


def test_a_preferred_ticker_without_tiingo_bars_is_an_error(conn, monkeypatch):
    from src.foundation.market_common import price_basis
    monkeypatch.setattr(price_basis, "PREFER_TIINGO", {"AAA": "test"})

    with pytest.raises(ValueError, match="store-preferred"):
        dataset.read_bars_bulk(conn, ["AAA"], dataset.LABEL_BASIS, "2019-06-01", "2021-12-31", fallback=True)


def test_drop_disputed_covers_the_label_window_and_the_atr_tail():
    from src.foundation.market_common.price_disputes import DisputedDay

    cal = pd.bdate_range("2020-01-01", periods=120)
    labels = pd.DataFrame({"ticker": "AAA", "date": cal})
    disputes = (DisputedDay("AAA", str(cal[60].date()), "yfinance", "test"),)

    kept, n = dataset.drop_disputed(labels, {"AAA": db.YFINANCE}, labels, horizon=10, disputes=disputes)

    gone = sorted(set(labels["date"]) - set(kept["date"]))
    assert gone[0] == cal[50] and gone[-1] == cal[60 + dataset.DISPUTE_ATR_TAIL]
    assert n == 10 + 1 + dataset.DISPUTE_ATR_TAIL


def test_drop_disputed_counts_the_tickers_own_bars_not_the_market_calendar():
    from src.foundation.market_common.price_disputes import DisputedDay

    cal = pd.bdate_range("2020-01-01", periods=120)
    own = cal.delete(range(40, 55))  # 15 missing sessions before the dispute
    labels = pd.DataFrame({"ticker": "AAA", "date": own})
    disputes = (DisputedDay("AAA", str(cal[70].date()), "yfinance", "test"),)

    kept, _ = dataset.drop_disputed(labels, {"AAA": db.YFINANCE}, labels, horizon=10, disputes=disputes)

    first_gone = min(set(labels["date"]) - set(kept["date"]))
    # 10 of the ticker's own bars before the dispute, not 10 market days
    assert first_gone == own[list(own).index(cal[70]) - 10]


def test_drop_disputed_only_applies_to_the_vendor_with_the_bad_bars():
    from src.foundation.market_common.price_disputes import DisputedDay

    cal = pd.bdate_range("2020-01-01", periods=60)
    labels = pd.DataFrame({"ticker": ["AAA"] * 60 + ["BBB"] * 60, "date": list(cal) * 2})
    disputes = (DisputedDay("AAA", str(cal[30].date()), "yfinance", "t"), DisputedDay("BBB", None, "tiingo", "t"))

    kept, n = dataset.drop_disputed(labels, {"AAA": db.TIINGO, "BBB": db.TIINGO_SPLIT_ONLY}, labels, 10, disputes)

    assert set(kept["ticker"]) == {"AAA"} and len(kept) == 60 and n == 60


def test_build_labels_drops_disputed_rows_and_records_them(conn, tmp_path, monkeypatch):
    from src.foundation.market_common import price_disputes
    monkeypatch.setattr(dataset, "DISPUTED_DAYS", (price_disputes.DisputedDay("AAA", "2020-03-02", "yfinance", "t"),))
    rows = universe_mask(conn, "2020-01-01", "2020-06-30")
    rows = rows[rows["ticker"] == "AAA"][["ticker", "date"]]

    path = build_labels(conn, rows, 21, tmp_path)

    labels = read_labels(tmp_path, 21)
    assert json_manifest(path)["n_disputed_dropped"] > 0
    assert not labels["date"].between("2020-02-28", "2020-03-31").any()


def test_the_disputes_file_loads_and_names_known_vendors():
    from src.foundation.market_common import price_disputes

    days = price_disputes.load()
    assert days and {d.vendor for d in days} <= {price_disputes.YFINANCE, price_disputes.TIINGO}
    assert all(d.reason for d in days)
    assert all(d.date is None or pd.Timestamp(d.date) for d in days)


def test_a_whole_history_dispute_removes_the_ticker_from_the_modeling_universe(conn, monkeypatch):
    from src.foundation.market_common.price_disputes import DisputedDay
    from src.foundation.market_common import price_basis
    # whole-history disputes are read in price_basis.resolve_sources (#194)
    monkeypatch.setattr(price_basis, "DISPUTED_DAYS", (DisputedDay("BBB", None, "yfinance", "reused symbol"),))

    mask = universe_mask(conn, "2020-01-01", "2020-06-30")

    assert not mask.loc[mask["ticker"] == "BBB", "has_bars"].any()
    assert mask.loc[mask["ticker"] == "AAA", "has_bars"].all()
    # every other module still reads it
    assert not dataset.read_bars_bulk(conn, ["BBB"], dataset.LABEL_BASIS, "2020-01-01", "2020-06-30").empty

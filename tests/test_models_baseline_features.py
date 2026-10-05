import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.models.dataset import HoldoutError
from src.models.features import baseline
from src.signals.moving_averages.features import panel as ma_panel

DAYS = pd.bdate_range("2018-01-01", "2021-12-31")


def _ohlcv(seed, days=DAYS):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, len(days))))
    opn = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": opn, "high": np.maximum(opn, close) * 1.01, "low": np.minimum(opn, close) * 0.99,
                         "close": close, "volume": 1e6}, index=days)


def test_definitions_match_the_ma_study_unlagged():
    bars = _ohlcv(1)
    mine = baseline.ticker_features(bars["close"])
    theirs = ma_panel._build_ticker_features(bars.rename_axis("timestamp"), "AAA").set_index("date")
    for col in baseline.NUMERIC_COLUMNS:
        np.testing.assert_allclose(mine[col], theirs[col].astype("float32"), rtol=1e-6, equal_nan=True)


def test_ma_panel_row_is_this_row_one_day_later():
    # The MA panel lags one row: its value at d is ours at d-1.
    bars = _ohlcv(2)
    sectors = pd.DataFrame({"ticker": ["AAA"], "sector": ["Tech"], "industry": [None], "updated_at": ["x"]})
    lagged = ma_panel.assemble_panel({"AAA": bars.rename_axis("timestamp")}, sectors).set_index("date")
    mine = baseline.ticker_features(bars["close"])
    for col in baseline.NUMERIC_COLUMNS:
        np.testing.assert_allclose(lagged[col].iloc[1:].to_numpy(), mine[col].iloc[:-1].to_numpy(),
                                   rtol=1e-6, equal_nan=True)


def test_features_ignore_the_future():
    bars = _ohlcv(3)
    t = 600
    base = baseline.ticker_features(bars["close"])
    future = bars["close"].copy()
    future.iloc[t + 1:] *= np.linspace(0.3, 3.0, len(future) - t - 1)
    moved = baseline.ticker_features(future)
    pd.testing.assert_frame_equal(base.iloc[: t + 1], moved.iloc[: t + 1])


def test_warmup_is_nan_not_zero():
    f = baseline.ticker_features(_ohlcv(4)["close"])
    assert f["mom_12_1"].iloc[:252].isna().all() and f["mom_12_1"].iloc[252:].notna().all()
    assert f["dist_pct_sma_50"].iloc[:49].isna().all()


def test_ranks_are_per_date_and_keep_nan():
    frame = pd.DataFrame({"date": pd.to_datetime(["2020-01-02"] * 4 + ["2020-01-03"] * 2),
                          "mom_12_1": [0.1, 0.3, 0.2, np.nan, -5.0, 5.0]})
    r = baseline.add_ranks(frame, ("mom_12_1",))["mom_12_1_rank"]
    np.testing.assert_allclose(r.iloc[:3], [1 / 3, 1.0, 2 / 3], rtol=1e-6)
    assert np.isnan(r.iloc[3])
    np.testing.assert_allclose(r.iloc[4:], [0.5, 1.0])


@pytest.fixture
def conn():
    c = db.get_connection(":memory:")
    db.create_tables(c)
    for i, t in enumerate(["AAA", "BBB"]):
        db.upsert_bars(c, "bars_1d", t, db.YFINANCE, _ohlcv(10 + i).assign(is_partial=0))
    c.execute("INSERT INTO ticker_sector (ticker, sector, industry, updated_at) VALUES ('AAA', 'Technology', NULL, 'x'), ('BBB', '', NULL, 'x')")
    yield c
    c.close()


def test_build_features_from_the_database(conn, tmp_path):
    f = baseline.build_features(conn, ["AAA", "BBB"], "2020-01-01", "2021-12-31")
    assert f["date"].min() >= pd.Timestamp("2020-01-01") and f["date"].max() <= pd.Timestamp("2021-12-31")
    assert f["mom_12_1"].notna().all()  # warm-up bars were read from before `start`
    assert (f.loc[f["ticker"] == "AAA", "sector"] == "Technology").all()
    assert f.loc[f["ticker"] == "BBB", "sector"].isna().all()  # empty sector is unknown, not a category
    path = baseline.write_features(f, tmp_path, {"start": "2020-01-01", "end": "2021-12-31"})
    back = baseline.read_features(tmp_path)
    assert path.exists() and len(back) == len(f) and back.attrs["manifest"]["feature_basis"] == "total_return"


def test_build_features_refuses_the_holdout(conn):
    with pytest.raises(HoldoutError):
        baseline.build_features(conn, ["AAA"], "2021-01-01", "2022-06-30")

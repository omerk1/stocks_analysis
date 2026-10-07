import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.models import vendor_check as vc

DAYS = pd.bdate_range("2017-01-02", "2021-12-31")
TICKERS = [f"T{i}" for i in range(8)]
WINDOW = ("2020-01-01", "2021-12-31")


def _store(conn, ticker, vendor, close, volume):
    opn = np.concatenate([[close[0]], close[:-1]])
    frame = pd.DataFrame({"open": opn, "high": np.maximum(opn, close) * 1.01, "low": np.minimum(opn, close) * 0.99,
                          "close": close, "volume": volume, "is_partial": 0}, index=DAYS)
    for source in vc.VENDOR_SOURCES[vendor].values():
        db.upsert_bars(conn, "bars_1d", ticker, source, frame)


@pytest.fixture
def paths():
    rng = np.random.default_rng(0)
    return {t: (100 * np.exp(np.cumsum(rng.normal(0, 0.015, len(DAYS)))),
                rng.uniform(5e5, 2e6, len(DAYS))) for t in TICKERS}


@pytest.fixture
def conn():
    c = db.get_connection(":memory:")
    db.create_tables(c)
    yield c
    c.close()


def test_identical_vendors_pass(conn, paths):
    for t, (close, volume) in paths.items():
        _store(conn, t, "yfinance", close, volume)
        _store(conn, t, "tiingo", close, volume)

    r = vc.same_ticker(conn, vc.both_vendor_tickers(conn, TICKERS), *WINDOW)

    assert r["passed"]
    assert r["gaps"]["median_gap_sd"].max() == pytest.approx(0.0, abs=1e-9)
    assert r["auc"] == pytest.approx(0.5, abs=0.05)


def test_a_uniform_volume_scale_is_harmless_to_ranked_inputs(conn, paths):
    # dollar volume reaches the model only as a per-date rank, which a vendor
    # reporting everyone's volume at ~half doesn't change
    rng = np.random.default_rng(1)
    for t, (close, volume) in paths.items():
        _store(conn, t, "yfinance", close, volume)
        _store(conn, t, "tiingo", close, volume * rng.uniform(0.45, 0.55))

    r = vc.same_ticker(conn, vc.both_vendor_tickers(conn, TICKERS), *WINDOW)

    assert r["passed"]


def test_vendor_noise_in_closes_fails(conn, paths):
    rng = np.random.default_rng(2)
    for t, (close, volume) in paths.items():
        _store(conn, t, "yfinance", close, volume)
        _store(conn, t, "tiingo", close * (1 + rng.normal(0, 0.01, len(close))), volume)

    r = vc.same_ticker(conn, vc.both_vendor_tickers(conn, TICKERS), *WINDOW)

    assert not r["passed"]
    assert r["gaps"]["median_gap_sd"].max() >= vc.SAME_TICKER_MAX_GAP_SD


def test_only_tickers_on_both_vendors_are_compared(conn, paths):
    close, volume = paths["T0"]
    _store(conn, "T0", "yfinance", close, volume)
    _store(conn, "T0", "tiingo", close, volume)
    _store(conn, "T1", "yfinance", close, volume)

    assert vc.both_vendor_tickers(conn, ["T0", "T1", "T2"]) == ["T0"]

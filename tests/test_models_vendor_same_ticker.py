import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.models import vendor_check as vc
from src.models.features import level_features as lf
from src.models.features import levels

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

    r = vc.same_ticker(conn, vc.both_vendor_tickers(conn, TICKERS), *WINDOW, level_tickers=0)

    assert r["passed"]
    assert r["gaps"]["median_gap_sd"].max() == pytest.approx(0.0, abs=1e-9)
    assert r["auc"] == pytest.approx(0.5, abs=0.05)


def test_the_level_columns_are_compared_on_a_sample(conn, paths):
    for t, (close, volume) in paths.items():
        _store(conn, t, "yfinance", close, volume)
        _store(conn, t, "tiingo", close, volume)

    r = vc.same_ticker(conn, vc.both_vendor_tickers(conn, TICKERS), *WINDOW, level_tickers=8, level_weeks=2,
                       level_warmup_weeks=2)

    assert r["n_level_tickers"] == 8 and r["passed"]   # the AUC's folds need 5+ tickers
    assert {"density_up_2", "near_up_round"} <= set(r["gaps"]["column"])
    assert r["auc_levels"] == pytest.approx(0.5, abs=0.05)
    w = r["level_window"]
    assert w["snapshot_start"] == w["start"] - pd.Timedelta(weeks=2)


def test_the_level_warmup_holds_a_full_strength_window_whatever_the_weekday():
    days = pd.bdate_range("2019-01-01", "2021-12-31")
    days = days[~days.isin(pd.to_datetime(["2019-01-01", "2019-12-25", "2020-01-01", "2020-12-25", "2021-01-01",
                                            "2019-07-04", "2020-07-03", "2021-07-05", "2019-11-28", "2020-11-26",
                                            "2021-11-25", "2019-05-27", "2020-05-25", "2021-05-31", "2019-09-02",
                                            "2020-09-07", "2021-09-06", "2019-04-19", "2020-04-10", "2021-04-02",
                                            "2019-02-18", "2020-02-17", "2021-02-15", "2019-01-21", "2020-01-20",
                                            "2021-01-18"]))]
    for wstart in days[days >= "2021-01-01"]:   # every weekday of a year: each alignment and holiday spacing
        snap_start = wstart - pd.Timedelta(weeks=vc.LEVEL_WARMUP_WEEKS)
        first_held = levels.snapshot_dates(days, snap_start)[0]   # daily rows begin at the first held snapshot
        assert ((days >= first_held) & (days < wstart)).sum() >= lf.STRENGTH_WINDOW


def test_a_vendor_wide_volume_scale_fails_though_ranks_agree(conn, paths):
    # each vendor ranked among its own copies gives equal ranks; in the
    # dataset Tiingo rows are ranked with yfinance rows, so the raw level counts
    for t, (close, volume) in paths.items():
        _store(conn, t, "yfinance", close, volume)
        _store(conn, t, "tiingo", close, volume * 0.5)

    r = vc.same_ticker(conn, vc.both_vendor_tickers(conn, TICKERS), *WINDOW, level_tickers=0)

    gaps = r["gaps"].set_index("column")
    assert gaps.loc["log_dollar_volume_20d_rank", "median_gap_sd"] == pytest.approx(0.0, abs=1e-9)
    assert not r["passed"] and any("log_dollar_volume_20d:" in f for f in r["failures"])


def test_a_tell_on_a_minority_of_tickers_fails_on_the_share_rule(conn, paths):
    rng = np.random.default_rng(3)
    for i, (t, (close, volume)) in enumerate(paths.items()):
        _store(conn, t, "yfinance", close, volume)
        noisy = close * (1 + rng.normal(0, 0.01, len(close))) if i < 2 else close
        _store(conn, t, "tiingo", noisy, volume)

    r = vc.same_ticker(conn, vc.both_vendor_tickers(conn, TICKERS), *WINDOW, level_tickers=0)

    assert not r["passed"]
    assert any("of rows off by" in f for f in r["failures"])


def test_a_column_without_spread_is_marked_not_failed():
    yf = pd.DataFrame({"ticker": ["A", "B"], "date": pd.Timestamp("2020-01-02"), "flat": [1.0, 1.0]})

    gaps = vc.feature_gaps(yf, yf.copy(), ["flat"]).iloc[0]

    assert gaps["no_spread"] and gaps["median_gap_sd"] == 0.0
    assert vc.gate_failures(vc.feature_gaps(yf, yf.copy(), ["flat"]), 0.5) == []


def test_vendor_noise_in_closes_fails(conn, paths):
    rng = np.random.default_rng(2)
    for t, (close, volume) in paths.items():
        _store(conn, t, "yfinance", close, volume)
        _store(conn, t, "tiingo", close * (1 + rng.normal(0, 0.01, len(close))), volume)

    r = vc.same_ticker(conn, vc.both_vendor_tickers(conn, TICKERS), *WINDOW, level_tickers=0)

    assert not r["passed"]
    assert r["gaps"]["median_gap_sd"].max() >= vc.SAME_TICKER_MAX_GAP_SD


def test_only_tickers_on_both_vendors_are_compared(conn, paths):
    close, volume = paths["T0"]
    _store(conn, "T0", "yfinance", close, volume)
    _store(conn, "T0", "tiingo", close, volume)
    _store(conn, "T1", "yfinance", close, volume)

    assert vc.both_vendor_tickers(conn, ["T0", "T1", "T2"]) == ["T0"]


def test_a_scorecards_columns_only(conn, paths, monkeypatch):
    """`specs` limits the gate (and the cache read-outs) to a scorecard's own
    columns, as for a cache built with build-features --scorecard."""
    from src.models import cli
    for t, (close, volume) in paths.items():
        _store(conn, t, "yfinance", close, volume)
        _store(conn, t, "tiingo", close, volume)
    specs = cli.scorecard_specs("HT1")
    r = vc.same_ticker(conn, vc.both_vendor_tickers(conn, TICKERS), *WINDOW, specs=specs)
    # each spec's model input, plus the raw value of a ranked one (`_compare`)
    wanted = {vc.registry.model_input(s) for s in specs} | {s.name for s in specs if s.ranked}
    assert set(r["gaps"]["column"]) | set(r["not_compared"]) == wanted - {"sector"}
    assert r["passed"] and r["n_level_tickers"] == 0                # HT1 has no level columns: no detector runs
    with pytest.raises(ValueError, match="lacks registered columns"):
        vc.run(pd.DataFrame({"ticker": [], "date": []}), pd.DataFrame(), {}, pd.DatetimeIndex([]), pd.Series(),
               specs)


class _Reached(Exception):
    pass


def test_the_command_checks_the_scorecards_columns_over_its_window(conn, monkeypatch):
    from src.models import cli
    with pytest.raises(SystemExit, match="pass --open-holdout --end 2026-08-18"):
        cli.main(["vendor-check", "--db", "x", "--scorecard", "HT1"])          # the dev window only
    seen = {}

    def same_ticker(conn, tickers, start, end, specs=None):
        seen["specs"] = specs
        raise _Reached

    monkeypatch.setattr(cli, "_read_only", lambda path: conn)
    monkeypatch.setattr(vc, "both_vendor_tickers", lambda conn, tickers: ["T0"])
    monkeypatch.setattr(vc, "same_ticker", same_ticker)
    with pytest.raises(_Reached):
        cli.main(["vendor-check", "--db", "x", "--scorecard", "HT1", "--open-holdout", "--end", "2026-08-18"])
    assert seen["specs"] == cli.scorecard_specs("HT1")

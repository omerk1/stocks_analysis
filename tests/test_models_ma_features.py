"""MA-family model features (`features/ma_family.py`), their registry entries, and
the model-feature cache (`features/cache.py`). Leakage for every registered
column is the gate's job (`tests/test_models_gates.py`)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.models import dataset
from src.models.dataset import HoldoutError
from src.models.features import cache, ma_family, registry
from src.models.features.baseline import BASELINE_COLUMNS
from src.signals.moving_averages.features import ribbon

DAYS = pd.bdate_range("2017-01-02", "2021-12-31")


def _bars(seed: int, n: int = len(DAYS), drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    opn = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open": opn, "high": np.maximum(opn, close) * 1.01, "low": np.minimum(opn, close) * 0.99,
        "close": close, "volume": rng.lognormal(14, 0.3, n),
    }, index=DAYS[:n])


# ---------------------------------------------------------------- definitions

def test_columns_are_the_registered_ma_group():
    names = {s.name for s in registry.model_specs(group="ma")}
    assert names == set(ma_family.MA_COLUMNS) | {"log_dollar_volume_20d"}
    assert {s.name for s in registry.model_specs("ma", ("supported",))} == {"slope_log_21_sma_50",
                                                                           "ribbon_agreement_state"}
    registry.check_columns([registry.model_input(s) for s in registry.model_specs()])
    for cols in BASELINE_COLUMNS.values():
        registry.check_columns(cols)


def test_undefined_until_every_input_exists():
    """Comparison-built columns are NaN in their inputs' warmup, not False/0
    (CLAUDE.md invariant #9)."""
    f = ma_family.ticker_features(_bars(1))
    assert f["stack_fully_bearish"].iloc[:199].isna().all() and f["stack_fully_bearish"].iloc[199:].notna().all()
    assert f["ribbon_agreement_state"].iloc[:220].isna().all() and f["ribbon_agreement_state"].iloc[220:].notna().all()
    assert set(f["ribbon_agreement_state"].dropna().unique()) <= {0, 1, 2, 3, 4, 5}


def test_scale_free():
    """A constant rescaling of the whole history (what a later split or dividend
    does to adjusted prices) leaves every column unchanged."""
    bars = _bars(2)
    scaled = bars.assign(**{c: bars[c] * 0.37 for c in ("open", "high", "low", "close")})
    pd.testing.assert_frame_equal(ma_family.ticker_features(bars), ma_family.ticker_features(scaled), rtol=1e-5)


def test_ribbon_width_pctile_matches_the_study():
    bars = _bars(3)
    sma = {k: bars["close"].rolling(k).mean() for k in ma_family.RIBBON_WIDTH_LOOKBACKS}
    panel = pd.DataFrame({f"sma_{k}": v for k, v in sma.items()})
    study = ribbon.ribbon_width_pctile(ribbon.ribbon_width(panel), pd.Series("X", index=panel.index))
    ours = ma_family.ticker_features(bars)["ribbon_width_pctile"]
    np.testing.assert_allclose(ours.to_numpy(), study.to_numpy(dtype="float32"), rtol=1e-4, equal_nan=True)


def test_stack_bearish_on_a_decline_not_a_rise():
    late = lambda drift: ma_family.ticker_features(_bars(4, drift=drift))["stack_fully_bearish"].iloc[-100:].mean()
    assert late(-0.004) > 0.6 and late(0.004) == 0.0


# ---------------------------------------------------------------- cache

@pytest.fixture
def conn():
    c = db.get_connection(":memory:")
    db.create_tables(c)
    for i, ticker in enumerate(["AAA", "BBB", "CCC", "DDD"]):
        bars = _bars(10 + i)
        volume = 2_000_000 if ticker != "DDD" else 1_000  # DDD fails the liquidity floor
        for source in (db.YFINANCE, db.YFINANCE_SPLIT_ONLY):
            db.upsert_bars(c, "bars_1d", ticker, source, bars.assign(volume=volume, is_partial=0))
    db.replace_index_membership(c, "sp500", pd.DataFrame(
        [(t, "2015-01-01", None) for t in ["AAA", "BBB", "CCC", "DDD"]], columns=["ticker", "start_date", "end_date"]))
    c.execute("INSERT INTO ticker_sector (ticker, sector, industry, updated_at) "
              "VALUES ('AAA', 'Technology', NULL, 'x'), ('BBB', 'Energy', NULL, 'x')")
    yield c
    c.close()


def test_cache_holds_eligible_rows_ranked_among_themselves(conn, tmp_path):
    universe = dataset.universe_mask(conn, "2020-01-01", "2021-12-31")
    cache.build_feature_cache(conn, universe, tmp_path)
    f = cache.read_feature_cache(tmp_path)
    eligible = universe[universe["eligible"]]
    assert len(f) == len(eligible) and "DDD" not in set(f["ticker"])
    # Warmup came from bars before `start`: the slowest columns are defined from day one.
    assert f["dist_z_sma_200"].notna().all() and f["ribbon_width_pctile"].notna().all()
    # Ranks are over the eligible names only (three per date here).
    ranks = f["slope_log_21_sma_50_rank"].to_numpy(dtype=float)
    assert np.isclose(ranks[:, None], [1 / 3, 2 / 3, 1.0], atol=1e-6).any(axis=1).all()
    assert (f.loc[f["ticker"] == "AAA", "sector"] == "Technology").all()
    assert f.loc[f["ticker"] == "CCC", "sector"].isna().all()
    manifest = f.attrs["manifest"]
    assert manifest["columns"]["slope_log_21_sma_50"]["prior"] == "supported"
    assert manifest["price_sources"]["total_return"] == {db.YFINANCE: 3}  # bars are read for eligible tickers only


def test_cache_refuses_the_holdout(conn, tmp_path):
    universe = dataset.universe_mask(conn, "2021-06-01", "2021-12-31")
    universe = pd.concat([universe, universe.tail(1).assign(date=pd.Timestamp("2022-01-03"))])
    with pytest.raises(HoldoutError):
        cache.build_feature_cache(conn, universe, tmp_path)


# ---------------------------------------------------------------- vendor check

def test_vendor_check_pieces():
    from src.models import vendor_check as vc
    days = pd.bdate_range("2015-01-02", "2019-12-31")
    sources = {"OLD": db.TIINGO, "NEW": db.YFINANCE}
    bars = pd.concat([
        _bars(1, len(days)).set_axis(days).assign(ticker="NEW").rename_axis("date").reset_index(),
        _bars(2, 500).set_axis(days[:500]).assign(ticker="OLD", volume=0.0).rename_axis("date").reset_index(),
    ])
    fp = vc.fingerprints(bars, sources, days)
    assert fp.loc["tiingo", "zero_volume_share"] == 1.0 and fp.loc["yfinance", "zero_volume_share"] == 0.0
    feats = bars[["ticker", "date"]].assign(x=np.random.default_rng(0).normal(size=len(bars)))
    rows = vc.tag_rows(feats, sources, bars.groupby("ticker")["date"].max())
    old = rows[rows["ticker"] == "OLD"]
    last = old["date"].max()
    # Far = at least FAR_DAYS before the delisted ticker's last bar; every yfinance row is far.
    assert (old["far"] == ((last - old["date"]).dt.days >= vc.FAR_DAYS)).all()
    assert rows.loc[rows["ticker"] == "NEW", "far"].all()


def test_vendor_auc_is_chance_on_noise_and_high_on_an_artefact():
    from src.models import vendor_check as vc
    rng = np.random.default_rng(0)
    tickers = np.repeat([f"T{i}" for i in range(40)], 300)
    tiingo = np.repeat(np.arange(40) < 10, 300)
    rows = pd.DataFrame({"ticker": tickers, "tiingo": tiingo, "noise": rng.normal(size=len(tickers))})
    assert abs(vc.vendor_auc(rows, ["noise"]) - 0.5) < 0.05
    rows["artefact"] = rows["noise"] + 2.0 * rows["tiingo"]
    assert vc.vendor_auc(rows, ["artefact"]) > 0.8

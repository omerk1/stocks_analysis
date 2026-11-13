"""scripts/scorecard_noise_coverage.py: one noise run is scored as HT1 judges
(gross), and the pre-committed rule picks the interval level from the H = 63
exclusion rates."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from src.models import trading

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "scorecard_noise_coverage.py"
spec = importlib.util.spec_from_file_location("scorecard_noise_coverage", SCRIPT)
noise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(noise)


def test_the_noise_scorecard_is_ht1s_but_gross_on_dev_years():
    sc, ht1 = noise.scorecard(63), trading.PREREGISTERED["HT1"]
    assert (sc.model_columns, sc.reference_columns, sc.rank, sc.verdict_against, sc.verdict_k) == (
        ht1.model_columns, ht1.reference_columns, ht1.rank, ht1.verdict_against, ht1.verdict_k)
    assert sc.verdict_cost_bps == 0 and not sc.open_holdout and max(sc.test_years) <= 2021
    assert [(c.upper, c.lower) for c in sc.cells(63)] == [noise.CELL]


def test_one_run_on_a_small_panel():
    r = noise.one_run(21, seed=0, n_tickers=24, n_boot=200)
    assert r["dates_missing_a_cell"] == 0 and r["n_blocks"] > 20
    assert np.isfinite(r["z"]) and 0 < r["p_positive"] <= 1
    # wider intervals leave out zero no more often than narrower ones
    flags = [r[f"excludes_{level:g}"] for level in noise.LEVELS]
    assert flags == sorted(flags, reverse=True)


def _runs(h63_excluding: dict[float, int], n: int | None = None, **settings) -> pd.DataFrame:
    n = noise.SEEDS[63] if n is None else n
    rows = pd.DataFrame({"horizon": 63, "seed": range(n), "n_tickers": settings.get("n_tickers", noise.N_TICKERS),
                         "n_boot": settings.get("n_boot", trading.PREREGISTERED["HT1"].n_boot),
                         "z": 0.0, "p_positive": 0.5, "n_blocks": 9.4})
    for level in noise.LEVELS:
        rows[f"excludes_{level:g}"] = np.arange(n) < h63_excluding.get(level, 0)
    return rows


def test_seeds_are_independent_streams():
    assert len(set(noise.streams(0))) == 4 and noise.streams(0) != noise.streams(1)


def test_cell_baskets_is_the_picks_and_every_sides_basket_net_of_its_cost():
    """What close_scorecard used to compute inline, now shared with the noise check."""
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2019-01-02", periods=3)
    frame = pd.DataFrame({"ticker": np.tile(list("ABCDEFGH"), 3), "date": np.repeat(dates, 8),
                          "ret": rng.normal(0, 0.02, 24), "hit": rng.integers(-1, 2, 24),
                          "atr": rng.uniform(1, 3, 24), "close_t": 100.0, "fold": 2019})
    probs = rng.dirichlet([1, 1, 1], 24)
    p = frame[["ticker", "date", "fold"]].assign(p_down=probs[:, 0], p_neither=probs[:, 1], p_up=probs[:, 2])
    preds = pd.concat([p.assign(model="model"), p.assign(model="B4")], ignore_index=True)
    sc = trading.Scorecard(verdict_k=3, ks=(3,), verdict_cost_bps=10, track="A")
    cell = sc.cells(21)[0]
    neither = {2019: 0.0}
    import unittest.mock as mock
    with mock.patch.object(trading, "neither_returns", lambda f, folds: neither), \
         mock.patch.object(trading, "neither_atr_returns", lambda f, folds: neither), \
         mock.patch.object(trading, "walk_forward_folds", lambda *a: []):
        picked, baskets = trading.cell_baskets(sc, cell, preds, frame)
        expect = trading.cell_picks(sc, cell, preds, frame, 3)
    assert set(picked) == {"model", "reference"} and set(baskets) == {"model", "reference", "market", "low_vol"}
    for side in ("model", "reference"):
        pd.testing.assert_frame_equal(picked[side], expect[side])
        pd.testing.assert_series_equal(baskets[side], trading.basket(expect[side], 10))
    pd.testing.assert_series_equal(baskets["market"], frame.groupby("date")["ret"].mean())   # no cost


def test_only_registered_runs_count():
    smoke = _runs({0.99: 50}, n=20, n_boot=200)                 # every one "leaves out zero"
    full = _runs({0.99: 2})
    assert noise.summary(pd.concat([smoke, full]))[63]["exclusion"][0.99]["k"] == 2
    partial = noise.verdict(noise.summary(_runs({}, n=30)))
    assert partial.startswith("incomplete: 30 of")
    extra = _runs({0.99: 0}, n=noise.SEEDS[63] + 50)             # seeds past the count don't count
    assert noise.summary(extra)[63]["runs"] == noise.SEEDS[63]


def test_the_rule():
    assert noise.SEEDS[63] == 1000
    keep = noise.verdict(noise.summary(_runs({0.99: 20, 0.995: 10, 0.999: 2})))     # 2.0%: at the line
    assert keep == "HT1 keeps its registered 99% interval"
    widen = noise.verdict(noise.summary(_runs({0.99: 21, 0.995: 20, 0.999: 5})))    # 2.1%, then 2.0%
    assert "becomes 99.5% at both horizons, with 20,000 draws" in widen
    widen_more = noise.verdict(noise.summary(_runs({0.99: 40, 0.995: 30, 0.999: 20})))
    assert "becomes 99.9% at both horizons, with 100,000 draws" in widen_more
    stop = noise.verdict(noise.summary(_runs({0.99: 60, 0.995: 45, 0.999: 30})))
    assert stop.startswith("even 99.9%") and "stop" in stop


def test_wilson_brackets_the_share():
    lo, hi = noise.wilson(4, 200)
    assert lo < 0.02 < hi and lo > 0

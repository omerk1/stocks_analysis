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
    assert (sc.model_columns, sc.reference_columns, sc.rank, sc.verdict_against) == (
        ht1.model_columns, ht1.reference_columns, ht1.rank, ht1.verdict_against)
    assert sc.verdict_cost_bps == 0 and not sc.open_holdout and max(sc.test_years) <= 2021
    assert [(c.upper, c.lower) for c in sc.cells(63)] == [noise.CELL]


def test_one_run_on_a_small_panel():
    r = noise.one_run(21, seed=0, n_tickers=24, n_boot=200)
    assert r["dates_missing_a_cell"] == 0 and r["n_blocks"] > 20
    assert np.isfinite(r["z"]) and 0 < r["p_positive"] <= 1
    # wider intervals leave out zero no more often than narrower ones
    flags = [r[f"excludes_{level:g}"] for level in noise.LEVELS]
    assert flags == sorted(flags, reverse=True)


def _runs(h63_excluding: dict[float, int], n: int = 200) -> pd.DataFrame:
    rows = pd.DataFrame({"horizon": 63, "seed": range(n), "z": 0.0, "p_positive": 0.5, "n_blocks": 9.4})
    for level in noise.LEVELS:
        rows[f"excludes_{level:g}"] = np.arange(n) < h63_excluding.get(level, 0)
    return rows


def test_the_rule():
    keep = noise.verdict(noise.summary(_runs({0.99: 4, 0.995: 2, 0.999: 0})))      # 2.0%: at the line
    assert keep == "HT1 keeps its registered 99% interval at H = 63"
    widen = noise.verdict(noise.summary(_runs({0.99: 7, 0.995: 4, 0.999: 1})))     # 3.5%, then 2.0%
    assert "becomes 99.5%" in widen
    widen_more = noise.verdict(noise.summary(_runs({0.99: 9, 0.995: 6, 0.999: 3})))
    assert "becomes 99.9%" in widen_more
    stop = noise.verdict(noise.summary(_runs({0.99: 20, 0.995: 15, 0.999: 10})))
    assert stop.startswith("even 99.9%") and "stop" in stop


def test_wilson_brackets_the_share():
    lo, hi = noise.wilson(4, 200)
    assert lo < 0.02 < hi and lo > 0

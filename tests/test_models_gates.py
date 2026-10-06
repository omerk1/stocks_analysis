"""The four harness gates (`docs/modeling/VALIDATION_HARNESS.md` §8), at the quick
size, plus the pieces they're built from. The gates' pass/fail logic is
`gates.*_verdict`, the same functions `python -m src.models.cli run-gates` uses.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
import pytest

from src.models import gates, synthetic
from src.models.features import registry
from src.models.features.baseline import BASELINE_COLUMNS


def _failed(verdict: dict[str, bool]) -> list[str]:
    return [check for check, ok in verdict.items() if not ok]


# ---------------------------------------------------------------- synthetic data

def test_planted_panel_shape_and_truth():
    spec = synthetic.PlantedSpec(n_tickers=60, start="2017-01-03")
    panel = synthetic.planted_panel(spec)
    resolved = panel.dropna(subset=["hit"])
    # The true probabilities move by exactly delta with x.
    up = panel.groupby(panel["x"] > 0)["p_up_true"].mean()
    assert up[True] - up[False] == pytest.approx(spec.delta, abs=0.005)
    # Delisted tickers: some windows end early, on the ticker's last row.
    last = panel.groupby("ticker")["date"].max()
    assert resolved["truncated"].any()
    trunc = resolved[resolved["truncated"]]
    assert (trunc["label_end_date"].to_numpy() == last.reindex(trunc["ticker"]).to_numpy()).all()
    assert (resolved["label_end_date"] > resolved["date"]).all()
    # A window running past the calendar's end is unresolved, as at the holdout boundary.
    assert panel.loc[panel["date"] == panel["date"].max(), "hit"].isna().all()


def test_oracle_gains_match_the_generator():
    """The closed forms vs the generator's own probabilities: the Brier gain of
    E[p | feature] over a constant is minus the summed variance of E[p | feature]."""
    spec = synthetic.PlantedSpec(n_tickers=400, start="2016-01-04")
    panel = synthetic.planted_panel(spec).dropna(subset=["x_stale"])
    s = (panel["x"] > 0).astype(float)
    assert -2 * (spec.delta ** 2) * s.var() == pytest.approx(synthetic.oracle_brier_gain(spec.delta), rel=0.02)
    c = spec.rho / math.sqrt(1 - spec.rho ** 2)
    g = pd.Series(np.vectorize(lambda v: 0.5 * math.erfc(-c * v / math.sqrt(2)))(panel["x_stale"]))
    empirical = -2 * spec.delta ** 2 * g.var()
    assert empirical == pytest.approx(synthetic.oracle_stale_brier_gain(spec.delta, spec.rho), rel=0.03)
    # And g really is P(x_t > 0 | x_{t-1}).
    assert np.corrcoef(g, s)[0, 1] ** 2 * s.var() == pytest.approx(g.var(), rel=0.05)


def test_shuffle_within_date_keeps_each_dates_outcomes():
    panel = synthetic.planted_panel(synthetic.PlantedSpec(n_tickers=30, start="2020-01-02"))
    shuffled = synthetic.shuffle_within_date(panel, seed=3)
    for col in ("hit", "ret"):
        a = panel.groupby("date")[col].apply(lambda v: sorted(v.fillna(9)))
        b = shuffled.groupby("date")[col].apply(lambda v: sorted(v.fillna(9)))
        assert a.equals(b)
    assert (panel["hit"].fillna(9) != shuffled["hit"].fillna(9)).mean() > 0.3
    # hit and ret move together.
    pairs = lambda f: f.dropna(subset=["hit"]).groupby("hit")["ret"].apply(lambda r: (r > 0).mean())
    assert pairs(shuffled)[1.0] == 1.0 and pairs(shuffled)[-1.0] == 0.0


# ---------------------------------------------------------------- registry

def test_every_baseline_column_is_registered():
    for columns in BASELINE_COLUMNS.values():
        registry.check_columns(columns)


def test_unregistered_model_columns_are_refused():
    with pytest.raises(ValueError, match="unregistered"):
        registry.check_columns(["mom_12_1_rank", "my_new_feature"])
    with pytest.raises(ValueError, match="unregistered"):
        registry.check_columns(["dollar_volume_20d"])  # a universe filter, not a model input


# ---------------------------------------------------------------- the gates

@pytest.fixture(scope="module")
def planted():
    warnings.filterwarnings("ignore")
    return gates.planted_and_shuffle_gates(gates.QUICK)


def test_gate_1_planted_effect(planted):
    # The one-bar-late amount is checked at the FULL size only (`planted_verdict`).
    assert not _failed(gates.planted_verdict(planted, check_stale_amount=False))
    assert planted["uplift"]["x"].point_estimate == pytest.approx(planted["expected_uplift"]["x"], abs=0.01)


def test_gate_2_label_shuffle(planted):
    assert not _failed(gates.shuffle_verdict(planted))


def test_gate_3_leakage_on_synthetic_bars():
    bars, splits, cut = gates.synthetic_leakage_inputs()
    result = gates.leakage_gate(bars, splits, cut)
    assert not _failed(gates.leakage_verdict(result))
    assert set(result["columns"]) >= {"mom_12_1_rank", "dollar_volume_20d", "history_eligible", "atr_pct"}
    assert result["not_bar_derived"] == ["sector"]


def test_gate_3_catches_an_unsafe_registered_feature():
    """Registering a feature that reads an adjusted price level makes the gate fail."""
    bars, splits, cut = gates.synthetic_leakage_inputs()
    unsafe = registry.FeatureSpec("sma_50_level", "test", registry.MODEL, "dense", None, "level", 50)
    sources = {**registry.SOURCES, "level": registry.Source(
        registry.PriceBasis.TOTAL_RETURN, lambda b, s: pd.DataFrame({"sma_50_level": b["close"].rolling(50).mean()}))}
    original = registry.SOURCES
    try:
        registry.SOURCES = sources
        result = gates.leakage_gate(bars, splits, cut, registry=registry.REGISTRY + (unsafe,))
    finally:
        registry.SOURCES = original
    failed = _failed(gates.leakage_verdict(result))
    assert "future_split_no_leak" in failed and "future_dividend_no_leak" in failed
    assert "future_path_no_leak" not in failed


def test_gate_3_catches_atr_masked_by_the_label():
    """The label cache's `atr` is NaN where bar t+1 is missing -- future
    information. Registered as a feature, the delisting perturbation catches it."""
    from src.models.labels.barriers import BarrierCell, barrier_labels
    bars, splits, cut = gates.synthetic_leakage_inputs()

    def masked_atr(b, s):
        labels = barrier_labels(b.reset_index().assign(ticker="_"), [BarrierCell(1, 1.0, 1.0)])
        return pd.DataFrame({"masked_atr": labels["atr"].to_numpy()}, index=b.index)

    unsafe = registry.FeatureSpec("masked_atr", "test", registry.MODEL, "dense", None, "masked", 15)
    original = registry.SOURCES
    try:
        registry.SOURCES = {**original, "masked": registry.Source(registry.PriceBasis.TOTAL_RETURN, masked_atr)}
        result = gates.leakage_gate(bars, splits, cut, registry=registry.REGISTRY + (unsafe,))
    finally:
        registry.SOURCES = original
    assert result["leaks"]["future_delisting"] == {"masked_atr": result["leaks"]["future_delisting"]["masked_atr"]}
    assert not result["leaks"]["future_path"]


def test_boosted_model_refuses_unregistered_columns():
    from src.models.learners import BoostedModel
    with pytest.raises(ValueError, match="unregistered"):
        BoostedModel(["mom_12_1_rank", "x"])
    BoostedModel(["mom_12_1_rank", "x"], registered_only=False)


def test_gate_4_purge():
    result = gates.purge_gate(n_tickers=12, test_years=gates.QUICK.test_years,
                              first_train_start=gates.QUICK.first_train_start)
    assert not _failed(gates.purge_verdict(result))

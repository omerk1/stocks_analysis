"""Tests for M16's linear-filter diagnostic module."""

from __future__ import annotations

import numpy as np

from src.signals.moving_averages.modules import linear_filter_diagnostic as lfd


def test_candidate_rules_covers_expected_names():
    rules = lfd.candidate_rules()
    assert "dist_pct_sma_20" in rules
    assert "dist_pct_ema_200" in rules
    assert "slope_log_21_sma_50" in rules
    assert "mom_12_1" in rules
    assert "mom_1_0" in rules
    assert "crossover_sma_50_sma_200" in rules
    # 8 dist_pct + 8 slope + 2 momentum + 5 crossover
    assert len(rules) == 23


def test_kernel_table_has_finite_centroids_for_every_rule():
    table = lfd.kernel_table()
    assert len(table) == 23
    assert table["centroid"].notna().all()
    # every centroid should sit well inside the 400-bar max_lag window
    assert (table["centroid"] > 0).all()
    assert (table["centroid"] < lfd.MAX_LAG).all()


def test_golden_cross_pair_sma_50_200_has_a_long_centroid_matching_its_slow_leg():
    """The classic 50/200 crossover spread's own kernel should be dominated
    by the slower (200-day) leg's own contribution -- its centroid should
    sit well above the fast-only dist_pct_sma_50's own centroid, and in the
    same rough neighborhood as a 200-day construction's, not the other way
    around (a data-shape sanity check, not a precise numeric claim).
    """
    rules = lfd.candidate_rules()
    table = lfd.kernel_table(rules)
    by_name = table.set_index("name")
    crossover_centroid = by_name.loc["crossover_sma_50_sma_200", "centroid"]
    dist_50_centroid = by_name.loc["dist_pct_sma_50", "centroid"]
    assert crossover_centroid > dist_50_centroid


def test_dist_pct_centroid_increases_with_lookback():
    """A longer SMA's own distance measure should have a longer effective
    lookback (larger centroid) than a shorter one -- monotonicity check
    across this study's own 4 cached lookbacks.
    """
    rules = lfd.candidate_rules()
    table = lfd.kernel_table(rules).set_index("name")
    centroids = [table.loc[f"dist_pct_sma_{lb}", "centroid"] for lb in lfd.SMA_EMA_LOOKBACKS]
    assert centroids == sorted(centroids)


def test_weight_vectors_returns_same_names_as_kernel_table():
    rules = lfd.candidate_rules()
    vectors = lfd.weight_vectors(rules)
    table = lfd.kernel_table(rules)
    assert set(vectors) == set(table["name"])
    for weights in vectors.values():
        assert len(weights) == lfd.MAX_LAG

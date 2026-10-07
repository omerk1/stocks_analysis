"""Unit tests for the DC-B1/DC-B2 run script's pure pieces -- panel
assembly, the cluster-robust interaction, verdict mapping, plateau
classification. The registered readout itself runs only against the real
DB with --unblind; these tests never touch outcomes semantics beyond
hand-built toy frames."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.divergence_trackb_run import (
    HURDLE,
    assemble_panel,
    classify_with,
    cluster_robust_interaction,
    per_event_deltas,
    plateau_gate,
    shape_stats,
    verdict,
)


def _panel_rows():
    events = pd.DataFrame(
        [
            {"id": "e1", "ticker": "A", "p2_date": "2015-03-10", "confirmed_at": "2015-03-12",
             "direction": "bearish", "context_class": "extension", "p2_month": "2015-03",
             "interpeak_retrace_frac": 0.1, "leg2_bars": 2},
        ]
    )
    controls = pd.DataFrame(
        [
            {"id": "c1", "ticker": "B", "p2_date": "2015-03-11", "confirmed_at": "2015-03-13",
             "direction": "bearish", "context_class": "extension", "p2_month": "2015-03",
             "interpeak_retrace_frac": 0.12, "leg2_bars": 3},
            {"id": "c2", "ticker": "C", "p2_date": "2015-03-12", "confirmed_at": "2015-03-14",
             "direction": "bearish", "context_class": "extension", "p2_month": "2015-03",
             "interpeak_retrace_frac": 0.11, "leg2_bars": 2},
        ]
    )
    matches = pd.DataFrame(
        [
            {"event_id": "e1", "control_id": "c1", "rank": 1},
            {"event_id": "e1", "control_id": "c2", "rank": 2},
        ]
    )
    return events, controls, matches


def test_assemble_panel_builds_event_strata():
    events, controls, matches = _panel_rows()
    events = events.assign(is_divergence=True)
    controls = controls.assign(is_divergence=False)
    panel = assemble_panel(events, controls, matches)

    assert len(panel) == 3
    assert panel["match_group"].nunique() == 1  # one stratum: e1 + its 2 controls
    assert set(panel.loc[panel["is_divergence"], "id"]) == {"e1"}
    assert set(panel.loc[~panel["is_divergence"], "id"]) == {"c1", "c2"}
    assert (panel["match_group"] == "e1").all()


def test_cluster_robust_interaction_recovers_a_planted_slope():
    # y = 0 + 0*d + 0*r + B3*(d*r) exactly, two months of rows: the OLS
    # must recover B3 with a tiny CI and the clustered p near zero.
    rng = np.random.default_rng(0)
    rows = []
    for month in ("2015-03", "2015-04"):
        for i in range(60):
            d = i % 2
            r = rng.uniform(0, 1)
            y = 0.004 * d * r + rng.normal(0, 1e-6)
            rows.append({"id": f"{month}-{i}", "p2_date": f"{month}-{(i % 28) + 1:02d}",
                         "direction": "bearish", "p2_month": month, "is_divergence": bool(d),
                         "interpeak_retrace_frac": r, "fwd_log_ret_63": y})
    panel = pd.DataFrame(rows)

    res = cluster_robust_interaction(panel, "bearish", 63)

    assert res["point_estimate"] == pytest.approx(0.004, rel=0.01)
    assert res["p_value"] < 0.01
    assert res["n_dates"] == 2


def test_verdict_mapping_matches_the_frozen_three_way_rules():
    tight_null = {"point_estimate": 0.0002, "ci_low": -0.0008, "ci_high": 0.0011}
    assert verdict(tight_null, bh_pass=False, plateau_ok=True, formulations_agree=True) == "dead_demonstrated_null"

    wide = {"point_estimate": 0.001, "ci_low": -0.01, "ci_high": 0.012}
    assert verdict(wide, bh_pass=False, plateau_ok=True, formulations_agree=True) == "inconclusive_underpowered"

    strong = {"point_estimate": 0.006, "ci_low": 0.003, "ci_high": 0.009}
    assert verdict(strong, bh_pass=True, plateau_ok=True, formulations_agree=True) == "alive"
    # The gates demote an otherwise-Alive cell, never resurrect a dead one.
    assert verdict(strong, bh_pass=True, plateau_ok=False, formulations_agree=True) == "inconclusive_gate_failed"
    assert verdict(strong, bh_pass=True, plateau_ok=True, formulations_agree=False) == "inconclusive_gate_failed"
    # BH failure with a wide CI is underpowered, not dead.
    assert verdict(strong, bh_pass=False, plateau_ok=True, formulations_agree=True) == "inconclusive_underpowered"
    # Hurdle: significant but economically too small, CI inside the band -> dead.
    small = {"point_estimate": 0.0008, "ci_low": 0.0003, "ci_high": 0.0013}
    assert max(abs(small["ci_low"]), abs(small["ci_high"])) < HURDLE
    assert verdict(small, bh_pass=True, plateau_ok=True, formulations_agree=True) == "dead_demonstrated_null"


def test_plateau_gate_finite_agreement_semantics():
    # All finite, same sign -> ok; NaN neighbors are absence of evidence.
    ok, n = plateau_gate([0.01, 0.02, float("nan"), 0.005])
    assert ok and n == 3
    # Any sign disagreement among finite neighbors fails.
    ok, n = plateau_gate([0.01, -0.001, 0.02])
    assert not ok and n == 3
    # Nothing computable: fail with zero finite (never a silent pass).
    ok, n = plateau_gate([float("nan")] * 9)
    assert not ok and n == 0


def test_per_event_deltas_and_shape_stats():
    panel = pd.DataFrame(
        [
            {"match_group": "e1", "is_divergence": True, "context_class": "extension", "fwd_log_ret_63": 0.05},
            {"match_group": "e1", "is_divergence": False, "context_class": "extension", "fwd_log_ret_63": 0.01},
            {"match_group": "e1", "is_divergence": False, "context_class": "extension", "fwd_log_ret_63": 0.03},
            {"match_group": "e2", "is_divergence": True, "context_class": "pullback_rebuild", "fwd_log_ret_63": -0.02},
            {"match_group": "e2", "is_divergence": False, "context_class": "pullback_rebuild", "fwd_log_ret_63": 0.00},
        ]
    )
    deltas = per_event_deltas(panel, 63)

    by = dict(zip(deltas["match_group"], deltas["delta"]))
    assert by["e1"] == pytest.approx(0.05 - 0.02)  # event minus MEAN of its controls
    assert by["e2"] == pytest.approx(-0.02)

    stats = shape_stats(pd.Series([0.03, -0.02, 0.01, -0.01, 0.02]))
    assert stats["hit"] == pytest.approx(3 / 5)
    assert stats["wl"] == pytest.approx((0.02) / 0.015)  # mean win / |mean loss|
    assert np.isfinite(stats["skew"])


def test_classify_with_reproduces_the_frozen_poles_at_registered_thresholds():
    cls = classify_with(0.33, 5)
    assert cls(0.2, 2) == "extension"
    assert cls(0.4, 6) == "pullback_rebuild"
    assert cls(0.4, 3) is None       # deep-fast
    assert cls(0.29, 10) is None     # buffer band
    assert cls(float("nan"), 6) is None
    # A plateau neighbor widens/narrows only the pullback pole; the
    # extension edge stays the frozen 0.25.
    wide = classify_with(0.50, 8)
    assert wide(0.4, 10) is None
    assert wide(0.55, 10) == "pullback_rebuild"
    assert wide(0.2, 2) == "extension"

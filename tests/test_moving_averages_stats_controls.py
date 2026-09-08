"""Tests for the C2 matched-control infrastructure added for M4
(`cross_sectional_bucket`, `c2_delta` -- see PREREGISTRATION.md). C0/C1
are already covered in `test_moving_averages_synthetic_validation.py`
(Phase 1's gate); this file is specifically the new C2 surface.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.signals.moving_averages.stats.controls import c2_delta, cross_sectional_bucket, stratum_deltas


def test_cross_sectional_bucket_ranks_within_each_date_independently():
    panel = pd.DataFrame(
        {
            "date": ["d1", "d1", "d1", "d1", "d2", "d2", "d2", "d2"],
            "value": [1.0, 2.0, 3.0, 4.0, 100.0, 200.0, 300.0, 400.0],
        }
    )

    bucket = cross_sectional_bucket(panel, "value", date_col="date", n_buckets=4)

    # Same rank pattern on both dates despite wildly different absolute scale.
    assert bucket.iloc[0:4].tolist() == [0, 1, 2, 3]
    assert bucket.iloc[4:8].tolist() == [0, 1, 2, 3]


def test_cross_sectional_bucket_is_nan_for_missing_values():
    panel = pd.DataFrame({"date": ["d1", "d1", "d1"], "value": [1.0, None, 3.0]})

    bucket = cross_sectional_bucket(panel, "value", date_col="date", n_buckets=2)

    assert pd.isna(bucket.iloc[1])


def test_c2_delta_is_not_diluted_and_matches_within_stratum_only():
    """Two dates, two sectors each with an event/control pair. True
    within-stratum difference is +10 everywhere; a cross-stratum-blind
    computation (e.g. accidentally averaging event vs. the whole date,
    ignoring sector) would come back wrong, since sector B's absolute
    level is far higher than sector A's -- if match_cols weren't actually
    doing the matching, the result would be dominated by the huge B-A
    level gap instead of the true +10 within-stratum effect.
    """
    panel = pd.DataFrame(
        {
            "date": ["d1", "d1", "d1", "d1", "d2", "d2", "d2", "d2"],
            "sector": ["A", "A", "B", "B", "A", "A", "B", "B"],
            "is_event": [True, False, True, False, True, False, True, False],
            "value": [15.0, 5.0, 1015.0, 1005.0, 25.0, 15.0, 1025.0, 1015.0],
        }
    )

    delta = c2_delta(panel, group_col="is_event", value_col="value", match_cols=["sector"], date_col="date")

    assert delta == pytest.approx(10.0)


def test_c2_delta_drops_strata_with_no_control_or_no_event_rows():
    panel = pd.DataFrame(
        {
            "date": ["d1", "d1", "d1"],
            "sector": ["A", "A", "B"],
            "is_event": [True, False, True],  # sector B has no control row
            "value": [20.0, 10.0, 999.0],
        }
    )

    delta = c2_delta(panel, group_col="is_event", value_col="value", match_cols=["sector"], date_col="date")

    # Only sector A's stratum has both an event and a control row.
    assert delta == pytest.approx(10.0)


def test_c2_delta_uses_multiple_match_columns_jointly():
    # Two match columns; event/control pairs only share both mom and vol
    # bucket within the same row-pair -- confirms match_cols is a genuine
    # joint key, not just the first column.
    panel = pd.DataFrame(
        {
            "date": ["d1"] * 4,
            "mom_bucket": [0, 0, 1, 1],
            "vol_bucket": [0, 0, 0, 0],
            "is_event": [True, False, True, False],
            "value": [12.0, 2.0, 55.0, 5.0],
        }
    )

    delta = c2_delta(
        panel, group_col="is_event", value_col="value", match_cols=["mom_bucket", "vol_bucket"], date_col="date"
    )

    # (12-2 + 55-5) / 2 = 30.0
    assert delta == pytest.approx(30.0)


def test_stratum_deltas_mean_matches_c2_delta_directly():
    # stratum_deltas is the shared primitive c1_delta/c2_delta are built
    # on (see controls.py's module docstring) -- pin that they can't drift
    # apart.
    panel = pd.DataFrame(
        {
            "date": ["d1", "d1", "d1", "d1", "d2", "d2", "d2", "d2"],
            "sector": ["A", "A", "B", "B", "A", "A", "B", "B"],
            "is_event": [True, False, True, False, True, False, True, False],
            "value": [15.0, 5.0, 1015.0, 1005.0, 25.0, 15.0, 1025.0, 1015.0],
        }
    )

    deltas = stratum_deltas(panel, "is_event", "value", ["date", "sector"])
    direct = c2_delta(panel, "is_event", "value", match_cols=["sector"], date_col="date")

    assert deltas["delta"].mean() == pytest.approx(direct)

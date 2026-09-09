"""Tests for the C2 matched-control infrastructure added for M4
(`cross_sectional_bucket`, `c2_delta` -- see PREREGISTRATION.md). C0/C1
are already covered in `test_moving_averages_synthetic_validation.py`
(Phase 1's gate); this file is specifically the new C2 surface.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.signals.moving_averages.stats.controls import (
    c0_delta,
    c1_delta,
    c2_delta,
    pooled_delta,
    c2_eligible_mask,
    cross_sectional_bucket,
    stratum_deltas,
)


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


# ---- c2_eligible_mask (M1's waterfall row-set fix, PREREGISTRATION.md) ----

def test_c2_eligible_mask_drops_rows_missing_a_match_col():
    panel = pd.DataFrame(
        {
            "date": ["d1", "d1", "d1"],
            "sector": ["A", "A", None],  # third row missing its match col
            "is_event": [True, False, True],
            "value": [15.0, 5.0, 999.0],
        }
    )

    mask = c2_eligible_mask(panel, "is_event", "value", match_cols=["sector"], date_col="date")

    assert mask.tolist() == [True, True, False]


def test_c2_eligible_mask_drops_singleton_strata():
    panel = pd.DataFrame(
        {
            "date": ["d1", "d1", "d1"],
            "sector": ["A", "A", "B"],  # sector B has no control row
            "is_event": [True, False, True],
            "value": [20.0, 10.0, 999.0],
        }
    )

    mask = c2_eligible_mask(panel, "is_event", "value", match_cols=["sector"], date_col="date")

    assert mask.tolist() == [True, True, False]


def test_c2_eligible_mask_matches_the_row_population_c2_delta_actually_uses():
    # A blend: some rows missing a match col, some in singleton strata,
    # some fully populated -- the mask must select exactly the rows whose
    # (date, sector) stratum contributes to stratum_deltas's own C2 table.
    panel = pd.DataFrame(
        {
            "date": ["d1", "d1", "d1", "d1", "d2", "d2"],
            "sector": ["A", "A", "B", "B", "A", None],
            "is_event": [True, False, True, False, True, True],
            "value": [15.0, 5.0, 1015.0, 1005.0, 25.0, 999.0],
        }
    )

    mask = c2_eligible_mask(panel, "is_event", "value", match_cols=["sector"], date_col="date")
    deltas = stratum_deltas(panel, "is_event", "value", ["date", "sector"])

    contributing_strata = set(map(tuple, deltas[["date", "sector"]].itertuples(index=False)))
    expected = panel.apply(lambda r: (r["date"], r["sector"]) in contributing_strata, axis=1)

    assert mask.tolist() == expected.tolist()


def test_c2_eligible_mask_restricts_c0_and_c1_to_the_same_row_set_as_c2():
    panel = pd.DataFrame(
        {
            "date": ["d1", "d1", "d1", "d1", "d2", "d2"],
            "sector": ["A", "A", "B", "B", "A", None],  # d2/None row is ineligible
            "is_event": [True, False, True, False, True, True],
            "value": [15.0, 5.0, 1015.0, 1005.0, 999.0, 999.0],
        }
    )
    mask = c2_eligible_mask(panel, "is_event", "value", match_cols=["sector"], date_col="date")
    restricted = panel[mask]

    # Same row count feeding all three deltas -- the point of the fix.
    assert len(restricted) == 4
    c0_delta(restricted, "is_event", "value")
    c1_delta(restricted, "is_event", "value")
    c2_delta(restricted, "is_event", "value", match_cols=["sector"])


# ---- pooled_delta (M1's "C1 > C0" investigation, PREREGISTRATION.md) ----

def test_pooled_delta_excludes_event_rows_from_its_baseline():
    # event=[10,20] (mean 15), control=[0,2,4] (mean 2) -- pooled_delta
    # must use only the control rows as its baseline, not all 5 rows.
    panel = pd.DataFrame(
        {"is_event": [True, True, False, False, False], "value": [10.0, 20.0, 0.0, 2.0, 4.0]}
    )

    assert pooled_delta(panel, "is_event", "value") == pytest.approx(15.0 - 2.0)


def test_c0_delta_equals_dilution_factor_times_pooled_delta():
    # Algebraic identity: c0_delta = (1 - p) * pooled_delta, where p is the
    # event group's population share -- verified numerically (not just
    # asserted) since this is exactly the relationship the M1 "C1 > C0"
    # investigation depends on.
    panel = pd.DataFrame(
        {
            "is_event": [True, True, True, False, False, False, False],
            "value": [10.0, 12.0, 14.0, 0.0, 2.0, 4.0, 6.0],
        }
    )
    p = panel["is_event"].mean()  # 3/7

    c0 = c0_delta(panel, "is_event", "value")
    pooled = pooled_delta(panel, "is_event", "value")

    assert c0 == pytest.approx((1 - p) * pooled)

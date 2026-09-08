"""Phase 1 gate: synthetic pipeline validation (DESIGN.md §10.2).

"Nothing past this point should be trusted until it passes" -- these tests
are the enforcement of that gate, not just a report. They exercise the real
`features/panel.py` (one-bar lag), `labels/forward_returns.py`, and
`stats/controls.py` (C1) primitives that Phase 2's full feature layer will
build on -- catching a broken lag or a leaked signal here, against a
dataset with a precisely known ground truth, rather than as a subtle drift
in a real-data result later. `run_validation`/`gate_verdict` are also what
`python -m src.signals.moving_averages.cli validate-synth` calls, so the
CLI's PASS/FAIL report and these assertions can't diverge.

`test_c1_delta_is_not_diluted_by_the_event_group_itself` pins down a real
bug this suite caught during Phase 1: an earlier `c1_delta` compared the
event group's mean against the whole date-universe mean (event rows
included), which silently halved every recovered effect on an
~50/50-split feature. DESIGN.md §6.1 defines C1 as event-vs-non-event, not
event-vs-everyone -- fixed, and pinned here so it can't regress unnoticed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c0_delta, c1_delta
from src.signals.moving_averages.synthetic import (
    PLANT_MAGNITUDE,
    RECOVERY_TOLERANCE,
    SHIFT_DEGRADATION_RATIO,
    build_synthetic_panels,
    gate_verdict,
    run_validation,
    shift_extra_day,
)


# ---- primitive correctness, independent of the synthetic generator ----

def test_apply_lag_does_not_bleed_across_ticker_boundaries():
    panel = pd.DataFrame(
        {
            "ticker": ["A", "A", "A", "B", "B", "B"],
            "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"] * 2),
            "signal": [1, 2, 3, 10, 20, 30],
        }
    )

    lagged = apply_lag(panel, columns=["signal"])

    # B's first row must be NaN (no prior B row), not A's last value (3).
    assert lagged.loc[lagged["ticker"] == "B", "signal"].iloc[0] != 3
    assert pd.isna(lagged.loc[lagged["ticker"] == "B", "signal"].iloc[0])
    assert pd.isna(lagged.loc[lagged["ticker"] == "A", "signal"].iloc[0])
    assert lagged.loc[lagged["ticker"] == "A", "signal"].tolist()[1:] == [1, 2]
    assert lagged.loc[lagged["ticker"] == "B", "signal"].tolist()[1:] == [10, 20]


def test_forward_return_does_not_bleed_across_ticker_boundaries():
    panel = pd.DataFrame(
        {
            "ticker": ["A", "A", "B", "B"],
            "date": pd.to_datetime(["2020-01-01", "2020-01-02"] * 2),
            "close": [100.0, 110.0, 50.0, 40.0],
        }
    )

    fwd = forward_return(panel, horizon=1)

    assert fwd.iloc[0] == pytest.approx(0.10)   # A: 110/100 - 1
    assert pd.isna(fwd.iloc[1])                  # A's last row: no forward price
    assert fwd.iloc[2] == pytest.approx(-0.20)  # B: 40/50 - 1, not bled from A
    assert pd.isna(fwd.iloc[3])


def test_c1_delta_is_not_diluted_by_the_event_group_itself():
    """Two dates, 50/50 event split each date, true group difference is
    exactly +10 both dates -- C1 must recover +10.0, not +5.0 (see module
    docstring: the bug this pins down diluted the delta by the event
    group's population share when compared against the whole universe
    instead of the non-event group).
    """
    panel = pd.DataFrame(
        {
            "date": ["d1", "d1", "d2", "d2"],
            "is_event": [True, False, True, False],
            "value": [15.0, 5.0, 25.0, 15.0],
        }
    )

    delta = c1_delta(panel, group_col="is_event", value_col="value", date_col="date")

    assert delta == pytest.approx(10.0)


def test_c0_delta_compares_against_the_whole_panel_including_the_event_group():
    """C0 is deliberately the weak/diluted control (DESIGN.md §6.1) --
    unlike C1, it's *supposed* to compare against the whole universe,
    event rows included.
    """
    panel = pd.DataFrame({"is_event": [True, True, False, False], "value": [20.0, 20.0, 0.0, 0.0]})

    delta = c0_delta(panel, group_col="is_event", value_col="value")

    # overall mean = 10.0, event-group mean = 20.0 -> delta = 10.0, not 20.0
    assert delta == pytest.approx(10.0)


# ---- the Phase 1 gate itself ----

def test_pipeline_recovers_the_planted_effect_at_the_right_magnitude():
    results = run_validation()

    assert abs(results["recovered_planted"] - PLANT_MAGNITUDE) < RECOVERY_TOLERANCE


def test_pipeline_reports_nothing_on_the_null_dataset():
    results = run_validation()

    assert abs(results["recovered_null"]) < RECOVERY_TOLERANCE


def test_lookahead_shift_degrades_the_recovered_effect():
    """DESIGN.md §7.2: shift every feature forward one day and confirm
    results degrade. Not a strict "must vanish" -- above/below a 5-day SMA
    is autocorrelated day to day, so some residual recovery is expected --
    but it must fall well below the correctly-lagged recovery.
    """
    results = run_validation()

    assert abs(results["recovered_shifted"]) < abs(results["recovered_planted"]) * SHIFT_DEGRADATION_RATIO


def test_gate_verdict_all_pass_on_the_default_synthetic_run():
    results = run_validation()
    verdict = gate_verdict(results)

    assert all(verdict.values()), verdict


def test_shift_extra_day_actually_changes_a_meaningful_fraction_of_rows():
    """Guards the shift test's own discriminating power: if the shifted
    feature happened to equal the correctly-lagged one on almost every
    row (e.g. a lookback so long its state barely ever flips), the shift
    test above would pass for the wrong reason -- not because the pipeline
    is lag-sensitive, but because misalignment rarely changes the value.
    """
    planted, _ = build_synthetic_panels()
    shifted = shift_extra_day(planted)

    comparable = planted[["above_sma_lagged"]].assign(shifted=shifted).dropna()
    disagreement_rate = (comparable["above_sma_lagged"] != comparable["shifted"]).mean()

    assert disagreement_rate > 0.15

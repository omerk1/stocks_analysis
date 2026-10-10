"""Track-B match-quality (balance) report -- PREREGISTRATION.md
prerequisite 3. COVARIATES ONLY: no outcome column is read anywhere in
this module, so the matching can be reviewed and tuned before anything is
unblinded, without multiple-testing consequences.

Assembles the two sides exactly as the eventual run script will:

- Events: RSI regular divergences, p2 in 2010-01-01..2021-12-31, PIT
  S&P 500 + Nasdaq-100 membership at p2 (rename-aware), context class
  from the stored scalars (extension / pullback_rebuild poles only).
- Controls: divergence_control_pairs rows with regular geometry, NO
  stored divergence on the swing (has_divergence = 0), same window,
  membership, and classification.

Then matches per the pre-registration (month cell; +/-1-bin caliper on
impulse deciles, vol quintiles AND retrace-fraction quintiles, bucketed
per direction x context class; <=3:1, without replacement, seeded) and
prints SMD before/after per direction x context class, with
NaN-covariate exclusions counted explicitly (the prereg requires it).

Usage: python -m src.analysis.divergence_trackb_balance
"""

from __future__ import annotations

import argparse

import pandas as pd

from src.foundation.market_common import derived_db
from src.signals.divergences.matching import (
    balance_report,
    classify_context,
    match_controls,
)
from src.signals.divergences.study_universe import DEV_END, DEV_START, membership_intervals, pit_member_mask

MATCH_SEED = 20261007


def _pit_filter(frame: pd.DataFrame, by_ticker: dict) -> pd.DataFrame:
    return frame[pit_member_mask(frame, by_ticker)]


def _prepare(frame: pd.DataFrame, require_class: bool = True) -> pd.DataFrame:
    """Classify-but-keep by default is NOT an option here: `require_class`
    filters to the two frozen poles, which the binary/matching path needs.
    The run script passes require_class=False because the frozen c-cells
    'use every event including the band' -- dropping band/deep-fast rows
    before they reach the continuous regression was the bug #186's review
    caught."""
    frame = frame.copy()
    frame["context_class"] = [
        classify_context(r, b)
        for r, b in zip(frame["interpeak_retrace_frac"], frame["leg2_bars"])
    ]
    if require_class:
        frame = frame[frame["context_class"].notna()]
    frame["p2_month"] = pd.to_datetime(frame["p2_date"]).dt.strftime("%Y-%m")
    return frame


def load_events(
    derived_conn, raw_conn, membership: dict | None = None, require_class: bool = True
) -> pd.DataFrame:
    q = """
    SELECT d.id, d.ticker, d.p2_date, d.confirmed_at, d.direction,
           c.impulse_gain_pct, c.interpeak_retrace_frac, c.leg2_bars,
           c.realized_vol_63
    FROM divergences d JOIN divergence_context c ON c.divergence_id = d.id
    WHERE d.timeframe = 'daily' AND d.form = 'regular' AND d.indicator = 'rsi'
      AND d.p2_date >= ? AND d.p2_date <= ?
    """
    events = pd.read_sql_query(q, derived_conn, params=[DEV_START, DEV_END + "T23:59:59"])
    by_ticker = membership if membership is not None else membership_intervals(raw_conn)
    return _prepare(_pit_filter(events, by_ticker), require_class=require_class)


def load_controls(
    derived_conn, raw_conn, membership: dict | None = None, require_class: bool = True
) -> pd.DataFrame:
    q = """
    SELECT id, ticker, p2_date, confirmed_at, direction,
           impulse_gain_pct, interpeak_retrace_frac, leg2_bars, realized_vol_63
    FROM divergence_control_pairs
    WHERE timeframe = 'daily' AND regular_geometry = 1 AND has_divergence = 0
      AND p2_date >= ? AND p2_date <= ?
    """
    controls = pd.read_sql_query(q, derived_conn, params=[DEV_START, DEV_END + "T23:59:59"])
    by_ticker = membership if membership is not None else membership_intervals(raw_conn)
    return _prepare(_pit_filter(controls, by_ticker), require_class=require_class)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    raw_conn, derived_conn = derived_db.bootstrap_cli(lambda conn: None)

    membership = membership_intervals(raw_conn)
    events = load_events(derived_conn, raw_conn, membership)
    controls = load_controls(derived_conn, raw_conn, membership)

    print(f"events (RSI regular, PIT, classified): {len(events)}  by cell:")
    print(events.groupby(["direction", "context_class"]).size().to_string())
    print(f"\ncontrol pool (regular geometry, no divergence, PIT, classified): {len(controls)}  by cell:")
    print(controls.groupby(["direction", "context_class"]).size().to_string())

    # Events the matcher cannot serve structurally (NaN covariate) are a
    # different failure from "no control available in the cell" -- the
    # pre-registration requires them excluded AND counted.
    covs = ["impulse_gain_pct", "realized_vol_63", "interpeak_retrace_frac"]
    unmatchable = events[events[covs].isna().any(axis=1)]
    matchable = len(events) - len(unmatchable)
    print(
        f"\nevents with a NaN matching covariate (structurally unmatchable, excluded): "
        f"{len(unmatchable)}; matchable: {matchable}"
    )

    matches = match_controls(events, controls, seed=MATCH_SEED)
    matched_rate = matches["event_id"].nunique() / matchable if matchable else float("nan")
    print(
        f"matches: {len(matches)} rows; matchable events with >=1 control: {matched_rate:.1%} "
        f"(denominator = matchable, not total)"
    )

    report = balance_report(events, controls, matches)
    pd.set_option("display.width", 160)
    print("\nbalance (SMD before = events vs full pool; after = events vs matched):")
    print(report.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

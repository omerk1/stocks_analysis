"""Hidden-forms prep looks (Track A, exploratory) — the two looks that
PREREGISTRATION.md's "Hidden forms" section gates DC-B3/B4 on. Definitions
and gates pre-committed in EXPLORATION_LOG.md (2026-10-11) before anything
was computed.

(a) Co-occurrence: does a hidden event mark the same structure as a
    regular event of the opposite direction (the interleaving is
    structural: an uptrend pullback's hidden-bullish LOW pair brackets the
    regular-bearish second high), or is it independent information?
(b) Scalar fit: a pivot-to-pivot retrace fraction derived from the stored
    context scalars, as the hidden-geometry replacement for the v0 63-bar
    impulse normalization that step 0 showed mismeasures hidden structure
    (retrace_frac medians > 1).

Everything printed here is a bare rate on exploratory data: input for
deciding whether DC-B3/B4 get drafted, never a finding. Read-only over
`divergences` + `divergence_context`; no DB writes, no caches.

Usage: python -m src.analysis.divergence_hidden_prep
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from src.foundation.market_common import derived_db
from src.signals.divergences.study_universe import (
    DEV_END,
    DEV_START,
    membership_intervals,
    pit_member_mask,
)

OUTCOME_END = "2021-11-30"  # 20-bar outcome window must not cross the holdout
# Descriptive bucket edges mirroring step 0's, applied to the hidden-fit
# fraction: not pre-registered thresholds.
SHAPE_RETRACE_FRAC = 0.33
SHAPE_LEG2_BARS = 5

# A hidden event and the regular event marking the other side of the same
# swing run in opposite directions: the uptrend that prints hidden-bullish
# LOW pairs prints regular-bearish HIGH pairs, and mirrored.
MIRROR = {"bullish": "bearish", "bearish": "bullish"}


def _load_dev_events(derived_conn) -> pd.DataFrame:
    q = """
    SELECT d.*, c.impulse_gain_pct, c.interpeak_retrace_pct, c.interpeak_retrace_frac,
           c.leg2_gain_pct, c.leg2_bars, c.atr_contraction
    FROM divergences d LEFT JOIN divergence_context c ON c.divergence_id = d.id
    WHERE d.timeframe = 'daily' AND d.confirmed_at <= ?
    """
    events = pd.read_sql_query(q, derived_conn, params=[DEV_END + "T23:59:59"])
    events["p1_ts"] = pd.to_datetime(events["p1_date"])
    events["p2_ts"] = pd.to_datetime(events["p2_date"])
    events["cell"] = events["form"] + "/" + events["direction"]
    return events


def hidden_fit_retrace_frac(events: pd.DataFrame) -> pd.Series:
    """Pivot-to-pivot retrace fraction: counter-move / trend-leg, derived
    from the stored scalars (DESIGN's ratios-at-analysis-time rule).

    For a LOW pair (direction bullish) the trend leg is the advance p1 ->
    interpeak high (stored as interpeak_retrace_pct of p1) and the
    counter-move is the decline interpeak high -> p2 (leg2_gain_pct of the
    high), so the ratio is leg2 * (1 + retrace_pct) / retrace_pct. HIGH
    pairs (bearish) mirror with (1 - retrace_pct). NaN wherever an input
    is NaN or the trend leg is ~0 (invariant #9: derived features preserve
    their inputs' missingness — the where/mask discipline, not a bare
    comparison).
    """
    retrace = events["interpeak_retrace_pct"]
    leg2 = events["leg2_gain_pct"]
    is_high_pair = events["direction"] == "bearish"
    level_factor = np.where(is_high_pair, 1.0 - retrace, 1.0 + retrace)
    frac = leg2 * level_factor / retrace
    defined = retrace.notna() & leg2.notna() & (retrace > 0)
    return frac.where(defined)


def _covered_mask(points: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """True where a point lies STRICTLY inside any (start, end) interval.
    Intervals may overlap or nest: sort by start, prefix-max the ends, and
    a point is covered iff the latest-ending interval that starts before
    it also ends after it."""
    if len(starts) == 0 or len(points) == 0:
        return np.zeros(len(points), dtype=bool)
    order = np.argsort(starts, kind="stable")
    starts, ends = starts[order], ends[order]
    prefix_max_end = np.maximum.accumulate(ends)
    idx = np.searchsorted(starts, points, side="left")  # intervals with start < point
    out = np.zeros(len(points), dtype=bool)
    has_prior = idx > 0
    out[has_prior] = prefix_max_end[idx[has_prior] - 1] > points[has_prior]
    return out


def attach_cooccurrence(events: pd.DataFrame) -> pd.DataFrame:
    """Adds four boolean columns.

    Hidden rows: `counterpart_any` / `counterpart_same_ind` — a regular
    event of the mirrored direction (any indicator / this row's indicator)
    has its p2 strictly inside this row's (p1, p2) interval.
    Regular rows: `inside_hidden_any` / `inside_hidden_same_ind` — this
    row's p2 lies strictly inside some mirrored-direction hidden row's
    interval. Boundaries are exclusive: a shared pivot date is not
    "between the pivots".
    """
    events = events.copy()
    for col in ("counterpart_any", "counterpart_same_ind",
                "inside_hidden_any", "inside_hidden_same_ind"):
        events[col] = False

    hidden = events[events["form"] == "hidden"]
    regular = events[events["form"] == "regular"]

    for same_indicator, (h_col, r_col) in (
        (False, ("counterpart_any", "inside_hidden_any")),
        (True, ("counterpart_same_ind", "inside_hidden_same_ind")),
    ):
        keys = ["ticker", "indicator"] if same_indicator else ["ticker"]
        reg_groups = dict(iter(regular.groupby(keys)))
        hid_groups = dict(iter(hidden.groupby(keys)))
        for key, h_grp in hid_groups.items():
            r_grp = reg_groups.get(key)
            if r_grp is None:
                continue
            for direction, h_dir in h_grp.groupby("direction"):
                r_dir = r_grp[r_grp["direction"] == MIRROR[direction]]
                if r_dir.empty:
                    continue
                reg_p2 = np.sort(r_dir["p2_ts"].to_numpy())
                starts = h_dir["p1_ts"].to_numpy()
                ends = h_dir["p2_ts"].to_numpy()
                # Hidden side: any regular p2 strictly inside (p1, p2)?
                lo = np.searchsorted(reg_p2, starts, side="right")
                hi = np.searchsorted(reg_p2, ends, side="left")
                events.loc[h_dir.index, h_col] = hi > lo
                # Regular side: p2 strictly inside any hidden interval?
                pts = r_dir["p2_ts"].to_numpy()
                events.loc[r_dir.index, r_col] = _covered_mask(pts, starts, ends)
    return events


def _rate_line(label: str, frame: pd.DataFrame, flag: str) -> str:
    n = len(frame)
    k = int(frame[flag].sum())
    dates = frame.loc[frame[flag], "p2_date"].nunique()
    dates_without = frame.loc[~frame[flag], "p2_date"].nunique()
    rate = k / n if n else float("nan")
    return (f"  {label:40s} {k}/{n} = {rate:.1%}  "
            f"(p2 dates with: {dates}, without: {dates_without})")


def report_cooccurrence(events: pd.DataFrame) -> None:
    print("\n== Look (a): hidden/regular co-occurrence on the same structure ==")
    dev = events["p2_ts"] >= DEV_START
    for scope, frame in (("raw, <= DEV_END", events),
                         (f"PIT members, {DEV_START}..{DEV_END}", events[events["pit_member"] & dev])):
        print(f"  -- {scope} --")
        hidden = frame[frame["form"] == "hidden"]
        regular = frame[frame["form"] == "regular"]
        for direction, grp in hidden.groupby("direction"):
            mirrored = MIRROR[direction]
            print(_rate_line(f"hidden/{direction} w/ regular/{mirrored} p2 inside (any ind)",
                             grp, "counterpart_any"))
            print(_rate_line(f"hidden/{direction} w/ regular/{mirrored} p2 inside (same ind)",
                             grp, "counterpart_same_ind"))
        for direction, grp in regular.groupby("direction"):
            mirrored = MIRROR[direction]
            print(_rate_line(f"regular/{direction} inside a hidden/{mirrored} window (any ind)",
                             grp, "inside_hidden_any"))
            print(_rate_line(f"regular/{direction} inside a hidden/{mirrored} window (same ind)",
                             grp, "inside_hidden_same_ind"))


def report_disagreement_outcomes(events: pd.DataFrame) -> None:
    print(f"\n== Look (a) outcome peek (confirmed <= {OUTCOME_END}; BARE RATES, not findings;"
          " within-form comparisons only) ==")
    sub = events[(events["form"] == "hidden")
                 & (events["confirmed_at"] <= OUTCOME_END + "T23:59:59")].copy()
    sub = sub[sub["outcome_computed_through"].notna() & sub["invalidated"].notna()]
    for (direction, flag), grp in sub.groupby(["direction", "counterpart_any"]):
        label = "with regular counterpart" if flag else "hidden alone"
        print(f"  hidden/{direction:8s} {label:25s} n={len(grp):6d} "
              f"dates={grp['p2_date'].nunique():5d} "
              f"invalidated={grp['invalidated'].mean():.1%} "
              f"medMFE={grp['max_favorable_move_atr'].median():.2f} ATR")


def _fmt_quantiles(s: pd.Series) -> str:
    s = s.dropna()
    if s.empty:
        return "n=0"
    q = s.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    return (f"n={len(s)}  p10={q.iloc[0]:.2f}  p25={q.iloc[1]:.2f}  p50={q.iloc[2]:.2f}  "
            f"p75={q.iloc[3]:.2f}  p90={q.iloc[4]:.2f}")


def report_scalar_fit(events: pd.DataFrame) -> None:
    print("\n== Look (b): impulse-scalar fit for hidden geometry ==")
    print("  -- v0 misfit: interpeak_retrace_frac (63-bar impulse normalization) --")
    for cell, grp in events.groupby("cell"):
        v0 = grp["interpeak_retrace_frac"]
        defined = v0.notna()
        over1 = (v0 > 1).where(defined).mean()
        print(f"  {cell:18s} {_fmt_quantiles(v0)}  frac>1: {over1:.1%}  "
              f"NaN: {(~defined).mean():.1%}")

    print("\n  -- candidate: pivot-to-pivot retrace fraction (counter-move / trend-leg) --")
    hidden = events[events["form"] == "hidden"]
    for direction, grp in hidden.groupby("direction"):
        cand = grp["hidden_fit_frac"]
        inputs_nan = grp["interpeak_retrace_pct"].isna() | grp["leg2_gain_pct"].isna()
        degenerate = grp["interpeak_retrace_pct"].notna() & ~(grp["interpeak_retrace_pct"] > 0)
        print(f"  hidden/{direction:8s} {_fmt_quantiles(cand)}")
        print(f"  {'':18s} NaN: {cand.isna().mean():.1%} "
              f"(inputs NaN: {inputs_nan.mean():.1%}, trend-leg ~0: {degenerate.mean():.1%})")

    print(f"\n  -- shape split on the candidate (frac >= {SHAPE_RETRACE_FRAC},"
          f" counter-move bars >= {SHAPE_LEG2_BARS}; descriptive edges) --")
    dev = hidden["p2_ts"] >= DEV_START
    for scope, frame in (("raw, <= DEV_END", hidden),
                         (f"PIT members, {DEV_START}..{DEV_END}", hidden[hidden["pit_member"] & dev])):
        print(f"  -- {scope} --")
        defined = frame["hidden_fit_frac"].notna()
        deep = frame["hidden_fit_frac"] >= SHAPE_RETRACE_FRAC
        slow = frame["leg2_bars"] >= SHAPE_LEG2_BARS
        shape = pd.Series(pd.NA, index=frame.index, dtype="object")
        shape[defined & ~deep] = "shallow (extension-analogue)"
        shape[defined & deep & slow] = "deep+slow (pullback-analogue)"
        shape[defined & deep & ~slow] = "deep-fast"
        for (direction, cls), grp in frame.groupby(["direction", shape], dropna=True):
            n_defined = int(defined[frame["direction"] == direction].sum())
            print(f"  hidden/{direction:8s} {cls:30s} n={len(grp):6d} "
                  f"({len(grp) / n_defined:5.1%} of defined) "
                  f"dates={grp['p2_date'].nunique():5d}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()

    raw_conn, derived_conn = derived_db.bootstrap_cli(lambda conn: None)
    events = _load_dev_events(derived_conn)
    events["pit_member"] = pit_member_mask(events, membership_intervals(raw_conn))
    events["hidden_fit_frac"] = hidden_fit_retrace_frac(events)
    events = attach_cooccurrence(events)

    print(f"dev-window events (confirmed <= {DEV_END}): {len(events)}; "
          f"per cell:\n{events.groupby('cell').size().to_string()}")
    report_cooccurrence(events)
    report_disagreement_outcomes(events)
    report_scalar_fit(events)

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

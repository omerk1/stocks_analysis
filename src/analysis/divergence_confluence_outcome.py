"""Confluence vs outcome for stored daily divergences (Track A, exploratory).

The Done #44 follow-up (backlog "Signals"): do divergences where several
indicators diverge off the same price swing actually resolve more
favorably than solo ones? Answered as a delta against matched solo
divergences, never a bare conditional mean.

Point-in-time discipline: the stored `confluence_count` is a FULL-RUN
value — the backfill runs with as_of=None, and a later-confirming
indicator's divergence can join a cluster retroactively (see
tests/test_divergences_asof_equivalence.py's docstring). Reading it as a
decision-time fact is look-ahead. This script recomputes, per event, the
confluence knowable at that event's own `confirmed_at`
(`pit_confluence_at_confirmation`, the per-event form of
`context.pit_confluence`), against the same per-ticker vendor bars the
detector ran on.

Everything stays inside the development window: events are confirmed
<= DEV_END, outcome tabulations stop at OUTCOME_END so the 20-bar outcome
window cannot cross the holdout. Exploratory output — input for designing
a real test, never a finding.

Usage:
  python -m src.analysis.divergence_confluence_outcome build    # slow: per-ticker bars -> PIT counts, cached parquet
  python -m src.analysis.divergence_confluence_outcome report   # the analysis, from the cache
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.divergence_rr_sweep import drop_disputed
from src.analysis.divergence_study_common import (
    OUTCOME_END,
    attach_pit_membership,
    load_dev_events,
)
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe
from src.signals.divergences.config import VENDOR_FALLBACK, DivergenceConfig
from src.signals.divergences.store import builder_sources

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "derived" / "divergence_confluence_outcome"
EVENTS_PARQUET = CACHE_DIR / "events.parquet"

# Stratification for the matched comparison: high- and low-confluence
# events are only ever compared within the same direction x form x
# indicator x p2-year cell, then the per-stratum deltas are combined
# weighted by the stratum's high-confluence count.
STRATA = ["direction", "form", "indicator", "year"]
ERA_SPLIT_YEAR = 2016  # 2010-2015 vs 2016-2021, as in the R/R sweep's era check
BOOTSTRAP_DRAWS = 400
SEED = 20261014


def pit_confluence_at_confirmation(
    events: pd.DataFrame, bar_index: pd.DatetimeIndex, pairing_window: int = 3
) -> pd.Series:
    """Distinct agreeing indicators per event as knowable at that event's
    OWN `confirmed_at` — for each event, the `context.pit_confluence`
    cluster size it would get with the frame filtered to
    `confirmed_at <= its own confirmed_at` (the decision-time count for a
    consumer acting at confirmation; the equivalence is asserted in
    tests/test_divergence_confluence_outcome.py).

    Same clustering rule as detect._apply_confluence: within (direction,
    form), events chain while consecutive *visible* p2 bar positions are
    within `pairing_window`. One ticker/timeframe at a time, and rows
    whose p2_date is off the bar calendar stay solo — both stances
    inherited from `pit_confluence`.
    """
    for col in ("ticker", "timeframe"):
        if col in events.columns and events[col].nunique() > 1:
            raise ValueError(
                f"pit_confluence_at_confirmation clusters one ticker/timeframe at a time; got multiple {col}s"
            )
    counts = pd.Series(1, index=events.index, dtype=int)
    if events.empty:
        return counts
    locs = bar_index.get_indexer(pd.DatetimeIndex(pd.to_datetime(events["p2_date"])))
    pos = pd.Series(locs, index=events.index)
    located = events.loc[pos[pos >= 0].index]

    for _, group in located.groupby(["direction", "form"]):
        order = pos.loc[group.index].sort_values().index
        p = pos.loc[order].to_numpy()
        c = pd.to_datetime(group.loc[order, "confirmed_at"]).to_numpy()
        inds = group.loc[order, "indicator"].to_numpy()
        m = len(order)
        out = np.ones(m, dtype=int)
        for i in range(m):
            visible = c <= c[i]
            members = {inds[i]}
            # Walk out from i over visible members; the chain breaks when
            # the gap between consecutive visible positions exceeds the
            # pairing window — exactly pit_confluence's walk on the
            # confirmed_at-filtered frame.
            prev = p[i]
            for k in range(i - 1, -1, -1):
                if not visible[k]:
                    continue
                if prev - p[k] > pairing_window:
                    break
                members.add(inds[k])
                prev = p[k]
            prev = p[i]
            for k in range(i + 1, m):
                if not visible[k]:
                    continue
                if p[k] - prev > pairing_window:
                    break
                members.add(inds[k])
                prev = p[k]
            out[i] = len(members)
        counts.loc[order] = out
    return counts


def build(args: argparse.Namespace) -> None:
    """Attach a PIT confluence count (and PIT index membership) to every
    dev-window daily divergence and cache the result. Reads both DBs,
    writes only the parquet."""
    config = DivergenceConfig()
    raw_conn, derived_conn = derived_db.bootstrap_cli(lambda conn: None)
    events = load_dev_events(derived_conn)
    events = attach_pit_membership(events, raw_conn)
    tickers = sorted(events["ticker"].unique())

    # The same per-ticker vendor rule the detector and the context builder
    # use: a PIT count computed on a different vendor's calendar than the
    # stored pivots' is a silent cross-vendor mismatch, so flagged tickers
    # are dropped from the analysis (counted, never guessed).
    sources, flagged = builder_sources(
        raw_conn, derived_conn, tickers, config.price_basis, VENDOR_FALLBACK, "daily"
    )
    pit = pd.Series(np.nan, index=events.index)
    done = failed = 0
    for ticker, group in events.groupby("ticker"):
        if ticker in flagged:
            continue
        try:
            bars, _ = data_mod.load_and_validate(
                raw_conn, ticker, Timeframe.DAILY, basis=config.price_basis,
                source=sources[ticker],
            )
            if len(bars) == 0:
                continue
            pit.loc[group.index] = pit_confluence_at_confirmation(
                group, bars.index, config.pairing_window
            ).astype(float)
        except Exception:
            logger.exception("%s: PIT confluence failed", ticker)
            failed += 1
            continue
        done += 1
        if done % 500 == 0:
            print(f"  {done}/{len(tickers) - len(flagged)} tickers...", flush=True)

    events["pit_confluence"] = pit
    keep = [
        "id", "ticker", "direction", "form", "indicator", "p2_date",
        "confirmed_at", "year", "strength", "duration_bars", "price_move_atr",
        "max_favorable_move_atr", "invalidated", "confluence_count",
        "pit_confluence", "pit_member",
    ]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    events[keep].to_parquet(EVENTS_PARQUET, index=False)
    n_skipped = int(events["pit_confluence"].isna().sum())
    print(
        f"cached {len(events)} events -> {EVENTS_PARQUET}\n"
        f"tickers: {done} processed, {len(flagged)} vendor-flagged, {failed} failed; "
        f"{n_skipped} events without a PIT count (excluded at report time)"
    )
    raw_conn.close()
    derived_conn.close()


def stratified_delta(
    df: pd.DataFrame, hi: pd.Series, lo: pd.Series, value_col: str
) -> dict:
    """Mean(value | hi) - mean(value | lo), combined across STRATA cells
    weighted by each cell's hi count — only cells holding both groups
    contribute, so the comparison is always like-for-like. Returns the
    delta plus the raw/effective sample sizes behind it."""
    mask = (hi | lo) & df[value_col].notna()
    sub = df[mask].copy()
    sub["_hi"] = hi[mask]
    agg = (
        sub.groupby(STRATA + ["_hi"], observed=True)[value_col]
        .agg(["mean", "count"])
        .unstack("_hi")
        .dropna()  # a cell missing either group contributes nothing
    )
    if agg.empty:
        return {"delta": np.nan, "n_hi": 0, "n_lo": 0, "dates_hi": 0}
    n_hi = agg[("count", True)]
    w = n_hi / n_hi.sum()
    delta = float(((agg[("mean", True)] - agg[("mean", False)]) * w).sum())
    contributing = sub.set_index(STRATA).index.isin(agg.index)
    return {
        "delta": delta,
        "n_hi": int(n_hi.sum()),
        "n_lo": int(agg[("count", False)].sum()),
        "dates_hi": int(sub[contributing & sub["_hi"].to_numpy()]["p2_date"].nunique()),
    }


def bootstrap_dates_ci(
    df: pd.DataFrame, hi: pd.Series, lo: pd.Series, value_col: str,
    draws: int = BOOTSTRAP_DRAWS, seed: int = SEED,
) -> tuple[float, float]:
    """95% CI for `stratified_delta`, resampling p2 DATES with replacement
    (events cluster on dates — invariant #6 — so rows are not independent;
    dates are the resampling unit). Point estimates are computed on
    date-level sums so each draw is a groupby, not a re-walk."""
    mask = (hi | lo) & df[value_col].notna()
    sub = df[mask].copy()
    sub["_hi"] = hi[mask]
    day = (
        sub.groupby(STRATA + ["p2_date", "_hi"], observed=True)[value_col]
        .agg(["sum", "count"])
        .reset_index()
    )
    dates = day["p2_date"].unique()
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(draws):
        picked = pd.Series(rng.choice(dates, size=len(dates), replace=True)).value_counts()
        d = day.merge(picked.rename("w"), left_on="p2_date", right_index=True)
        d["ws"] = d["sum"] * d["w"]
        d["wn"] = d["count"] * d["w"]
        agg = (
            d.groupby(STRATA + ["_hi"], observed=True)[["ws", "wn"]]
            .sum()
            .unstack("_hi")
            .dropna()
        )
        if agg.empty:
            continue
        mean_hi = agg[("ws", True)] / agg[("wn", True)]
        mean_lo = agg[("ws", False)] / agg[("wn", False)]
        w = agg[("wn", True)] / agg[("wn", True)].sum()
        out.append(float(((mean_hi - mean_lo) * w).sum()))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def _report_variant(df: pd.DataFrame, name: str, hi: pd.Series, lo: pd.Series, ci: bool) -> None:
    print(f"\n-- {name} --")
    for col, label in (("max_favorable_move_atr", "MFE (ATR)"), ("invalidated", "invalidation rate")):
        r = stratified_delta(df, hi, lo, col)
        line = (
            f"  {label}: delta {r['delta']:+.4f}   "
            f"n_hi {r['n_hi']} (on {r['dates_hi']} distinct p2 dates), n_lo {r['n_lo']}"
        )
        if ci and r["n_hi"] > 0:
            lo_ci, hi_ci = bootstrap_dates_ci(df, hi, lo, col)
            line += f"   95% CI [{lo_ci:+.4f}, {hi_ci:+.4f}] (date-clustered bootstrap)"
        print(line)
    for era, sub in df.groupby(df["year"] >= ERA_SPLIT_YEAR):
        r = stratified_delta(sub, hi[sub.index], lo[sub.index], "max_favorable_move_atr")
        label = f"{ERA_SPLIT_YEAR}-2021" if era else f"2010-{ERA_SPLIT_YEAR - 1}"
        print(f"    era {label}: MFE delta {r['delta']:+.4f}  (n_hi {r['n_hi']}, {r['dates_hi']} dates)")
    for (d, f), sub in df.groupby(["direction", "form"], observed=True):
        r = stratified_delta(sub, hi[sub.index], lo[sub.index], "max_favorable_move_atr")
        print(f"    {d}/{f}: MFE delta {r['delta']:+.4f}  (n_hi {r['n_hi']}, {r['dates_hi']} dates)")


def report(args: argparse.Namespace) -> None:
    events = pd.read_parquet(EVENTS_PARQUET)
    n0 = len(events)
    events = events[events["pit_confluence"].notna()]
    n_nopit = n0 - len(events)
    events, n_whole, n_window = drop_disputed(
        events.assign(entry_date=pd.to_datetime(events["confirmed_at"]).dt.strftime("%Y-%m-%d"))
    )
    events = events.reset_index(drop=True)
    print(f"events: {n0} cached, {n_nopit} without PIT count, "
          f"{n_whole} on whole-history-disputed tickers, {n_window} near a disputed day")

    # Outcome subset: the 20-bar outcome window must not cross the holdout,
    # and the headline universe is PIT index members (as the R/R sweep's) —
    # the all-ticker aggregate is printed once for scale.
    oc = events[
        (events["confirmed_at"] <= OUTCOME_END + "T23:59:59")
        & events["max_favorable_move_atr"].notna()
    ].copy()
    oc["invalidated"] = oc["invalidated"].astype(float)
    print(f"outcome-eligible (confirmed <= {OUTCOME_END}): {len(oc)}; "
          f"PIT members: {int(oc['pit_member'].sum())}")

    print("\n== look-ahead in the stored column (all outcome-eligible events) ==")
    tab = pd.crosstab(oc["pit_confluence"].astype(int), oc["confluence_count"])
    print(tab.rename_axis(index="PIT count", columns="stored (full-run) count"))
    inflated = oc["confluence_count"] > oc["pit_confluence"]
    print(f"stored count exceeds the decision-time count on {inflated.mean():.1%} of events")

    members = oc[oc["pit_member"]].copy()
    pit = members["pit_confluence"].astype(int)
    print(f"\n== matched deltas, PIT members (strata: {' x '.join(STRATA)}) ==")
    _report_variant(members, "PIT confluence >= 2 vs == 1 (headline)", pit >= 2, pit == 1, ci=True)
    _report_variant(members, "PIT confluence == 2 vs == 1 (neighbor)", pit == 2, pit == 1, ci=False)
    _report_variant(members, "PIT confluence == 3 vs == 1 (neighbor)", pit == 3, pit == 1, ci=False)

    pit_all = oc["pit_confluence"].astype(int)
    r = stratified_delta(oc, pit_all >= 2, pit_all == 1, "max_favorable_move_atr")
    print(f"\nall tickers (scale check): MFE delta {r['delta']:+.4f}  (n_hi {r['n_hi']}, {r['dates_hi']} dates)")

    st = stratified_delta(members, pit >= 2, pit == 1, "confluence_count")
    print("\nstored full-run count, same comparison (look-ahead bias direction): "
          f"delta {st['delta']:+.4f}")

    print("\n== balance check (hi vs lo within the same strata; selection, not outcome) ==")
    for col in ("strength", "price_move_atr", "duration_bars"):
        r = stratified_delta(members, pit >= 2, pit == 1, col)
        print(f"  {col}: delta {r['delta']:+.4f}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["build", "report"])
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        report(args)


if __name__ == "__main__":
    main()

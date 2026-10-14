"""python -m src.signals.refresh_derived [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--from-step N]

Run after every bar refresh: recomputes all seven derived RS/breadth
table-slices in one go -- breadth for both indices x both weightings (4)
plus the three relative-strength tiers -- then sweeps stale rows.
Exists because the tables are only as fresh as their last manual run and
twice in three days a bar refresh left them two weeks behind the bars
(Done #77); running seven CLI invocations by hand is exactly the step that
kept being skipped.

The sweep: all three stores are INSERT OR REPLACE by natural key, so a
fresh run only overwrites keys it itself produces -- a ticker (RS) or a
whole trading date (breadth) that lost its bars since the last run
(delisted, renamed, vendor re-adjustment) keeps its old rows forever
(Done #69 deleted 44,207 such RS rows by hand). After a full refresh, any
row whose run_id isn't one of this refresh's is by definition stale, so
it's deleted -- but only on a FULL-HISTORY run (no --start/--end: a
windowed run's new run_ids only cover the window, so the sweep would
delete everything outside it), and only when every step feeding that
table ran here and none was skipped (a skipped or --from-step-excluded
step means this invocation did not cover the full key space either).

A failed step stops the whole command (later tables would otherwise look
fresh while an earlier one silently stayed stale); rerun with
`--from-step N` to resume from the failed step without redoing the hours
already done.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

import pandas as pd

from src.foundation.market_common import derived_db
from src.signals.breadth import cli as breadth_cli
from src.signals.breadth import store as breadth_store
from src.signals.breadth.config import WEIGHTING_CHOICES, BreadthConfig
from src.signals.relative_strength import cli as rs_cli
from src.signals.relative_strength import store as rs_store
from src.signals.relative_strength.config import RelativeStrengthConfig


@dataclass(frozen=True)
class Step:
    kind: str  # "breadth" | "rs_stock" | "rs_sector"
    label: str  # what the per-step banner prints
    index_name: str | None = None
    weighting: str | None = None  # breadth only
    tier: str | None = None  # rs_stock only


def _build_steps() -> tuple[Step, ...]:
    """Derived from the two configs' own `indices`, not a second hand-kept
    index list: the sweep treats every run_id outside this invocation as
    stale, so a slice the module CLIs can produce but this list doesn't
    cover would have its history DELETED by the sweep. Deriving both from
    one source removes that divergence. Fixed order so --from-step numbers
    stay meaningful: breadth slices first (fastest feedback), then the two
    stock RS tiers over both indices, then the sector tier. Known
    trade-off: the equal and cap steps for one index recompute the same
    price/indicator panel; worth sharing only if the breadth half ever
    dominates the run.
    """
    breadth = [
        Step("breadth", f"breadth {index} {weighting}", index_name=index, weighting=weighting)
        for weighting in WEIGHTING_CHOICES
        for index in BreadthConfig().indices
    ]
    rs_stock = [
        Step("rs_stock", f"rs {tier} {index}", index_name=index, tier=tier)
        for tier in ("stock-vs-market", "stock-vs-sector")
        for index in RelativeStrengthConfig().indices
    ]
    return (*breadth, *rs_stock, Step("rs_sector", "rs sector-vs-market"))


REFRESH_STEPS: tuple[Step, ...] = _build_steps()

# Which steps must ALL have run (and stored rows) in this invocation
# before each table may be swept of other runs' rows.
_SWEEP_REQUIRES = {
    "breadth": ("breadth",),
    "relative_strength": ("rs_stock",),
    "sector_relative_strength": ("rs_sector",),
}


def _run_step(step: Step, raw_conn, derived_conn, start, end):
    """Returns (result_frame, skip_reason, run_id) -- the shared contract of
    the two modules' own CLI helpers, reused here so refresh and the
    per-module CLIs can't drift apart on how a slice is computed/stored."""
    if step.kind == "breadth":
        config = BreadthConfig(weighting=step.weighting)
        return breadth_cli.run_for_index(raw_conn, derived_conn, step.index_name, config, start, end)
    if step.kind == "rs_stock":
        return rs_cli.run_stock_tier(raw_conn, derived_conn, step.tier, step.index_name,
                                     RelativeStrengthConfig(), start, end)
    return rs_cli.run_sector_tier(raw_conn, derived_conn, RelativeStrengthConfig(), start, end)


def _latest_date(frame) -> str:
    # pd.Timestamp() rather than .date() on the raw max: the shared runner
    # contract doesn't pin the date dtype, and a string-dated frame must
    # not crash the banner of a step that already stored its rows.
    values = frame["date"] if "date" in frame.columns else frame.index
    return str(pd.Timestamp(values.max()).date())


def run_refresh(raw_conn, derived_conn, start=None, end=None, from_step: int = 1) -> bool:
    """Run steps `from_step`.. in order, then (full-history runs only)
    sweep each table whose feeding steps all stored rows here. Returns True
    when no step was skipped for lack of data -- steps excluded by
    `from_step` don't count against it (the caller chose that; the per-
    table sweep gating still accounts for them). Raises on the first
    failing step after naming it and the --from-step number that resumes
    there.
    """
    n = len(REFRESH_STEPS)
    data_skips = False
    kinds_stored: set[str] = set()
    kinds_incomplete: set[str] = set()  # skipped for no data, or excluded by --from-step
    run_ids: dict[str, list[str]] = {kind: [] for kinds in _SWEEP_REQUIRES.values() for kind in kinds}

    for step in REFRESH_STEPS[: from_step - 1]:
        kinds_incomplete.add(step.kind)

    for number, step in enumerate(REFRESH_STEPS, start=1):
        if number < from_step:
            print(f"[{number}/{n}] {step.label} ... skipped (--from-step {from_step})")
            continue
        print(f"[{number}/{n}] {step.label} ...", flush=True)
        try:
            frame, skip_reason, run_id = _run_step(step, raw_conn, derived_conn, start, end)
        except Exception:
            print(
                f"[{number}/{n}] {step.label} FAILED -- stopping so later tables don't look "
                f"fresher than this one; fix and resume with --from-step {number}",
                file=sys.stderr, flush=True,
            )
            raise
        if skip_reason is not None:
            print(f"[{number}/{n}] {step.label} SKIPPED -- {skip_reason}")
            data_skips = True
            kinds_incomplete.add(step.kind)
            continue
        kinds_stored.add(step.kind)
        # Every kind must be in run_ids (i.e. in _SWEEP_REQUIRES): a kind
        # the sweep doesn't know about would otherwise store rows the keep
        # lists omit -- toward deletion. KeyError here is the loud failure.
        run_ids[step.kind].append(run_id)
        print(f"[{number}/{n}] {step.label} done: {len(frame):,} rows through {_latest_date(frame)}")

    if start is not None or end is not None:
        print(
            "sweep: SKIPPED for all tables -- a windowed run's new run_ids only cover "
            "--start/--end, so sweeping would delete every row outside the window"
        )
        return not data_skips

    for table, required_kinds in _SWEEP_REQUIRES.items():
        keep = [rid for kind in required_kinds for rid in run_ids[kind]]
        if any(kind in kinds_incomplete or kind not in kinds_stored for kind in required_kinds):
            print(
                f"sweep {table}: SKIPPED -- not every feeding step ran and stored rows in this "
                "invocation, so old rows can't be told from not-recomputed ones"
            )
            continue
        deleted = derived_db.delete_rows_from_other_runs(derived_conn, table, keep)
        print(f"sweep {table}: deleted {deleted:,} stale rows from earlier runs")

    return not data_skips


def main():
    parser = argparse.ArgumentParser(
        description="Recompute all seven derived RS/breadth table-slices after a bar refresh, "
                    "then sweep stale rows (full-history runs only)"
    )
    parser.add_argument("--start", default=None, help="YYYY-MM-DD; default: full available history")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD; default: latest available data")
    parser.add_argument(
        "--from-step", type=int, default=1, choices=range(1, len(REFRESH_STEPS) + 1),
        help="Resume from this step number (as printed by a previous run) after a failure. "
             "Each table's sweep still only runs when every feeding step ran in THIS invocation.",
    )
    args = parser.parse_args()
    # Surface compute's own logger output (cap-outlier exclusions, the
    # share-class dedup) next to the step banners.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    def _create_tables(conn):
        breadth_store.create_breadth_table(conn)
        rs_store.create_relative_strength_tables(conn)

    raw_conn, derived_conn = derived_db.bootstrap_cli(_create_tables)
    try:
        no_data_skips = run_refresh(raw_conn, derived_conn, args.start, args.end, args.from_step)
    finally:
        raw_conn.close()
        derived_conn.close()
    if not no_data_skips:
        print("refresh finished with steps skipped for missing data -- those tables are NOT fresh", file=sys.stderr)
        sys.exit(1)
    if args.start is not None or args.end is not None:
        print("windowed refresh complete: only the --start/--end window was recomputed; no sweep ran")
    elif args.from_step > 1:
        print(
            f"resume complete: steps {args.from_step}..{len(REFRESH_STEPS)} recomputed; "
            "withheld sweeps need one full run without --from-step"
        )
    else:
        print("refresh complete: every table-slice recomputed and swept")


if __name__ == "__main__":
    main()

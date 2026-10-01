"""M22 -- Break and retest. Track B, run against the M19 placebo panel cache
(DESIGN.md M22; PREREGISTRATION.md, 2026-10-01).

Usage:
  python -m src.signals.moving_averages.break_retest_run --feasibility
      Event counts only (retest, plain-bounce and generic-move rows per cell;
      retest share of all bounces). Reads no outcome column.
  python -m src.signals.moving_averages.break_retest_run
      The pre-registered run: 32 primary cells, 192 sensitivity cells, the
      kill-criterion evaluation. Writes `m22_break_retest_{primary,
      sensitivity,kill}.csv` under output/moving_averages (gitignored).
"""

from __future__ import annotations

import argparse
import time

import pandas as pd

from src.signals.moving_averages.modules import bounce_entry as be
from src.signals.moving_averages.modules import break_retest as br
from src.signals.moving_averages.respect_history_run import OUTPUT_DIR, load_panel

PREFIX = "m22_break_retest"


def feasibility(panel: pd.DataFrame) -> pd.DataFrame:
    years = (panel["date"].max() - panel["date"].min()).days / 365.25
    n_tickers = panel["ticker"].nunique()
    rows = []
    for g in br.GROUP_ORDER:
        for d in br.DIRECTIONS:
            retest, plain, generic, base = br._arms(panel, g, d)
            ev = panel[retest]
            rows.append({
                "group": g, "direction": d, "n_retest": int(retest.sum()),
                "retest_dates": int(ev["date"].nunique()), "retest_tickers": int(ev["ticker"].nunique()),
                "n_plain_bounce": int(plain.sum()), "n_generic": int(generic.sum()), "n_base": int(base.sum()),
                "retest_share_of_bounces": float(retest.sum() / (retest.sum() + plain.sum())),
                "retest_per_ticker_year": float(retest.sum() / (years * n_tickers)),
            })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feasibility", action="store_true")
    parser.add_argument("--neighbour-check", action="store_true",
                        help="M22 lookback-neighbour addendum: SMA47/53 cells plus the coarse-match check")
    parser.add_argument("--n-boot", type=int, default=br.N_BOOT)
    args = parser.parse_args()
    t0 = time.time()

    panel = load_panel()
    print(f"panel: {panel.shape}, {panel['ticker'].nunique()} tickers, "
          f"{panel['date'].min().date()} -> {panel['date'].max().date()}", flush=True)
    context = be.add_context(panel)
    prepared = br.add_event_flags(context, br.PRIMARY_PARAMS)
    print(f"event flags added, t={time.time()-t0:.0f}s", flush=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.neighbour_check:
        table = br.neighbour_table(context, n_boot=args.n_boot)
        table.to_csv(OUTPUT_DIR / f"{PREFIX}_neighbours.csv", index=False)
        coarse = pd.DataFrame([br.coarse_match_cell(prepared, n_boot=args.n_boot)])
        coarse.to_csv(OUTPUT_DIR / f"{PREFIX}_coarse_match.csv", index=False)
        show = ["group", "horizon", "n_events", "n_dates", "overlap_with_sma50", "below_threshold", "did_c1", "did_c2",
                "did_c2_rev", "did_c2_rev_ci_low", "did_c2_rev_ci_high", "delta_focal_c2_rev", "delta_plain_c2_rev",
                "delta_focal_c2_rev_n_dates"]
        with pd.option_context("display.width", 300, "display.max_columns", 40, "display.float_format", "{:.5f}".format):
            print(table[show].to_string(index=False))
            print(coarse.to_string(index=False))
        print(f"total time {time.time()-t0:.0f}s", flush=True)
        return

    if args.feasibility:
        table = feasibility(prepared)
        table.to_csv(OUTPUT_DIR / f"{PREFIX}_feasibility.csv", index=False)
        with pd.option_context("display.width", 250, "display.max_columns", 40):
            print(table.to_string(index=False))
        return

    primary = br.primary_cell_table(prepared, n_boot=args.n_boot)
    primary.to_csv(OUTPUT_DIR / f"{PREFIX}_primary.csv", index=False)
    print(f"primary cells done, t={time.time()-t0:.0f}s", flush=True)

    sensitivity = br.sensitivity_cell_table(context, n_boot=args.n_boot)
    sensitivity.to_csv(OUTPUT_DIR / f"{PREFIX}_sensitivity.csv", index=False)
    print(f"sensitivity cells done, t={time.time()-t0:.0f}s", flush=True)

    verdict = br.evaluate_kill_criterion(primary, sensitivity)
    verdict["cells"].to_csv(OUTPUT_DIR / f"{PREFIX}_kill.csv", index=False)
    with pd.option_context("display.width", 300, "display.max_columns", 60, "display.float_format", "{:.5f}".format):
        print(f"\n=== {PREFIX} kill criterion ===")
        print(verdict["cells"].to_string(index=False))
    print(f"\nmodule_killed={verdict['module_killed']} (confirmed cells: {verdict['n_confirmed']}/{verdict['n_cells']})")
    print(f"total time {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

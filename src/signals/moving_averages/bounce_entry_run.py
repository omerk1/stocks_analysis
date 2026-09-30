"""M20 -- Confirmed bounce as an entry signal. Track B, run against the M19
placebo panel cache (DESIGN.md M20; PREREGISTRATION.md, 2026-09-30).

Usage:
  python -m src.signals.moving_averages.bounce_entry_run --feasibility
      Event counts only (bounce, generic-move and neighbour-bounce events per
      cell, overlap share). Reads no outcome column.
  python -m src.signals.moving_averages.bounce_entry_run
      The pre-registered run: 32 primary cells, 128 sensitivity cells, the
      kill-criterion evaluation. Writes `m20_bounce_entry_{primary,
      sensitivity,kill}.csv` under output/moving_averages (gitignored).

Panel: `respect_history_run.py`'s cached placebo panel (same U1 universe and
2010-01-01 -> 2021-12-31 window; built if missing).
"""

from __future__ import annotations

import argparse
import time

import pandas as pd

from src.signals.moving_averages.modules import bounce_entry as be
from src.signals.moving_averages.respect_history_run import OUTPUT_DIR, load_panel


def feasibility(panel: pd.DataFrame, event: str = "bounce") -> pd.DataFrame:
    rows = []
    for group in be.GROUP_ORDER:
        for direction in be.EVENT_SPECS[event]["directions"]:
            focal, generic, synth, base = be._arm_panels(panel, group, direction, event=event)
            ev = panel[focal]
            rows.append({
                "event": event, "group": group, "direction": direction,
                "n_focal": int(focal.sum()), "focal_dates": int(ev["date"].nunique()), "focal_tickers": int(ev["ticker"].nunique()),
                "n_generic": int(generic.sum()), "n_synth": int(synth.sum()), "n_base": int(base.sum()),
                "focal_also_synth_share": float((focal & synth).sum() / focal.sum()) if focal.sum() else float("nan"),
                "focal_also_generic_share": float((focal & generic).sum() / focal.sum()) if focal.sum() else float("nan"),
                "focal_per_ticker_year": float(focal.sum() / (panel["ticker"].nunique() * 12.0)),
            })
    return pd.DataFrame(rows)


# Output-file prefix per event type: M20 is the bounce, M21 the break
# (`break_entry_run.py` calls `main("break")`).
PREFIX = {"bounce": "m20_bounce_entry", "break": "m21_break_entry"}


def main(event: str = "bounce") -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feasibility", action="store_true")
    parser.add_argument("--n-boot", type=int, default=be.N_BOOT)
    args = parser.parse_args()
    t0 = time.time()
    prefix = PREFIX[event]

    panel = load_panel()
    print(f"panel: {panel.shape}, {panel['ticker'].nunique()} tickers, "
          f"{panel['date'].min().date()} -> {panel['date'].max().date()}", flush=True)
    context = be.add_context(panel)
    prepared = be.add_event_flags(context, be.PRIMARY_PARAMS)
    print(f"event flags added, t={time.time()-t0:.0f}s", flush=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.feasibility:
        table = feasibility(prepared, event)
        table.to_csv(OUTPUT_DIR / f"{prefix}_feasibility.csv", index=False)
        with pd.option_context("display.width", 250, "display.max_columns", 40):
            print(table.to_string(index=False))
        return

    primary = be.primary_cell_table(prepared, event=event, n_boot=args.n_boot)
    primary.to_csv(OUTPUT_DIR / f"{prefix}_primary.csv", index=False)
    print(f"primary cells done, t={time.time()-t0:.0f}s", flush=True)

    sensitivity = be.sensitivity_cell_table(context, event=event, n_boot=args.n_boot)
    sensitivity.to_csv(OUTPUT_DIR / f"{prefix}_sensitivity.csv", index=False)
    print(f"sensitivity cells done, t={time.time()-t0:.0f}s", flush=True)

    verdict = be.evaluate_kill_criterion(primary, sensitivity, event=event)
    verdict["cells"].to_csv(OUTPUT_DIR / f"{prefix}_kill.csv", index=False)

    show = ["group", "direction", "horizon", "n_events", "n_dates", "below_threshold", "delta_focal_c1", "delta_focal_c2",
            "delta_focal_c2_rev", "delta_focal_ci_low", "delta_focal_ci_high", "delta_generic_c2_rev",
            "did_c2_rev", "did_c2_rev_ci_low", "did_c2_rev_ci_high", "did_synth", "focal_also_synth_share"]
    with pd.option_context("display.width", 300, "display.max_columns", 60, "display.float_format", "{:.5f}".format):
        print(f"\n=== {prefix} primary cells ===")
        print(primary[show].to_string(index=False))
        print(f"\n=== {prefix} kill criterion ===")
        print(verdict["cells"].to_string(index=False))
    print(f"\nmodule_killed={verdict['module_killed']} (confirmed cells: {verdict['n_confirmed']}/{verdict['n_cells']})")
    print(f"total time {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

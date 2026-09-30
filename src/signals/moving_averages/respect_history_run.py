"""M19 -- MA respect history. Track B, run against the real §7.5/M5-style
placebo panel (DESIGN.md M19; PREREGISTRATION.md, 2026-09-30).

Usage:
  python -m src.signals.moving_averages.respect_history_run --build-panel
      Build (or rebuild) and cache the placebo panel with M19's four groups
      to `output/moving_averages/m19_placebo_panel.parquet` (gitignored).
  python -m src.signals.moving_averages.respect_history_run --feasibility
      Pre-registration feasibility counts ONLY: events per respect bucket
      and how many dates would contribute a valid stratum at each control
      tier. Reads no outcome column -- safe to run before freezing the
      grid, and PREREGISTRATION.md records the numbers.
  python -m src.signals.moving_averages.respect_history_run
      The pre-registered run: 16 primary cells, 48 sensitivity cells, the
      kill-criterion evaluation. Writes `m19_respect_history_primary.csv`,
      `m19_respect_history_sensitivity.csv`, `m19_respect_history_kill.csv`.

Same U1 universe and dev window as M5: S&P 500 constituents as of the
holdout boundary with full 2010-2021 coverage, bars 2010-01-01 ->
2021-12-31 (`end` = the holdout lock, CLAUDE.md invariant #1).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.utils.config_loader import load_config
from src.signals.moving_averages.cli import (
    HOLDOUT_BOUNDARY,
    SP500_UNIVERSE_AS_OF as AS_OF,
    SP500_UNIVERSE_COVERAGE_END as COVERAGE_END,
    SP500_UNIVERSE_COVERAGE_START as COVERAGE_START,
)
from src.signals.moving_averages.data import sp500_full_coverage_tickers
from src.signals.moving_averages.features.placebo_ma import build_placebo_panel
from src.signals.moving_averages.modules import respect_history as rh

DEV_START = "2010-01-01"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"
PANEL_CACHE = OUTPUT_DIR / "m19_placebo_panel.parquet"


def build_and_cache_panel() -> pd.DataFrame:
    t0 = time.time()
    config = load_config()
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    tickers = sp500_full_coverage_tickers(conn, AS_OF, COVERAGE_START, COVERAGE_END)
    print(f"universe: {len(tickers)} tickers", flush=True)
    panel = build_placebo_panel(conn, tickers, start=DEV_START, end=HOLDOUT_BOUNDARY, groups=rh.GROUPS)
    conn.close()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_CACHE, index=False)
    print(f"panel {panel.shape}, {panel['date'].min().date()} -> {panel['date'].max().date()}, "
          f"cached to {PANEL_CACHE}, t={time.time()-t0:.0f}s", flush=True)
    return panel


def load_panel() -> pd.DataFrame:
    if not PANEL_CACHE.exists():
        return build_and_cache_panel()
    panel = pd.read_parquet(PANEL_CACHE)
    assert panel["date"].max() <= pd.Timestamp(HOLDOUT_BOUNDARY), "cached panel crosses the holdout boundary"
    return panel


def touch_tables(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    tables = {g: rh.group_touch_table(panel, g) for g in rh.GROUP_ORDER}
    for g, t in tables.items():
        print(f"  {g}: {len(t):,} touch events ({int(t['is_focal'].sum()):,} focal), t={time.time()-t0:.0f}s", flush=True)
    return tables


def feasibility(panel: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Counts only. No outcome column is read."""
    rows = []
    for group in rh.GROUP_ORDER:
        events = rh.attach_respect(tables[group], panel)
        for direction in rh.DIRECTIONS:
            sub = events[(events["direction"] == direction)].dropna(subset=["respect"])
            row = {"group": group, "direction": direction}
            for is_focal, arm in ((True, "focal"), (False, "synth")):
                arm_rows = sub[sub["is_focal"] == is_focal]
                counts = arm_rows["respect_bucket"].value_counts()
                for b in (0, 1, 2):
                    row[f"{arm}_r{b}"] = int(counts.get(float(b), 0))
                row[f"{arm}_r2_dates"] = int(arm_rows.loc[arm_rows["respect_bucket"] == 2, "date"].nunique())
                row[f"{arm}_r2_tickers"] = int(arm_rows.loc[arm_rows["respect_bucket"] == 2, "ticker"].nunique())
            for tier, match_cols in rh.CONTROL_TIERS.items():
                pop = sub[sub["respect_bucket"] != 1].dropna(subset=list(match_cols))
                for is_focal, arm in ((True, "focal"), (False, "synth")):
                    arm_rows = pop[pop["is_focal"] == is_focal]
                    strata = arm_rows.groupby(["date", *match_cols], observed=True)["high_respect"].agg(
                        lambda s: s.astype(bool).any() and (~s.astype(bool)).any()
                    )
                    valid = strata[strata]
                    row[f"{arm}_{tier}_strata"] = int(len(valid))
                    row[f"{arm}_{tier}_dates"] = int(valid.index.get_level_values("date").nunique()) if len(valid) else 0
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-panel", action="store_true")
    parser.add_argument("--feasibility", action="store_true")
    parser.add_argument("--n-boot", type=int, default=500)
    args = parser.parse_args()
    t0 = time.time()

    if args.build_panel:
        build_and_cache_panel()
        return

    panel = load_panel()
    print(f"panel: {panel.shape}, {panel['ticker'].nunique()} tickers, "
          f"{panel['date'].min().date()} -> {panel['date'].max().date()}", flush=True)
    context = rh.add_context(panel)
    tables = touch_tables(context)
    prepared = rh.add_respect_columns(context, rh.PRIMARY_PARAMS)
    print(f"respect columns added, t={time.time()-t0:.0f}s", flush=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.feasibility:
        table = feasibility(prepared, tables)
        out = OUTPUT_DIR / "m19_respect_history_feasibility.csv"
        table.to_csv(out, index=False)
        with pd.option_context("display.width", 250, "display.max_columns", 60):
            print(table.to_string(index=False))
        print(f"wrote {out}", flush=True)
        return

    primary = rh.primary_cell_table(tables, prepared, n_boot=args.n_boot)
    primary.to_csv(OUTPUT_DIR / "m19_respect_history_primary.csv", index=False)
    print(f"primary cells done, t={time.time()-t0:.0f}s", flush=True)

    sensitivity = rh.sensitivity_cell_table(tables, context, n_boot=args.n_boot)
    sensitivity.to_csv(OUTPUT_DIR / "m19_respect_history_sensitivity.csv", index=False)
    print(f"sensitivity cells done, t={time.time()-t0:.0f}s", flush=True)

    verdict = rh.evaluate_kill_criterion(primary, sensitivity)
    verdict["cells"].to_csv(OUTPUT_DIR / "m19_respect_history_kill.csv", index=False)

    show = ["group", "direction", "outcome", "n_events", "n_dates", "n_tickers", "below_threshold",
            "did_c1", "did_c2", "did_c2_rev", "did_c2_rev_ci_low", "did_c2_rev_ci_high", "did_c2_rev_n_dates",
            "delta_focal_c2_rev", "delta_synth_c2_rev", "ci_excludes_zero"]
    with pd.option_context("display.width", 250, "display.max_columns", 60, "display.float_format", "{:.5f}".format):
        print("\n=== M19 primary cells ===")
        print(primary[show].to_string(index=False))
        print("\n=== M19 sensitivity (hold, c2_rev) ===")
        print(sensitivity[["group", "direction", "variant", "n_events", "did_c2_rev", "did_c2_rev_ci_low",
                           "did_c2_rev_ci_high", "did_c2_rev_n_dates"]].to_string(index=False))
        print("\n=== M19 kill criterion ===")
        print(verdict["cells"].to_string(index=False))
    print(f"\nmodule_killed={verdict['module_killed']} (confirmed cells: {verdict['n_confirmed']}/{verdict['n_cells']})")
    print(f"total time {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

"""M6.6 -- Slope agreement across the ribbon. Track B, run against the real
cached panel (DESIGN.md M6.6; PREREGISTRATION.md, 2026-09-23). Prints the
correlation matrix (required regardless of outcome), the shape table, both
`extreme_state_test` cells (fwd_ret_21, fwd_mdd_21), and the cost
annotation. Writes the raw results to
`output/moving_averages/m6_6_ribbon_slope_agreement_results.csv`
(gitignored, reproducible via this script -- same convention as every
other Track A/B driving script in this study, e.g. `high_low_52w_run.py`).
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.utils.config_loader import load_config
from src.signals.moving_averages.cli import (
    SP500_UNIVERSE_AS_OF as AS_OF,
    SP500_UNIVERSE_COVERAGE_END as COVERAGE_END,
    SP500_UNIVERSE_COVERAGE_START as COVERAGE_START,
)
from src.signals.moving_averages.data import sp500_full_coverage_tickers
from src.signals.moving_averages.features.panel import read_panel
from src.signals.moving_averages.modules.ribbon_slope_agreement import cost_annotation, prepare, run_grid
from src.signals.moving_averages.stats.costs import annualize, ci_clears_cost, point_clears_cost

DEV_START = "2010-01-01"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"


def main() -> None:
    t0 = time.time()
    config = load_config()
    cache_dir = Path(config.data_paths.features) / "moving_averages" / "ma_panel"
    db_path = db.default_db_path(config.data_paths.raw)
    conn = db.get_connection(db_path)
    tickers = sp500_full_coverage_tickers(conn, AS_OF, COVERAGE_START, COVERAGE_END)
    conn.close()

    panel = read_panel(cache_dir, start=DEV_START, end=AS_OF)
    panel = panel[panel["ticker"].isin(tickers)]
    print(f"panel: {panel.shape}, {panel['ticker'].nunique()} tickers, t={time.time()-t0:.0f}s", flush=True)

    results = run_grid(panel)
    print(f"grid run complete, t={time.time()-t0:.0f}s", flush=True)

    print("\n=== Correlation matrix (required regardless of outcome) ===")
    with pd.option_context("display.width", 200, "display.max_rows", 30):
        print(results["correlation_matrix"].to_string(index=False))

    print("\n=== Shape table (descriptive, 6 ordinal states) ===")
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(results["shape_table"].to_string(index=False))

    rows = []
    for key in ("extreme_state_test_return", "extreme_state_test_drawdown"):
        r = results[key]
        hurdle = results["cost"]["hurdle_annual"]
        point_ann = annualize(r["c2"], horizon=21) if not pd.isna(r["c2"]) else float("nan")
        ci_low_ann = annualize(r["ci_low"], horizon=21) if not pd.isna(r["ci_low"]) else float("nan")
        ci_high_ann = annualize(r["ci_high"], horizon=21) if not pd.isna(r["ci_high"]) else float("nan")
        row = {
            "cell": key,
            "value_col": r["value_col"],
            "n_events": r["n_events"], "n_dates": r["n_dates"], "n_tickers": r["n_tickers"],
            "below_threshold": r["below_threshold"],
            "c2_point": r["c2"], "ci_low": r["ci_low"], "ci_high": r["ci_high"],
            "edge": r["edge"], "kill_threshold": r["kill_threshold"], "killed": r["killed"],
            "ci_excludes_zero": r["ci_excludes_zero"],
            "signals_per_year": results["cost"]["signals_per_year"],
            "cost_hurdle_annual": hurdle,
            "c2_point_annualized": point_ann,
            "c2_ci_low_annualized": ci_low_ann,
            "c2_ci_high_annualized": ci_high_ann,
            "point_clears_cost": point_clears_cost(point_ann, hurdle) if not pd.isna(point_ann) else None,
            "ci_clears_cost": ci_clears_cost(ci_low_ann, ci_high_ann, hurdle) if not pd.isna(ci_low_ann) else None,
            "hit_rate": r["shape"]["hit_rate"],
            "hit_rate_delta_c2": r["shape"].get("hit_rate_delta_c2"),
            "win_loss_ratio": r["shape"]["win_loss_ratio"],
            "skew": r["shape"]["skew"],
        }
        rows.append(row)

    result_df = pd.DataFrame(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "m6_6_ribbon_slope_agreement_results.csv"
    result_df.to_csv(out_path, index=False)
    corr_path = OUTPUT_DIR / "m6_6_ribbon_slope_agreement_correlation_matrix.csv"
    results["correlation_matrix"].to_csv(corr_path, index=False)
    shape_path = OUTPUT_DIR / "m6_6_ribbon_slope_agreement_shape_table.csv"
    results["shape_table"].to_csv(shape_path, index=False)
    print(f"wrote {out_path}, {corr_path}, {shape_path}", flush=True)

    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print("\n=== M6.6 decisive-cell result table ===")
        print(result_df.to_string(index=False))

    print(f"\ntotal time {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

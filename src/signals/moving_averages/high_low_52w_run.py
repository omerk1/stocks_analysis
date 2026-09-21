"""M18 -- 52-week high/low range as a standalone predictor. Track B, run
against the real cached panel (DESIGN.md M18; PREREGISTRATION.md,
2026-09-20). Prints the full result table and the same-module correlation
check (dist_from_52w_high vs dist_from_52w_low, per-date median Spearman)
the pre-registration entry commits to checking before trusting the 4-cell
grid as independent. Writes the raw per-cell dict to
`output/moving_averages/m18_high_low_52w_results.csv` for later reference
(gitignored, reproducible via this script -- same convention as every
other Track A/B driving script in this study).
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
from src.signals.moving_averages.modules.high_low_52w import FEATURES, HORIZONS, run_grid
from src.signals.moving_averages.stats.costs import annualize, ci_clears_cost, point_clears_cost

DEV_START = "2010-01-01"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"


def per_date_median_corr(panel: pd.DataFrame, col_a: str, col_b: str, date_col: str = "date") -> float:
    sub = panel[[date_col, col_a, col_b]].dropna()

    def _corr(g: pd.DataFrame) -> float:
        return g[col_a].corr(g[col_b], method="spearman")

    corrs = sub.set_index(date_col).groupby(level=0).apply(_corr)
    return corrs.median()


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

    corr = per_date_median_corr(panel, "dist_from_52w_high", "dist_from_52w_low")
    print(f"per-date median Spearman(dist_from_52w_high, dist_from_52w_low) = {corr:.4f}", flush=True)

    results = run_grid(panel)
    print(f"grid run complete, t={time.time()-t0:.0f}s", flush=True)

    rows = []
    for key, r in results.items():
        cost = r["cost"]
        c2 = r["spread_c2"]
        hurdle = cost["cost_hurdle_annual"]
        point_ann = annualize(c2["point_estimate"], horizon=r["horizon"])
        ci_low_ann = annualize(c2["ci_low"], horizon=r["horizon"])
        ci_high_ann = annualize(c2["ci_high"], horizon=r["horizon"])
        row = {
            "feature": r["feature"],
            "horizon": r["horizon"],
            "n_events": r["n_events"],
            "n_dates": r["n_dates"],
            "n_tickers": r["n_tickers"],
            "below_threshold": r["below_threshold"],
            "ic_point": r["ic"]["point_estimate"],
            "ic_ci_low": r["ic"]["ci_low"],
            "ic_ci_high": r["ic"]["ci_high"],
            "c1_point": r["spread_c1"]["point_estimate"],
            "c1_ci_low": r["spread_c1"]["ci_low"],
            "c1_ci_high": r["spread_c1"]["ci_high"],
            "c2_point": c2["point_estimate"],
            "c2_ci_low": c2["ci_low"],
            "c2_ci_high": c2["ci_high"],
            "c2_ci_excludes_zero": not (c2["ci_low"] <= 0 <= c2["ci_high"]),
            "c2_reversal_point": r["spread_c2_reversal"]["point_estimate"],
            "c2_reversal_ci_low": r["spread_c2_reversal"]["ci_low"],
            "c2_reversal_ci_high": r["spread_c2_reversal"]["ci_high"],
            "signals_per_year_combined": cost["signals_per_year_combined"],
            "cost_hurdle_annual": hurdle,
            "c2_point_annualized": point_ann,
            "c2_ci_low_annualized": ci_low_ann,
            "c2_ci_high_annualized": ci_high_ann,
            "point_clears_cost": point_clears_cost(point_ann, hurdle),
            "ci_clears_cost": ci_clears_cost(ci_low_ann, ci_high_ann, hurdle),
        }
        rows.append(row)

    result_df = pd.DataFrame(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "m18_high_low_52w_results.csv"
    result_df.to_csv(out_path, index=False)
    print(f"wrote {out_path}", flush=True)

    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print("\n=== M18 full result table ===")
        print(result_df.to_string(index=False))

    print(f"\ntotal time {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

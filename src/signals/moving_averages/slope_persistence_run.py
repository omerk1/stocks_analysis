"""M6.4 -- Slope persistence and flip hazard. Track B, run against the real
cached panel (DESIGN.md M6.4; PREREGISTRATION.md 2026-09-24 entry and its
2026-09-29 re-run addendum). For every (lookback, tercile) stratum of the
primary vol-tercile grid and the ER-tercile companion facet, prints the
empirical 21-day survival of rising slope runs against two GBM nulls built
from the same simulated paths:

- `pooled`  -- rising and falling simulated runs pooled (the 2026-09-24
  behaviour; reproduces the logged numbers, kept so the reproduction is
  part of the record), and
- `matched` -- simulated runs filtered to the same sign as the empirical
  stratum (`gbm_null_survival(direction=True)`, the corrected null --
  code review PR #118 finding C1).

Writes the raw results to
`output/moving_averages/slope_persistence_results.csv` (gitignored,
reproducible via this script -- same convention as every other driving
script in this study, e.g. `ribbon_slope_agreement_run.py`). Holdout
untouched: the panel is read with `end=2021-12-31`.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from src.foundation.utils.config_loader import load_config
from src.signals.moving_averages.features.panel import read_panel
from src.signals.moving_averages.modules import slope_persistence as sp
from src.signals.moving_averages.stats.survival import gbm_null_survival, kaplan_meier, survival_at

DEV_END = "2021-12-31"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"
GRIDS = (
    ("entry_vol_tercile", sp.N_VOL_BUCKETS, "vol_tercile"),
    ("entry_er_tercile", sp.N_ER_BUCKETS, "er_tercile"),
)
NULLS = (("pooled", None), ("matched", True))


def stratum_rows(working: pd.DataFrame, run_table: pd.DataFrame, lookback: int) -> list[dict]:
    rows = []
    for stratify_col, n_buckets, label in GRIDS:
        calibration = sp.gbm_calibration(
            working, run_table, direction=True, stratify_col=stratify_col, n_buckets=n_buckets
        )
        for tercile in range(n_buckets):
            subset = run_table[(run_table[stratify_col] == tercile) & (run_table["direction"] == True)]  # noqa: E712
            empirical = survival_at(kaplan_meier(subset["duration"], subset["event"]), sp.REFERENCE_HORIZON)
            sigma = calibration["sigma_by_tercile"][tercile]
            row = {
                "cell_id": f"slope_persistence_{label}_sma{lookback}_t{tercile}",
                "lookback": lookback,
                "stratify": label,
                "tercile": tercile,
                "n_runs": len(subset),
                "n_flips": int(subset["event"].sum()),
                "n_tickers": subset["ticker"].nunique(),
                "n_entry_dates": subset["entry_date"].nunique(),
                "empirical_s21": empirical,
                "sigma": sigma,
                "mu": calibration["mu"],
            }
            for tag, direction in NULLS:
                null = gbm_null_survival(
                    n_paths=sp.GBM_N_PATHS,
                    n_days=sp.GBM_N_DAYS,
                    mu=calibration["mu"],
                    sigma=sigma,
                    sma_period=lookback,
                    slope_k=sp.SLOPE_K,
                    seed=tercile * 100 + lookback,
                    n_groups=sp.GBM_N_GROUPS,
                    direction=direction,
                )
                null_s21 = survival_at(null["km"], sp.REFERENCE_HORIZON)
                lo, hi = null["envelope"][sp.REFERENCE_HORIZON]
                row[f"{tag}_null_s21"] = null_s21
                row[f"{tag}_delta"] = empirical - null_s21
                row[f"{tag}_env_lo"] = lo - null_s21
                row[f"{tag}_env_hi"] = hi - null_s21
                row[f"{tag}_departs"] = bool(empirical < lo or empirical > hi)
            rows.append(row)
    return rows


def main() -> None:
    t0 = time.time()
    config = load_config()
    cache_dir = Path(config.data_paths.features) / "moving_averages" / "ma_panel"
    panel = read_panel(cache_dir, end=DEV_END)
    assert panel["date"].max() <= pd.Timestamp(DEV_END)
    print(f"panel: {len(panel):,} rows, {panel['ticker'].nunique()} tickers, to {panel['date'].max().date()}")
    working = sp.prepare(panel)

    rows: list[dict] = []
    for lookback in sp.LOOKBACKS:
        run_table = sp.build_run_table(working, lookback)
        rows.extend(stratum_rows(working, run_table, lookback))
        print(f"lookback {lookback} done ({time.time() - t0:.0f}s)")

    results = pd.DataFrame(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "slope_persistence_results.csv"
    results.to_csv(out, index=False)

    show = ["cell_id", "n_runs", "pooled_delta", "pooled_departs", "matched_delta", "matched_env_lo", "matched_env_hi", "matched_departs"]
    print(results[show].round(4).to_string(index=False))
    primary = results[results["stratify"] == "vol_tercile"]
    print(
        f"primary grid departing: pooled {int(primary['pooled_departs'].sum())}/12, "
        f"matched {int(primary['matched_departs'].sum())}/12 "
        f"(module killed under matched null: {not primary['matched_departs'].any()})"
    )
    print(f"wrote {out} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

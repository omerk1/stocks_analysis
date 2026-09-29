"""Whole-grid Benjamini-Hochberg pass over `EXPERIMENTS.csv` (DESIGN.md §6.6;
STATUS.md "Whole-grid FDR pass"). Every earlier pass (2026-09-17 ... 2026-09-25)
was run in-conversation; this script makes the pass reproducible from the
ledger alone.

Grid: rows with `counted_in_n_tests == True`. p-values: `p_value_from_ci`
(a labelled Wald back-out of each row's 90% block-bootstrap CI). Rows whose
`ci_low`/`ci_high` are not a CI on the estimate -- M6.4's survival cells,
whose columns hold the GBM null's simulation envelope (VALIDATION_2026-09-28.md
§D.2) -- stay in the grid at p = 1: they are declared tests and belong in the
denominator, but no p-value can be backed out of an envelope. Rows with a NaN
CI (unresolved cells, descriptive coefficients) are excluded from the grid, as
every earlier pass did.

Usage: `python -m src.signals.moving_averages.whole_grid_fdr_run [--q 0.10]`
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.signals.moving_averages.stats.multiple_testing import benjamini_hochberg, p_value_from_ci

LEDGER = Path(__file__).resolve().parents[3] / "docs" / "features" / "moving-averages" / "EXPERIMENTS.csv"
ENVELOPE_NOT_CI_PREFIX = "slope_persistence_"


def load_grid(ledger: Path = LEDGER) -> pd.DataFrame:
    rows = pd.read_csv(ledger)
    counted = rows[rows["counted_in_n_tests"].astype(str).str.lower() == "true"].copy()
    for col in ("point_estimate", "ci_low", "ci_high"):
        counted[col] = pd.to_numeric(counted[col], errors="coerce")
    counted["envelope_not_ci"] = counted["cell_id"].str.startswith(ENVELOPE_NOT_CI_PREFIX)
    valid = counted[counted["envelope_not_ci"] | counted[["point_estimate", "ci_low", "ci_high"]].notna().all(axis=1)].copy()
    valid["p_value"] = [
        1.0 if env else p_value_from_ci(pe, lo, hi)
        for env, pe, lo, hi in zip(valid["envelope_not_ci"], valid["point_estimate"], valid["ci_low"], valid["ci_high"])
    ]
    valid = valid.dropna(subset=["p_value"])
    return valid


def run(q: float, ledger: Path = LEDGER) -> pd.DataFrame:
    grid = load_grid(ledger).sort_values("p_value").reset_index(drop=True)
    n = len(grid)
    grid["rank"] = np.arange(1, n + 1)
    grid["bh_threshold"] = grid["rank"] / n * q
    grid["reject"] = benjamini_hochberg(grid["p_value"].to_numpy(), q=q)
    return grid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--q", type=float, default=0.10)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    for q in sorted({args.q, 0.05, 0.10}):
        grid = run(q)
        n_reject = int(grid["reject"].sum())
        print(f"\nq={q:.2f}: N_tests={len(grid)}, rejected={n_reject}")
        show = grid.loc[: args.top - 1, ["rank", "module", "cell_id", "point_estimate", "p_value", "bh_threshold", "reject"]]
        print(show.to_string(index=False, float_format=lambda v: f"{v:.6g}"))


if __name__ == "__main__":
    main()

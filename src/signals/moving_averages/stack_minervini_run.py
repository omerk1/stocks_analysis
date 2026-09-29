"""M2 -- Stack states and Minervini ablation. Track B, run against the real
cached panel (PREREGISTRATION.md M2 entry and its 2026-09-29 re-run
addendum). Prints both primary cells (standalone C2 and incremental vs
`above_sma_50`), their reversal companions, the 8 ablation coefficients and
the cost annotation; writes `output/moving_averages/stack_minervini_results.csv`
(gitignored). Holdout untouched: panel read with `end=2021-12-31`.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.utils.config_loader import load_config
from src.signals.moving_averages.features.panel import read_panel
from src.signals.moving_averages.modules import stack_minervini as m2

DEV_END = "2021-12-31"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"


def main() -> None:
    t0 = time.time()
    config = load_config()
    cache_dir = Path(config.data_paths.features) / "moving_averages" / "ma_panel"
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    panel = read_panel(cache_dir, end=DEV_END)
    assert panel["date"].max() <= pd.Timestamp(DEV_END)
    working = m2.prepare(panel, conn)
    print(f"prepared {len(working):,} rows ({time.time() - t0:.0f}s)")

    frames = []
    for label, match_cols in (("default", m2.C2_MATCH_COLS), ("reversal", m2.C2_MATCH_COLS_WITH_REVERSAL)):
        primary = m2.primary_stack_table(working, match_cols=match_cols).assign(kind="standalone", match=label)
        frames.append(primary)
        print(primary[["cell", "n_events", "n_dates", "c2", "c2_ci_low", "c2_ci_high", "hit_rate", "skew"]].to_string(index=False))
    incremental = m2.incremental_vs_single_ma_table(working).assign(kind="incremental", match="default")
    frames.append(incremental)
    print(incremental.to_string(index=False))
    print("part (a) kill:", m2.evaluate_part_a_kill_criterion(incremental))

    ablation = m2.linear_attribution(working).assign(kind="ablation")
    frames.append(ablation)
    print(ablation.to_string(index=False))
    for col in ("stack_fully_bullish", "stack_fully_bearish"):
        print(col, m2.cost_annotation(working, state_col=col))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "stack_minervini_results.csv"
    pd.concat(frames, ignore_index=True).to_csv(out, index=False)
    print(f"wrote {out} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

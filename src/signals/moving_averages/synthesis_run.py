"""M15 -- Synthesis: overlap/enrichment check between M6.3's extreme-slope
tail and M14's VCP-reclaim population (DESIGN.md M15; PREREGISTRATION.md
2026-09-25 entry + 2026-09-29 re-run addendum). Track A diagnostic, no
`N_tests` footprint.

Re-run on the as-of-safe pattern flag (`modules/pattern_context.py::
attach_breakout_dates`, 2026-09-29) -- the 2026-09-25 run consumed the
formation_end-anchored flag whose VCP population was one-third look-ahead
events. Prints the four tail rates and three enrichment ratios; writes
`output/moving_averages/synthesis_results.csv` (gitignored). Holdout
untouched: panel read with `end=2021-12-31`, patterns/bars with `as_of`.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.utils.config_loader import load_config
from src.signals.moving_averages.features.panel import read_panel
from src.signals.moving_averages.modules import pattern_context as pc
from src.signals.moving_averages.modules.synthesis import overlap_enrichment

AS_OF = "2021-12-31"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"


def main() -> None:
    t0 = time.time()
    config = load_config()
    cache_dir = Path(config.data_paths.features) / "moving_averages" / "ma_panel"
    raw_conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    derived_conn = sqlite3.connect(f"file:{Path(config.data_paths.derived) / 'analysis.sqlite'}?mode=ro", uri=True)

    panel = read_panel(cache_dir, end=AS_OF)
    assert panel["date"].max() <= pd.Timestamp(AS_OF)
    tickers = sorted(panel["ticker"].unique())
    patterns = pc.attach_breakout_dates(pc.load_qualifying_patterns(derived_conn, tickers, AS_OF), raw_conn, AS_OF)
    print(f"panel {len(panel):,} rows / {len(tickers)} tickers; {len(patterns):,} qualifying patterns ({time.time() - t0:.0f}s)")

    result = overlap_enrichment(panel, patterns)
    for key, value in result.items():
        print(f"{key}: {value:.4f}" if isinstance(value, float) else f"{key}: {value}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "synthesis_results.csv"
    pd.DataFrame([result]).to_csv(out, index=False)
    print(f"wrote {out} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

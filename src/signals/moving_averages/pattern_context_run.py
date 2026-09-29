"""M14 -- Integration with existing detectors. Track B, run against the real
cached panel and the `pattern_matches` table (DESIGN.md M14; PREREGISTRATION.md
2026-09-25 entry + VCP addendum + 2026-09-29 as-of-safe re-run addendum).

Runs the pooled cell (all pattern types) and the VCP-only cell, each with the
default C2 match and the `ext_tercile` / `rev_tercile` companions, on the
as-of-safe event flag (window anchored strictly after the pattern's own
breakout date, `modules/pattern_context.py::attach_breakout_dates`). Prints
every cell with its effective N and shape statistics; writes the raw results
to `output/moving_averages/pattern_context_results.csv` (gitignored,
reproducible via this script -- same convention as the study's other driving
scripts). Holdout untouched: panel read with `end=2021-12-31`, bars and
patterns loaded with `as_of=2021-12-31`.
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
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas

AS_OF = "2021-12-31"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"
POPULATIONS = (("pooled", None), ("vcp_only", "vcp"))
COMPANIONS = (
    ("default", list(pc.C2_MATCH_COLS)),
    ("extension_neutralized", [*pc.C2_MATCH_COLS, "ext_tercile"]),
    ("reversal_robustness", [*pc.C2_MATCH_COLS, "rev_tercile"]),
)


def run_cell(working: pd.DataFrame, match_cols: list[str]) -> dict:
    events = working[working["is_reclaim_50"]]
    subset = events.dropna(subset=["fwd_ret_21", *match_cols])
    in_ctx = subset[subset["in_pattern_context"]]
    row = {
        "n_events_in_context": len(in_ctx),
        "n_dates_in_context": in_ctx["date"].nunique(),
        "n_tickers_in_context": in_ctx["ticker"].nunique(),
        "n_events_population": len(subset),
        "n_dates_population": subset["date"].nunique(),
    }
    try:
        boot = block_bootstrap_delta(subset, "in_pattern_context", "fwd_ret_21", match_cols=match_cols)
        row.update({"c2": boot["point_estimate"], "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
                    "n_dates_bootstrap": boot["n_dates"], "status": "ok"})
    except InsufficientBlocksError as exc:
        row.update({"c2": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                    "n_dates_bootstrap": float("nan"), "status": f"InsufficientBlocksError: {exc}"})
    hit = hit_rate_deltas(subset, "in_pattern_context", "fwd_ret_21", match_cols=match_cols)
    row.update({f"hit_{k}": v for k, v in hit.items()})
    shape_in = distribution_shape(in_ctx["fwd_ret_21"])
    row.update({f"shape_in_{k}": v for k, v in shape_in.items()})
    return row


def main() -> None:
    t0 = time.time()
    config = load_config()
    cache_dir = Path(config.data_paths.features) / "moving_averages" / "ma_panel"
    raw_conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    derived_conn = sqlite3.connect(f"file:{Path(config.data_paths.derived) / 'analysis.sqlite'}?mode=ro", uri=True)

    panel = read_panel(cache_dir, end=AS_OF)
    assert panel["date"].max() <= pd.Timestamp(AS_OF)
    tickers = sorted(panel["ticker"].unique())
    print(f"panel: {len(panel):,} rows, {len(tickers)} tickers ({time.time() - t0:.0f}s)")

    patterns = pc.load_qualifying_patterns(derived_conn, tickers, AS_OF)
    patterns = pc.attach_breakout_dates(patterns, raw_conn, AS_OF)
    n_unverified = int(patterns["breakout_date"].isna().sum())
    print(f"qualifying patterns: {len(patterns):,} ({n_unverified} without a verifiable breakout date, excluded); "
          f"vcp: {int((patterns['pattern_type'] == 'vcp').sum()):,} ({time.time() - t0:.0f}s)")
    print("status mix of qualifying patterns:", patterns["status"].value_counts().to_dict())

    rows = []
    for pop_label, pattern_type in POPULATIONS:
        subset_patterns = patterns if pattern_type is None else patterns[patterns["pattern_type"] == pattern_type]
        working = pc.prepare(panel, subset_patterns)
        working["ext_tercile"] = cross_sectional_bucket(working, "dist_pct_sma_50", n_buckets=3)
        working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)
        for comp_label, match_cols in COMPANIONS:
            row = {"population": pop_label, "companion": comp_label, "match_cols": "+".join(match_cols)}
            row.update(run_cell(working, match_cols))
            rows.append(row)
            print(f"{pop_label}/{comp_label}: c2={row['c2']:+.6f} [{row['ci_low']:+.6f}, {row['ci_high']:+.6f}] "
                  f"in-context {row['n_events_in_context']} ev / {row['n_dates_in_context']} dates / "
                  f"{row['n_tickers_in_context']} tickers; bootstrap dates {row['n_dates_bootstrap']}; {row['status']} "
                  f"({time.time() - t0:.0f}s)")

    results = pd.DataFrame(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "pattern_context_results.csv"
    results.to_csv(out, index=False)
    print(f"wrote {out} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

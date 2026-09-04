"""python -m src.signals.breadth.cli --index sp500|nasdaq100|all [--weighting equal|cap]
    [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Computes market breadth, upserts it into the derived DB, and prints a
summary. Structurally different from gaps/divergences/etc's `TICKER|--all`
CLIs -- breadth has no per-ticker axis (it aggregates *across* an index's
constituents), so the loop here is over indices, not tickers. `runs` still
needs a `ticker`/`timeframe` (NOT NULL columns on the shared table) --
`index_name` fills the `ticker` slot and `timeframe` is always "daily"
(breadth is daily-only for now), a deliberate repurposing rather than a
schema change to the table every module shares.
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from src.signals.breadth import store
from src.signals.breadth.compute import compute_breadth
from src.signals.breadth.config import WEIGHTING_CHOICES, BreadthConfig
from src.foundation.market_common import derived_db


def run_for_index(raw_conn, derived_conn, index_name: str, config: BreadthConfig, start, end):
    breadth = compute_breadth(raw_conn, index_name, config, start=start, end=end)
    if breadth.empty:
        return breadth, "no membership/price/market-cap data for this index"

    run_id = derived_db.record_run(
        derived_conn, "breadth", index_name, "daily", end,
        json.dumps(dataclasses.asdict(config)), 0, False,
    )
    store.upsert_breadth(derived_conn, index_name, breadth, run_id, weighting=config.weighting)
    return breadth, None


def main():
    parser = argparse.ArgumentParser(description="Compute market breadth for S&P 500 / Nasdaq-100")
    parser.add_argument(
        "--index", required=True, choices=["sp500", "nasdaq100", "all"],
        help="Which index_membership index to compute breadth for",
    )
    parser.add_argument(
        "--weighting", default="equal", choices=WEIGHTING_CHOICES,
        help="equal: every constituent counts 1x (default). cap: weighted by real historical market cap.",
    )
    parser.add_argument("--start", default=None, help="YYYY-MM-DD; default: full available history")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD; default: latest available data")
    args = parser.parse_args()

    raw_conn, derived_conn = derived_db.bootstrap_cli(store.create_breadth_table)

    config = BreadthConfig(weighting=args.weighting)
    index_names = config.indices if args.index == "all" else [args.index]

    for index_name in index_names:
        breadth, skip_reason = run_for_index(raw_conn, derived_conn, index_name, config, args.start, args.end)
        if skip_reason is not None:
            print(f"{index_name}: SKIPPED -- {skip_reason}")
            continue
        latest = breadth.iloc[-1]
        print(
            f"{index_name} ({config.weighting}-weighted): {len(breadth)} rows, "
            f"latest ({breadth.index[-1].date()}) "
            f"n_constituents={int(latest['n_constituents'])} "
            f"pct_above_sma50={latest['pct_above_sma50']:.1%} "
            f"pct_above_sma200={latest['pct_above_sma200']:.1%}"
        )

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

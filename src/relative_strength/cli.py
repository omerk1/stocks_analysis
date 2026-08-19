"""python -m src.relative_strength.cli --index sp500|nasdaq100|all
    --tier stock-vs-market|stock-vs-sector|sector-vs-market|all [--start] [--end]

Computes relative strength, upserts it into the derived DB, and prints a
summary. Same loop-and-print shape as breadth/cli.py; sector-vs-market
isn't index-scoped (the 11 sector ETFs aren't an index_membership roster),
so `--index` is ignored for that tier.
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from src.market_common import derived_db
from src.relative_strength import store
from src.relative_strength.compute import (
    compute_sector_vs_market,
    compute_stock_vs_market,
    compute_stock_vs_sector,
)
from src.relative_strength.config import RelativeStrengthConfig

_TIERS = ("stock-vs-market", "stock-vs-sector", "sector-vs-market")


def run_stock_tier(raw_conn, derived_conn, tier: str, index_name: str, config: RelativeStrengthConfig, start, end):
    compute_fn = compute_stock_vs_market if tier == "stock-vs-market" else compute_stock_vs_sector
    comparison = "vs_market" if tier == "stock-vs-market" else "vs_sector"

    rs = compute_fn(raw_conn, index_name, config, start=start, end=end)
    if rs.empty:
        return rs, "no membership/price/sector data for this index"

    run_id = derived_db.record_run(
        derived_conn, "relative_strength", index_name, "daily", None,
        json.dumps(dataclasses.asdict(config)), 0, False,
    )
    store.upsert_relative_strength(derived_conn, comparison, rs, run_id)
    return rs, None


def run_sector_tier(raw_conn, derived_conn, config: RelativeStrengthConfig, start, end):
    rs = compute_sector_vs_market(raw_conn, config, start=start, end=end)
    if rs.empty:
        return rs, "no sector-ETF/benchmark price data"

    run_id = derived_db.record_run(
        derived_conn, "relative_strength", "sectors", "daily", None,
        json.dumps(dataclasses.asdict(config)), 0, False,
    )
    store.upsert_sector_relative_strength(derived_conn, rs, run_id)
    return rs, None


def main():
    parser = argparse.ArgumentParser(description="Compute relative strength for S&P 500 / Nasdaq-100")
    parser.add_argument("--index", required=True, choices=["sp500", "nasdaq100", "all"])
    parser.add_argument("--tier", default="all", choices=[*_TIERS, "all"])
    parser.add_argument("--start", default=None, help="YYYY-MM-DD; default: full available history")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD; default: latest available data")
    args = parser.parse_args()

    raw_conn, derived_conn = derived_db.bootstrap_cli(store.create_relative_strength_tables)

    config = RelativeStrengthConfig()
    index_names = config.indices if args.index == "all" else [args.index]
    tiers = _TIERS if args.tier == "all" else [args.tier]

    for tier in tiers:
        if tier == "sector-vs-market":
            rs, skip_reason = run_sector_tier(raw_conn, derived_conn, config, args.start, args.end)
            if skip_reason is not None:
                print(f"sector-vs-market: SKIPPED -- {skip_reason}")
                continue
            latest_date = rs["date"].max()
            latest = rs[rs["date"] == latest_date].sort_values("rs_rating", ascending=False)
            print(f"sector-vs-market: {len(rs)} rows, latest ({latest_date.date()}):")
            for row in latest.itertuples():
                print(f"  {row.sector}: rs_rating={row.rs_rating:.1f} rs_mansfield={row.rs_mansfield:.2f}")
            continue

        for index_name in index_names:
            rs, skip_reason = run_stock_tier(raw_conn, derived_conn, tier, index_name, config, args.start, args.end)
            if skip_reason is not None:
                print(f"{tier}/{index_name}: SKIPPED -- {skip_reason}")
                continue
            latest_date = rs["date"].max()
            n_latest = (rs["date"] == latest_date).sum()
            print(
                f"{tier}/{index_name}: {len(rs)} rows, latest ({latest_date.date()}) "
                f"n_tickers={n_latest}"
            )

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

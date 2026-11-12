"""python -m src.signals.relative_strength.cli
    [--tier stock-vs-market|stock-vs-sector|sector-vs-market|all] [--start] [--end]

Computes relative strength, upserts it into the derived DB, and prints a
summary. Same loop-and-print shape as breadth/cli.py.

The stock tiers rank every ticker against ONE universe, all of
`config.indices` together (S&P 500 + Nasdaq-100): the stored table is keyed
by (ticker, date, comparison), so separate per-index runs overwrote each
other and a stock in both indices kept whichever run wrote last (about 97
Nasdaq-100 names were rated against Nasdaq-100 peers only). There is no
per-index option for that reason; per-index ratings are computed live
(`compute_stock_vs_market(conn, "sp500", ...)`), not stored.
sector-vs-market isn't index-scoped (the 11 sector ETFs aren't an
index_membership roster).
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from src.foundation.market_common import derived_db
from src.signals.relative_strength import store
from src.signals.relative_strength.compute import (
    compute_sector_vs_market,
    compute_stock_vs_market,
    compute_stock_vs_sector,
)
from src.signals.relative_strength.config import RelativeStrengthConfig

_TIERS = ("stock-vs-market", "stock-vs-sector", "sector-vs-market")


def universe_name(config: RelativeStrengthConfig) -> str:
    """The stored run's universe, as recorded in `runs.ticker`: e.g. "sp500+nasdaq100"."""
    return "+".join(config.indices)


def run_stock_tier(raw_conn, derived_conn, tier: str, config: RelativeStrengthConfig, start, end):
    """Returns (rs, skip_reason, run_id) -- run_id is None exactly when
    skip_reason isn't (nothing was stored, so no run was recorded). Ranks
    over all of `config.indices` together (module docstring)."""
    compute_fn = compute_stock_vs_market if tier == "stock-vs-market" else compute_stock_vs_sector
    comparison = "vs_market" if tier == "stock-vs-market" else "vs_sector"

    rs = compute_fn(raw_conn, list(config.indices), config, start=start, end=end)
    if rs.empty:
        return rs, "no membership/price/sector data for these indices", None

    run_id = derived_db.record_run(
        derived_conn, "relative_strength", universe_name(config), "daily", None,
        json.dumps(dataclasses.asdict(config)), 0, False,
    )
    store.upsert_relative_strength(derived_conn, comparison, rs, run_id)
    return rs, None, run_id


def run_sector_tier(raw_conn, derived_conn, config: RelativeStrengthConfig, start, end):
    """Returns (rs, skip_reason, run_id), same contract as run_stock_tier."""
    rs = compute_sector_vs_market(raw_conn, config, start=start, end=end)
    if rs.empty:
        return rs, "no sector-ETF/benchmark price data", None

    run_id = derived_db.record_run(
        derived_conn, "relative_strength", "sectors", "daily", None,
        json.dumps(dataclasses.asdict(config)), 0, False,
    )
    store.upsert_sector_relative_strength(derived_conn, rs, run_id)
    return rs, None, run_id


def main():
    parser = argparse.ArgumentParser(description="Compute relative strength for S&P 500 + Nasdaq-100 (one universe)")
    parser.add_argument("--tier", default="all", choices=[*_TIERS, "all"])
    parser.add_argument("--start", default=None, help="YYYY-MM-DD; default: full available history")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD; default: latest available data")
    args = parser.parse_args()

    raw_conn, derived_conn = derived_db.bootstrap_cli(store.create_relative_strength_tables)

    config = RelativeStrengthConfig()
    tiers = _TIERS if args.tier == "all" else [args.tier]

    for tier in tiers:
        if tier == "sector-vs-market":
            rs, skip_reason, _ = run_sector_tier(raw_conn, derived_conn, config, args.start, args.end)
            if skip_reason is not None:
                print(f"sector-vs-market: SKIPPED -- {skip_reason}")
                continue
            latest_date = rs["date"].max()
            latest = rs[rs["date"] == latest_date].sort_values("rs_rating", ascending=False)
            print(f"sector-vs-market: {len(rs)} rows, latest ({latest_date.date()}):")
            for row in latest.itertuples():
                print(f"  {row.sector}: rs_rating={row.rs_rating:.1f} rs_mansfield={row.rs_mansfield:.2f}")
            continue

        universe = universe_name(config)
        rs, skip_reason, _ = run_stock_tier(raw_conn, derived_conn, tier, config, args.start, args.end)
        if skip_reason is not None:
            print(f"{tier}/{universe}: SKIPPED -- {skip_reason}")
            continue
        latest_date = rs["date"].max()
        n_latest = (rs["date"] == latest_date).sum()
        print(f"{tier}/{universe}: {len(rs)} rows, latest ({latest_date.date()}) n_tickers={n_latest}")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

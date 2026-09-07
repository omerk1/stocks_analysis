"""python -m src.signals.moving_averages.cli [--tickers TICKER ...]

Phase 0 data-hygiene audit (DESIGN.md §3.4) against the real ingested DB --
not a pytest test. Delisted coverage and the golden-fixture MA check have a
single unambiguous right answer and live as real assertions in
`tests/test_moving_averages_hygiene.py`; flat-run/large-move flags and the
spot-check sample are for human review (a real large move can be genuine --
an earnings gap or crash -- not a bug), so this command is their rerunnable,
human-facing report rather than a pass/fail.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.foundation.data_processing import db
from src.foundation.market_common.data import load_bars, validate_bars
from src.foundation.market_common.models import Timeframe
from src.foundation.utils.config_loader import load_config
from src.signals.moving_averages.data import (
    delisted_coverage_by_year,
    flag_forward_filled_halts,
    flag_large_moves,
    spot_check_sample,
)

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"

# A deliberately mixed sample: a couple of clean blue chips, and names this
# repo's own docs already flagged as having real data-quality wrinkles
# (docs/limitations.md, docs/done.md) -- T's 2023-01-24 intraday spike,
# AMC's 2021 squeeze and 2023 reverse split, GEVO's low-liquidity history --
# so the report exercises the flags against known-interesting cases, not
# just quiet ones.
DEFAULT_TICKERS = ["AAPL", "MSFT", "T", "AMC", "GEVO"]


def main():
    parser = argparse.ArgumentParser(description="Phase 0 hygiene report for the moving-averages study")
    parser.add_argument(
        "--tickers", nargs="*", default=DEFAULT_TICKERS,
        help=f"Tickers to run the per-ticker flat-run/large-move scan against (default: {DEFAULT_TICKERS})",
    )
    args = parser.parse_args()

    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    conn = db.get_connection(db_path)

    print("=== Delisted coverage by year (tickers.active=0 with >=1 bars_1d row) ===")
    coverage = delisted_coverage_by_year(conn)
    if coverage.empty:
        print("ZERO delisted tickers have any price history in this DB.")
        print("Per DESIGN.md §3.4: 'if you have zero delistings, your data vendor is lying to you.'")
        print("Here the vendor isn't lying -- delisted names were simply never ingested.")
        print("See CLAUDE.md invariant #4 and docs/limitations.md.")
    else:
        print(coverage.to_string(index=False))

    print("\n=== Per-ticker flat-run / large-move scan ===")
    for ticker in args.tickers:
        bars = load_bars(conn, ticker, Timeframe.DAILY)
        if bars.empty:
            print(f"{ticker}: no data")
            continue
        clean, _ = validate_bars(bars, ticker)
        halts = flag_forward_filled_halts(clean)
        moves = flag_large_moves(clean)
        print(f"{ticker}: {len(clean)} bars, {len(halts)} flat-run-flagged rows, {len(moves)} large-move-flagged rows")
        if not moves.empty:
            for date, ret in moves["ret"].items():
                print(f"    {date.date()}  ret={ret:+.1%}")

    print("\n=== Spot-check sample (20 random ticker/date pairs, seed=42) ===")
    sample = spot_check_sample(conn, n=20, seed=42)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "spot_check_sample.csv"
    sample.to_csv(out_path, index=False)
    print(sample.to_string(index=False))
    print(f"\nWritten to {out_path} -- manually verify each row against a chart provider (DESIGN.md §3.4).")

    conn.close()


if __name__ == "__main__":
    main()

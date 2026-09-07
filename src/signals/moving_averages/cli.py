"""python -m src.signals.moving_averages.cli <command>

Commands:
  hygiene-report   Phase 0 data-hygiene audit (DESIGN.md §3.4) against the real DB.
  validate-synth   Phase 1 synthetic pipeline-validation gate (DESIGN.md §10.2).

`build-panel` (Phase 2's feature panel) isn't implemented yet.

Both commands mirror a pytest suite (`tests/test_moving_averages_hygiene.py`,
`tests/test_moving_averages_synthetic_validation.py`) for the checks that
have a single unambiguous right answer; they exist here too because
`hygiene-report`'s flat-run/large-move flags and spot-check sample are for
human review (a real large move can be genuine -- an earnings gap or crash
-- not a bug), which a pass/fail pytest assertion can't express.
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
from src.signals.moving_averages.synthetic import gate_verdict, run_validation

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"

# A deliberately mixed sample: a couple of clean blue chips, and names this
# repo's own docs already flagged as having real data-quality wrinkles
# (docs/limitations.md, docs/done.md) -- T's 2023-01-24 intraday spike,
# AMC's 2021 squeeze and 2023 reverse split, GEVO's low-liquidity history --
# so the report exercises the flags against known-interesting cases, not
# just quiet ones.
DEFAULT_TICKERS = ["AAPL", "MSFT", "T", "AMC", "GEVO"]


def hygiene_report(tickers: list[str]) -> None:
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
    for ticker in tickers:
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


def validate_synth() -> bool:
    results = run_validation()
    verdict = gate_verdict(results)

    print("=== Phase 1 synthetic pipeline validation (DESIGN.md §10.2) ===")
    print(f"Planted magnitude:   {results['planted_magnitude']:+.4f}")
    print(f"Recovered (planted): {results['recovered_planted']:+.4f}  "
          f"[{'PASS' if verdict['planted_recovered'] else 'FAIL'}]")
    print(f"Recovered (null):    {results['recovered_null']:+.4f}  "
          f"[{'PASS' if verdict['null_reports_nothing'] else 'FAIL'}]")
    print(f"Recovered (shifted): {results['recovered_shifted']:+.4f}  "
          f"[{'PASS' if verdict['shift_degrades'] else 'FAIL'}]  "
          "(look-ahead shift test -- should be well below the planted recovery)")

    all_pass = all(verdict.values())
    print(f"\nGATE: {'PASS' if all_pass else 'FAIL'}")
    if not all_pass:
        print("Per CLAUDE.md: 'If this is failing or absent, no result from this repo means anything. Fix it first.'")
    return all_pass


def main():
    parser = argparse.ArgumentParser(description="Moving-averages study utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    hygiene_parser = subparsers.add_parser("hygiene-report", help="Phase 0 data-hygiene audit")
    hygiene_parser.add_argument(
        "--tickers", nargs="*", default=DEFAULT_TICKERS,
        help=f"Tickers to run the per-ticker flat-run/large-move scan against (default: {DEFAULT_TICKERS})",
    )

    subparsers.add_parser("validate-synth", help="Phase 1 synthetic pipeline-validation gate")

    args = parser.parse_args()

    if args.command == "hygiene-report":
        hygiene_report(args.tickers)
    elif args.command == "validate-synth":
        passed = validate_synth()
        raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()

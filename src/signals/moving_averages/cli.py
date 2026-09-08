"""python -m src.signals.moving_averages.cli <command>

Commands:
  hygiene-report   Phase 0 data-hygiene audit (DESIGN.md §3.4) against the real DB.
  validate-synth   Phase 1 synthetic pipeline-validation gate (DESIGN.md §10.2).
  build-panel      Phase 2 starting-subset feature panel build + cache (DESIGN.md §4).

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
    sp500_full_coverage_tickers,
    spot_check_sample,
)
from src.signals.moving_averages.features.panel import build_panel, read_panel, write_panel
from src.signals.moving_averages.synthetic import gate_verdict, run_validation

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"

# The holdout boundary enforced by CLAUDE.md's holdout-lock invariant.
HOLDOUT_BOUNDARY = "2021-12-31"

# A deliberately mixed sample: a couple of clean blue chips, and names this
# repo's own docs already flagged as having real data-quality wrinkles
# (docs/limitations.md, docs/done.md) -- T's 2023-01-24 intraday spike,
# AMC's 2021 squeeze and 2023 reverse split, GEVO's low-liquidity history --
# so the report exercises the flags against known-interesting cases, not
# just quiet ones.
DEFAULT_TICKERS = ["AAPL", "MSFT", "T", "AMC", "GEVO"]

# A slightly broader default for build-panel -- the hygiene sample plus a
# few more liquid megacaps, enough to demonstrate the panel's multi-ticker/
# multi-date partitioned caching without being slow to build on demand.
DEFAULT_PANEL_TICKERS = DEFAULT_TICKERS + ["GOOGL", "AMZN", "NVDA", "META", "JPM"]

# The exact universe-selection parameters M4's first pass (PREREGISTRATION.md,
# 2026-09-08) ran against: S&P 500 membership as of the holdout boundary,
# restricted to tickers with bars_1d coverage spanning essentially the whole
# 2010-2021 dev window. `--universe sp500` reproduces that 408-ticker set.
SP500_UNIVERSE_AS_OF = HOLDOUT_BOUNDARY
SP500_UNIVERSE_COVERAGE_START = "2010-06-01"
SP500_UNIVERSE_COVERAGE_END = "2021-12-01"


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
        print("See CLAUDE.md's no-dropping-delisted-tickers invariant and docs/limitations.md.")
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


def build_panel_command(tickers: list[str] | None, universe: str, start: str | None, end: str | None) -> None:
    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    conn = db.get_connection(db_path)

    if universe == "sp500":
        tickers = sp500_full_coverage_tickers(
            conn, SP500_UNIVERSE_AS_OF, SP500_UNIVERSE_COVERAGE_START, SP500_UNIVERSE_COVERAGE_END
        )
        print(f"--universe sp500: resolved {len(tickers)} tickers "
              f"(S&P 500 as of {SP500_UNIVERSE_AS_OF}, coverage {SP500_UNIVERSE_COVERAGE_START} to "
              f"{SP500_UNIVERSE_COVERAGE_END})")
    elif tickers is None:
        tickers = DEFAULT_PANEL_TICKERS

    if end is None:
        print("WARNING: --end not given and --open-holdout not passed -- "
              f"loading unrestricted history, past the {HOLDOUT_BOUNDARY} holdout boundary.")
    panel = build_panel(conn, tickers, start=start, end=end)
    conn.close()

    if panel.empty:
        print(f"No data for any of {tickers}.")
        return

    output_dir = Path(config.data_paths.features) / "moving_averages" / "ma_panel"
    write_panel(panel, output_dir)

    print(f"Built panel: {len(panel)} rows, {panel['ticker'].nunique()} tickers, "
          f"{panel['date'].nunique()} distinct dates, "
          f"{panel['date'].min().date()} to {panel['date'].max().date()}")
    print(f"{len(panel.columns)} columns: {list(panel.columns)}")
    print(f"Cached to {output_dir}")

    read_back = read_panel(output_dir)
    print(f"Read back: {len(read_back)} rows (matches: {len(read_back) == len(panel)})")

    print("\nLast 3 rows for the first ticker:")
    first_ticker = panel["ticker"].iloc[0]
    cols = ["date", "close", "sma_20", "above_sma_20", "dist_pct_sma_20", "slope_log_21_sma_20", "stacked_sma"]
    print(panel[panel["ticker"] == first_ticker][cols].tail(3).to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="Moving-averages study utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    hygiene_parser = subparsers.add_parser("hygiene-report", help="Phase 0 data-hygiene audit")
    hygiene_parser.add_argument(
        "--tickers", nargs="*", default=DEFAULT_TICKERS,
        help=f"Tickers to run the per-ticker flat-run/large-move scan against (default: {DEFAULT_TICKERS})",
    )

    subparsers.add_parser("validate-synth", help="Phase 1 synthetic pipeline-validation gate")

    panel_parser = subparsers.add_parser("build-panel", help="Phase 2 feature panel build + cache")
    panel_parser.add_argument(
        "--tickers", nargs="*", default=None,
        help=f"Tickers to build the panel for (default: {DEFAULT_PANEL_TICKERS}, ignored if --universe is given)",
    )
    panel_parser.add_argument(
        "--universe", choices=["sp500"], default=None,
        help="Use a named universe instead of --tickers. 'sp500' reproduces the exact "
             "408-ticker set M4's first pass ran against (S&P 500 as of the holdout "
             "boundary, filtered to full dev-window bars_1d coverage).",
    )
    panel_parser.add_argument("--start", default=None, help="YYYY-MM-DD; default: full available history")
    panel_parser.add_argument(
        "--end", default=HOLDOUT_BOUNDARY,
        help=f"YYYY-MM-DD, holdout-safe by default (CLAUDE.md's holdout-lock invariant: {HOLDOUT_BOUNDARY})",
    )
    panel_parser.add_argument(
        "--open-holdout", action="store_true",
        help="Explicitly bypass the holdout boundary and load unrestricted history (ignores --end)",
    )

    args = parser.parse_args()

    if args.command == "hygiene-report":
        hygiene_report(args.tickers)
    elif args.command == "validate-synth":
        passed = validate_synth()
        raise SystemExit(0 if passed else 1)
    elif args.command == "build-panel":
        end = None if args.open_holdout else args.end
        build_panel_command(args.tickers, args.universe, args.start, end)


if __name__ == "__main__":
    main()

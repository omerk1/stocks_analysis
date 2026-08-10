"""python -m src.gaps.cli TICKER --timeframe daily|weekly|both [--as-of YYYY-MM-DD] [--plot out.html]

Detects gaps/FVGs, upserts them into the derived DB, and prints a summary
table. `--all` iterates every distinct ticker in `bars_1d` instead of one
named TICKER -- continue-on-error per ticker, with a pass/fail/warning tally
at the end. No fetch_jobs-based resumability (see sr_lines/cli.py for that
heavier pattern, used for the very different problem of a multi-hour bulk
ingest job) -- a gap detection pass over one ticker is fast enough that a
plain loop is the right amount of machinery.
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from dotenv import load_dotenv

from src.data_processing import db
from src.gaps import store
from src.gaps.config import GapConfig
from src.gaps.detect import detect
from src.gaps.models import Gap, Timeframe
from src.gaps.plotting import render_gap_chart
from src.market_common import data as data_mod
from src.market_common import derived_db
from src.utils.config_loader import load_config


def _timeframes_for(arg: str) -> list[Timeframe]:
    if arg == "both":
        return [Timeframe.DAILY, Timeframe.WEEKLY]
    return [Timeframe(arg)]


def _status_counts(gaps: list[Gap]) -> str:
    counts: dict[str, int] = {}
    for gap in gaps:
        counts[gap.status.value] = counts.get(gap.status.value, 0) + 1
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"


def run_for_ticker(
    raw_conn, derived_conn, ticker: str, timeframe: Timeframe, config: GapConfig, as_of: str | None,
    plot_path: str | None = None,
) -> tuple[list[Gap], str | None]:
    """Returns (gaps, skip_reason). Always records a `runs` row when
    detection actually ran (even if it found zero gaps) -- a run that
    legitimately found nothing is still a completed run, distinct from one
    skipped outright for too little data."""
    gaps, report, skip_reason = detect(raw_conn, ticker, timeframe, config, as_of=as_of)
    if skip_reason is not None:
        return [], skip_reason

    run_id = derived_db.record_run(
        derived_conn, "gaps", ticker, timeframe.value, as_of,
        json.dumps(dataclasses.asdict(config)), report.rows_dropped, report.unreliable,
    )
    for gap in gaps:
        gap.run_id = run_id
    store.upsert_gaps(derived_conn, gaps, run_id)

    if plot_path:
        bars, _ = data_mod.load_and_validate(raw_conn, ticker, timeframe, as_of=as_of)
        fig = render_gap_chart(bars, gaps, ticker=ticker, timeframe=timeframe)
        fig.write_html(plot_path)

    return gaps, None


def main():
    parser = argparse.ArgumentParser(description="Detect classic gaps and fair-value gaps (FVGs)")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("ticker", nargs="?", help="Ticker to run detection for")
    target.add_argument("--all", action="store_true", help="Run for every distinct ticker in bars_1d")
    parser.add_argument(
        "--timeframe", default="both", choices=["daily", "weekly", "both"],
        help="Bar resolution (default: both)",
    )
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD; default: latest available data")
    parser.add_argument(
        "--plot", default=None, metavar="PATH",
        help="Write a Plotly HTML chart here. Only valid for a single ticker + single timeframe.",
    )
    args = parser.parse_args()

    if args.plot and (args.all or args.timeframe == "both"):
        parser.error("--plot requires a single TICKER and a single --timeframe (not --all/'both')")

    load_dotenv()
    config = load_config()
    raw_conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(raw_conn)

    derived_db_path = derived_db.default_derived_db_path(config.data_paths.derived)
    derived_db_path.parent.mkdir(parents=True, exist_ok=True)
    derived_conn = derived_db.get_connection(derived_db_path)
    derived_db.create_runs_table(derived_conn)
    store.create_gaps_table(derived_conn)

    gap_config = GapConfig()
    timeframes = _timeframes_for(args.timeframe)

    if args.all:
        tickers = [
            row[0] for row in raw_conn.execute("SELECT DISTINCT ticker FROM bars_1d").fetchall()
        ]
    else:
        tickers = [args.ticker]

    n_success, n_failed, n_warnings = 0, 0, 0
    for ticker in tickers:
        for timeframe in timeframes:
            try:
                gaps, skip_reason = run_for_ticker(
                    raw_conn, derived_conn, ticker, timeframe, gap_config, args.as_of,
                    plot_path=args.plot,
                )
            except Exception as exc:  # continue-on-error per ticker, as specced
                n_failed += 1
                print(f"{ticker} [{timeframe.value}]: FAILED -- {exc}")
                continue

            if skip_reason is not None:
                n_warnings += 1
                print(f"{ticker} [{timeframe.value}]: SKIPPED -- {skip_reason}")
                continue

            n_success += 1
            print(f"{ticker} [{timeframe.value}]: {len(gaps)} gaps ({_status_counts(gaps)})")

    if args.plot and n_success:
        print(f"Wrote {args.plot}")

    if args.all or len(tickers) > 1 or len(timeframes) > 1:
        print(f"\nDone: {n_success} succeeded, {n_warnings} skipped, {n_failed} failed")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

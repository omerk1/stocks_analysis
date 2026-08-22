"""python -m src.patterns.cli TICKER --timeframe daily|weekly|both [--as-of YYYY-MM-DD] [--plot out.html]

Detects chart patterns (double top/bottom, head & shoulders + inverse,
triangles + wedges, cup & handle + inverse, VCP so far), upserts them into
the derived DB, and prints a summary table. `--all` iterates every distinct
ticker in `bars_1d` instead of one named TICKER -- continue-on-error per
ticker, same shape as gaps.cli/divergences.cli. No `--preset` flag yet:
unlike SRConfig's asset-class presets, `config.PRESETS` today only
distinguishes daily vs. weekly bar-count scaling, so the right preset is
picked automatically per `--timeframe` rather than exposed as a separate
choice -- add a real `--preset` flag if/when a genuine second profile
(e.g. small-cap vs. large-cap thresholds) exists.
"""

from __future__ import annotations

import argparse
import json

from src.data_processing import db
from src.market_common import data as data_mod
from src.market_common import derived_db
from src.patterns import store
from src.patterns.config import get_preset
from src.patterns.models import PatternMatch, Timeframe
from src.patterns.plotting import render_pattern_chart
from src.patterns.scanner import detect


def _timeframes_for(arg: str) -> list[Timeframe]:
    if arg == "both":
        return [Timeframe.DAILY, Timeframe.WEEKLY]
    return [Timeframe(arg)]


def _status_counts(matches: list[PatternMatch]) -> str:
    counts: dict[str, int] = {}
    for m in matches:
        counts[m.status.value] = counts.get(m.status.value, 0) + 1
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"


def run_for_ticker(
    raw_conn, derived_conn, ticker: str, timeframe: Timeframe, as_of: str | None,
    plot_path: str | None = None,
) -> tuple[list[PatternMatch], str | None]:
    """Returns (matches, skip_reason). Always records a `runs` row when
    detection actually ran (even if it found zero matches), same
    reasoning as gaps.cli.run_for_ticker."""
    config = get_preset("daily" if timeframe == Timeframe.DAILY else "weekly")
    matches, report, skip_reason = detect(raw_conn, ticker, timeframe, config, as_of=as_of)
    if skip_reason is not None:
        return [], skip_reason

    run_id = derived_db.record_run(
        derived_conn, "patterns", ticker, timeframe.value, as_of,
        json.dumps(config.to_dict()), report.rows_dropped, report.unreliable,
    )
    for match in matches:
        match.run_id = run_id
    store.upsert_pattern_matches(derived_conn, matches, run_id)

    if plot_path:
        bars, _ = data_mod.load_and_validate(raw_conn, ticker, timeframe, as_of=as_of)
        fig = render_pattern_chart(bars, matches, ticker=ticker, timeframe=timeframe)
        fig.write_html(plot_path)

    return matches, None


def main():
    parser = argparse.ArgumentParser(description="Detect chart patterns (double top/bottom, head & shoulders, triangles/wedges, cup & handle, VCP, ...)")
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

    raw_conn, derived_conn = derived_db.bootstrap_cli(store.create_pattern_matches_table)

    timeframes = _timeframes_for(args.timeframe)
    if args.all:
        tickers = [
            row[0] for row in raw_conn.execute(
                "SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", (db.YFINANCE,)
            ).fetchall()
        ]
    else:
        tickers = [args.ticker]

    n_success, n_failed, n_warnings = 0, 0, 0
    for ticker in tickers:
        for timeframe in timeframes:
            try:
                matches, skip_reason = run_for_ticker(
                    raw_conn, derived_conn, ticker, timeframe, args.as_of, plot_path=args.plot,
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
            print(f"{ticker} [{timeframe.value}]: {len(matches)} patterns ({_status_counts(matches)})")

    if args.plot and n_success:
        print(f"Wrote {args.plot}")

    if args.all or len(tickers) > 1 or len(timeframes) > 1:
        print(f"\nDone: {n_success} succeeded, {n_warnings} skipped, {n_failed} failed")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

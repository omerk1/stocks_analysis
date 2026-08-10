"""python -m src.avwap.cli TICKER --timeframe daily|weekly|both [--as-of YYYY-MM-DD] [--plot out.html] [--include-stale]

Discovers anchored-VWAP anchors (ath/atl/52w_high/52w_low/cycle_high/
cycle_low), upserts them into the derived DB, and prints a summary.
`--all` iterates every distinct ticker in bars_1d instead of one named
TICKER -- continue-on-error per ticker, with a pass/fail/warning tally at
the end. Same shape as gaps/cli.py; see that module's own docstring for why
a plain loop (not fetch_jobs-based resumability) is the right amount of
machinery here too.
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from dotenv import load_dotenv

from src.avwap import store
from src.avwap.anchors import detect
from src.avwap.config import AvwapConfig
from src.avwap.models import AnchoredVwap, AnchorStatus, Timeframe
from src.avwap.plotting import render_avwap_chart
from src.data_processing import db
from src.market_common import data as data_mod
from src.market_common import derived_db
from src.utils.config_loader import load_config


def _timeframes_for(arg: str) -> list[Timeframe]:
    if arg == "both":
        return [Timeframe.DAILY, Timeframe.WEEKLY]
    return [Timeframe(arg)]


def _summary(anchors: list[AnchoredVwap]) -> str:
    active = sum(1 for a in anchors if a.status == AnchorStatus.ACTIVE)
    stale = sum(1 for a in anchors if a.status == AnchorStatus.STALE)
    return f"active={active}, stale={stale}"


def run_for_ticker(
    raw_conn, derived_conn, ticker: str, timeframe: Timeframe, config: AvwapConfig, as_of: str | None,
    plot_path: str | None = None, include_stale: bool = False,
) -> tuple[list[AnchoredVwap], str | None]:
    """Returns (anchors, skip_reason). Always records a `runs` row when
    detection actually ran (even if it found zero anchors, which shouldn't
    normally happen once min_bars is met) -- a run that legitimately found
    nothing is still a completed run, distinct from one skipped outright
    for too little data."""
    previous = store.get_anchor_types(derived_conn, ticker, timeframe.value)
    anchors, report, skip_reason = detect(
        raw_conn, ticker, timeframe, config, as_of=as_of, previous_anchor_types=previous,
    )
    if skip_reason is not None:
        return [], skip_reason

    run_id = derived_db.record_run(
        derived_conn, "avwap", ticker, timeframe.value, as_of,
        json.dumps(dataclasses.asdict(config)), report.rows_dropped, report.unreliable,
    )
    for anchor in anchors:
        anchor.run_id = run_id
    store.upsert_anchors(derived_conn, anchors, run_id)

    if plot_path:
        bars, _ = data_mod.load_and_validate(raw_conn, ticker, timeframe, as_of=as_of)
        fig = render_avwap_chart(
            bars, anchors, ticker=ticker, timeframe=timeframe, config=config, include_stale=include_stale,
        )
        fig.write_html(plot_path)

    return anchors, None


def main():
    parser = argparse.ArgumentParser(description="Discover anchored-VWAP anchors (ath/atl/52w/cycle)")
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
    parser.add_argument(
        "--include-stale", action="store_true",
        help="Also draw stale anchors on the plot (dashed lines)",
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
    store.create_avwap_table(derived_conn)

    avwap_config = AvwapConfig()
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
                anchors, skip_reason = run_for_ticker(
                    raw_conn, derived_conn, ticker, timeframe, avwap_config, args.as_of,
                    plot_path=args.plot, include_stale=args.include_stale,
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
            print(f"{ticker} [{timeframe.value}]: {len(anchors)} anchors ({_summary(anchors)})")

    if args.plot and n_success:
        print(f"Wrote {args.plot}")

    if args.all or len(tickers) > 1 or len(timeframes) > 1:
        print(f"\nDone: {n_success} succeeded, {n_warnings} skipped, {n_failed} failed")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

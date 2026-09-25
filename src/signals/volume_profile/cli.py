"""python -m src.signals.volume_profile.cli TICKER --timeframe daily|weekly|both [--as-of YYYY-MM-DD] [--plot out.html] [--plot-anchor YYYY-MM-DD]

Builds an anchored volume profile (POC / value area) for every anchor the
shared market_common.anchors discovery finds -- the same dates avwap
anchors on -- upserts the snapshots into the derived DB, and prints a
summary. `--all` iterates every distinct ticker in bars_1d, continue-on-
error per ticker, with a pass/fail/warning tally at the end. Same shape as
avwap/cli.py.
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from src.foundation.data_processing import db
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.anchors import AnchorStatus
from src.foundation.market_common.models import Timeframe
from src.signals.volume_profile import store
from src.signals.volume_profile.config import VolumeProfileConfig
from src.signals.volume_profile.detect import detect
from src.signals.volume_profile.models import AnchoredVolumeProfile
from src.signals.volume_profile.plotting import render_volume_profile_chart


def _timeframes_for(arg: str) -> list[Timeframe]:
    if arg == "both":
        return [Timeframe.DAILY, Timeframe.WEEKLY]
    return [Timeframe(arg)]


def _summary(profiles: list[AnchoredVolumeProfile]) -> str:
    active = sum(1 for p in profiles if p.status == AnchorStatus.ACTIVE)
    stale = sum(1 for p in profiles if p.status == AnchorStatus.STALE)
    inside = sum(1 for p in profiles if p.status == AnchorStatus.ACTIVE and p.value_area_position == "inside")
    return f"active={active} ({inside} with close inside value area), stale={stale}"


def run_for_ticker(
    raw_conn, derived_conn, ticker: str, timeframe: Timeframe, config: VolumeProfileConfig, as_of: str | None,
    plot_path: str | None = None, plot_anchor: str | None = None,
) -> tuple[list[AnchoredVolumeProfile], str | None]:
    """Returns (profiles, skip_reason). Records a `runs` row whenever
    detection actually ran (mirrors avwap.cli.run_for_ticker)."""
    previous = store.get_anchor_types(derived_conn, ticker, timeframe.value)
    profiles, report, skip_reason = detect(
        raw_conn, ticker, timeframe, config, as_of=as_of, previous_anchor_types=previous,
    )
    if skip_reason is not None:
        return [], skip_reason

    run_id = derived_db.record_run(
        derived_conn, "volume_profile", ticker, timeframe.value, as_of,
        json.dumps(dataclasses.asdict(config)), report.rows_dropped, report.unreliable,
    )
    for profile in profiles:
        profile.run_id = run_id
    store.upsert_profiles(derived_conn, profiles, run_id)

    if plot_path:
        bars, _ = data_mod.load_and_validate(raw_conn, ticker, timeframe, as_of=as_of)
        fig = render_volume_profile_chart(
            bars, profiles, ticker=ticker, timeframe=timeframe, config=config, anchor_date=plot_anchor,
        )
        fig.write_html(plot_path)

    return profiles, None


def main():
    parser = argparse.ArgumentParser(description="Anchored volume profiles (POC / value area) per AVWAP-style anchor")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("ticker", nargs="?", help="Ticker to run for")
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
        "--plot-anchor", default=None, metavar="YYYY-MM-DD",
        help="Which anchor's profile to draw (default: most senior active anchor)",
    )
    args = parser.parse_args()

    if args.plot and (args.all or args.timeframe == "both"):
        parser.error("--plot requires a single TICKER and a single --timeframe (not --all/'both')")

    raw_conn, derived_conn = derived_db.bootstrap_cli(store.create_volume_profile_table)

    config = VolumeProfileConfig()
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
                profiles, skip_reason = run_for_ticker(
                    raw_conn, derived_conn, ticker, timeframe, config, args.as_of,
                    plot_path=args.plot, plot_anchor=args.plot_anchor,
                )
            except Exception as exc:  # continue-on-error per ticker, as in avwap/cli.py
                n_failed += 1
                print(f"{ticker} [{timeframe.value}]: FAILED -- {exc}")
                continue

            if skip_reason is not None:
                n_warnings += 1
                print(f"{ticker} [{timeframe.value}]: SKIPPED -- {skip_reason}")
                continue

            n_success += 1
            print(f"{ticker} [{timeframe.value}]: {len(profiles)} profiles ({_summary(profiles)})")

    if args.plot and n_success:
        print(f"Wrote {args.plot}")

    if args.all or len(tickers) > 1 or len(timeframes) > 1:
        print(f"\nDone: {n_success} succeeded, {n_warnings} skipped, {n_failed} failed")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

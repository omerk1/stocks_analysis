"""CLI entry point: `python -m src.divergences.cli TICKER [options]` --
mirrors sr_lines.cli's structure (argparse, --as-of, --out/plot HTML). No
existing module CLI has --all yet; this is the first, kept simple: loop
tickers x timeframes, continue-on-error, tally successes/skips/failures.
"""

from __future__ import annotations

import argparse
import json
import logging

from dotenv import load_dotenv

from src.data_processing import db
from src.divergences.config import DivergenceConfig
from src.divergences.detect import compute_indicator_series, detect
from src.divergences.plotting import render_divergence_chart
from src.divergences.store import create_divergences_table, upsert_divergences
from src.market_common import data as data_mod
from src.market_common import derived_db
from src.market_common.models import Timeframe
from src.utils.config_loader import load_config

logger = logging.getLogger(__name__)


def _run_one(conn, derived_conn, ticker, timeframe, as_of, config, plot_path, plot_indicator):
    """Returns (n_divergences, unreliable) on success, or (None, None) if
    this (ticker, timeframe) was skipped for too little data."""
    divergences, report, skip_reason = detect(conn, ticker, timeframe, config, as_of=as_of)
    if skip_reason is not None:
        print(f"{ticker}/{timeframe.value}: skipped -- {skip_reason}")
        return None, None

    run_id = derived_db.record_run(
        derived_conn, "divergences", ticker, timeframe.value,
        str(as_of) if as_of else None, json.dumps(config.__dict__, default=str),
        report.rows_dropped, report.unreliable,
    )
    for divergence in divergences:
        divergence.run_id = run_id
    upsert_divergences(derived_conn, divergences, run_id)

    warn_note = ", UNRELIABLE" if report.unreliable else ""
    print(
        f"{ticker}/{timeframe.value}: {len(divergences)} divergence(s) "
        f"({report.rows_loaded} bars, {report.rows_dropped} dropped{warn_note})"
    )

    if plot_path is not None:
        bars, _ = data_mod.load_and_validate(conn, ticker, timeframe, as_of=as_of)
        series = compute_indicator_series(bars, plot_indicator, config)
        fig = render_divergence_chart(bars, series, divergences, plot_indicator, ticker=ticker)
        fig.write_html(plot_path)
        print(f"Wrote {plot_path}")

    return len(divergences), report.unreliable


def main():
    parser = argparse.ArgumentParser(description="Detect RSI/MACD-hist/OBV price divergences")
    parser.add_argument("ticker", nargs="?", help="Ticker symbol (omit when using --all)")
    parser.add_argument("--all", action="store_true", help="Run for every distinct ticker in bars_1d")
    parser.add_argument("--timeframe", default="both", choices=["daily", "weekly", "both"])
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD; default: latest available data")
    parser.add_argument("--plot", default=None, help="Output HTML path for a two-pane review chart")
    parser.add_argument(
        "--indicator", default="rsi", choices=["rsi", "macd_hist", "obv"],
        help="Which indicator's divergences to draw (--plot only; default rsi)",
    )
    args = parser.parse_args()

    if not args.all and not args.ticker:
        parser.error("TICKER is required unless --all is given")
    if args.all and args.plot:
        parser.error("--plot is not supported together with --all")

    load_dotenv()
    app_config = load_config()
    conn = db.get_connection(db.default_db_path(app_config.data_paths.raw))
    db.create_tables(conn)

    derived_path = derived_db.default_derived_db_path(app_config.data_paths.derived)
    derived_path.parent.mkdir(parents=True, exist_ok=True)
    derived_conn = derived_db.get_connection(derived_path)
    derived_db.create_runs_table(derived_conn)
    create_divergences_table(derived_conn)

    config = DivergenceConfig()
    timeframes = (
        [Timeframe.DAILY, Timeframe.WEEKLY] if args.timeframe == "both" else [Timeframe(args.timeframe)]
    )

    if args.all:
        tickers = [row[0] for row in conn.execute("SELECT DISTINCT ticker FROM bars_1d").fetchall()]
        total, skipped, failed, unreliable = 0, 0, 0, 0
        for ticker in tickers:
            for tf in timeframes:
                try:
                    n, warn = _run_one(conn, derived_conn, ticker, tf, args.as_of, config, None, args.indicator)
                except Exception:
                    logger.exception("%s/%s: divergence detection failed", ticker, tf.value)
                    print(f"{ticker}/{tf.value}: FAILED (see log)")
                    failed += 1
                    continue
                if n is None:
                    skipped += 1
                else:
                    total += n
                    if warn:
                        unreliable += 1
        print(
            f"\nDone: {len(tickers)} ticker(s) x {len(timeframes)} timeframe(s) -- "
            f"{total} divergence(s) total, {skipped} skipped, {failed} failed, {unreliable} unreliable runs."
        )
    else:
        plotted = False
        for tf in timeframes:
            want_plot = args.plot is not None and not plotted
            n, _warn = _run_one(
                conn, derived_conn, args.ticker, tf, args.as_of, config,
                args.plot if want_plot else None, args.indicator,
            )
            if want_plot and n is not None:
                plotted = True
        if args.plot and not plotted:
            print(f"Note: {args.ticker} had no non-skipped timeframe to plot.")

    conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

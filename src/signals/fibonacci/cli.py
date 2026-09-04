"""CLI: detect multi-scale fib retracement/extension sets for a ticker,
upsert them into the derived DB, and optionally render an HTML overlay
chart. Mirrors sr_lines.cli's argparse/DB-wiring precedent, adds `--all`
(iterate every distinct ticker in bars_1d, continue-on-error) since no
existing CLI here has one yet.
"""

from __future__ import annotations

import argparse
import json

from src.foundation.data_processing import db as raw_db
from src.signals.fibonacci import store as store_mod
from src.signals.fibonacci.config import FibConfig
from src.signals.fibonacci.engine import detect
from src.signals.fibonacci.plotting import render_fib_chart
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe


def _all_tickers(conn) -> list[str]:
    rows = conn.execute("SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", (raw_db.YFINANCE,))
    return sorted(r[0] for r in rows.fetchall())


def _run_one(raw_conn, derived_conn, ticker, timeframe, config, as_of, plot_path, set_id) -> bool:
    result = detect(raw_conn, ticker, timeframe, config, as_of=as_of)

    if result.skip_reason is not None:
        print(f"{ticker}/{result.timeframe}: {result.skip_reason} -- skipped")
        return False

    run_id = derived_db.record_run(
        derived_conn, "fibonacci", ticker, result.timeframe, result.as_of,
        json.dumps(config.to_dict()), result.quality.rows_dropped, result.quality.unreliable,
    )
    # upsert_fib_sets returns each set's *persisted* id -- on a re-run of a
    # swing detected before, that's the original id (preserved across the
    # ON CONFLICT DO UPDATE), not fib_set.id's freshly-minted-this-run
    # value. Printing the persisted id is what makes a later `--set-id`
    # copy-pasted from this output actually resolve.
    persisted_ids = store_mod.upsert_fib_sets(derived_conn, result.selected_sets, run_id)

    print(
        f"{ticker}/{result.timeframe}: {len(result.all_sets)} swing(s) detected, "
        f"{len(result.selected_sets)} stored (top {config.max_sets} by weight)."
    )
    for fib_set in result.selected_sets:
        print(
            f"  [{persisted_ids[fib_set.id][:8]}] {fib_set.swing.direction.value} x{fib_set.swing.scale_mult:g} "
            f"{fib_set.swing.origin_date} -> {fib_set.swing.end_date} "
            f"weight={fib_set.weight:.3f} status={fib_set.status.value}"
        )

    if plot_path:
        sets_to_plot = result.selected_sets
        if set_id:
            # Match against this run's *persisted* ids first (cheap, no
            # extra query) -- falls back to a direct DB lookup for a
            # set_id from an earlier run that this run's fresh detection
            # didn't reproduce (e.g. it fell out of this run's top-K).
            sets_to_plot = [s for s in result.selected_sets if persisted_ids[s.id] == set_id]
            if not sets_to_plot:
                stored = store_mod.load_fib_set(derived_conn, set_id)
                sets_to_plot = [stored] if stored is not None else []
            if not sets_to_plot:
                print(f"  --set-id {set_id} not found among this run's selected sets or the stored DB -- no plot written")
                return True

        bars, _ = data_mod.load_and_validate(raw_conn, ticker, timeframe, as_of=as_of)
        fig = render_fib_chart(bars, sets_to_plot)
        fig.write_html(plot_path)
        print(f"  wrote {plot_path}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Multi-scale Fibonacci retracement/extension detection")
    parser.add_argument("ticker", nargs="?", help="Ticker symbol (omit when using --all)")
    parser.add_argument("--all", action="store_true", help="Run for every distinct ticker in bars_1d")
    parser.add_argument("--timeframe", default="both", choices=["daily", "weekly", "both"])
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD; default: latest available data")
    parser.add_argument("--plot", default=None, help="Output HTML path for an overlay chart")
    parser.add_argument(
        "--set-id", default=None,
        help="Render only this stored fib_set id instead of the run's full top-K (requires --plot)",
    )
    args = parser.parse_args()

    if not args.all and not args.ticker:
        parser.error("TICKER is required unless --all is given")

    raw_conn, derived_conn = derived_db.bootstrap_cli(store_mod.create_tables)

    config = FibConfig()
    timeframes = (
        [Timeframe.DAILY, Timeframe.WEEKLY] if args.timeframe == "both" else [Timeframe(args.timeframe)]
    )
    tickers = _all_tickers(raw_conn) if args.all else [args.ticker]
    # A single --plot path can't sensibly hold charts for many tickers --
    # only honor it in single-ticker mode.
    plot_path = args.plot if not args.all else None

    n_ok = n_skipped = n_err = 0
    for ticker in tickers:
        for timeframe in timeframes:
            try:
                if _run_one(raw_conn, derived_conn, ticker, timeframe, config, args.as_of, plot_path, args.set_id):
                    n_ok += 1
                else:
                    n_skipped += 1
            except Exception as exc:
                n_err += 1
                print(f"{ticker}/{timeframe.value}: ERROR - {exc}")

    if args.all:
        print(f"\nDone: {n_ok} ok, {n_skipped} skipped, {n_err} errors across {len(tickers)} ticker(s).")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

"""CLI entry point: `python -m src.signals.divergences.cli TICKER [options]` --
mirrors sr_lines.cli's structure (argparse, --as-of, --out/plot HTML). No
existing module CLI has --all yet; this is the first, kept simple: loop
tickers x timeframes, continue-on-error, tally successes/skips/failures.
"""

from __future__ import annotations

import argparse
import json
import logging

import pandas as pd

from src.signals.divergences.config import VENDOR_FALLBACK, DivergenceConfig
from src.signals.divergences.detect import compute_indicator_series, detect
from src.signals.divergences.plotting import render_divergence_chart
from src.signals.divergences.store import (
    create_divergences_table,
    purge_ticker,
    recorded_run_sources,
    upsert_divergences,
)
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.price_basis import (
    MODULE_PRICE_BASIS,
    resolve_sources,
    source_for,
    sources_for,
)

logger = logging.getLogger(__name__)

PRIMARY_SOURCE = source_for(MODULE_PRICE_BASIS["divergences"])


def vendor_changed(recorded: dict, ticker: str, resolved_source: str) -> bool:
    """True when the ticker HAS prior detection runs and their bars came
    from a different vendor than today's resolution. A legacy run with no
    recorded `bar_source` read the primary source by construction (no
    fallback existed then). Such a ticker's stored events describe pivots
    on another vendor's prices: it must be re-scanned REPLACE-style (purge
    first), never upserted — pivots shift between vendors and the upsert's
    natural key would leave a mixed-vendor event base."""
    if ticker not in recorded:
        return False
    return (recorded[ticker] or PRIMARY_SOURCE) != resolved_source


def resolve_universe(conn) -> tuple[dict[str, str], int]:
    """The --all universe: every distinct bars_1d ticker on any source this
    module may read, resolved per ticker (primary vendor preferred,
    whole-history-disputed tickers excluded — `price_basis.resolve_sources`).
    Returns (ticker -> source, n_excluded_as_disputed). Before the fallback
    opt-in this was a single primary-source DISTINCT, which silently limited
    detection to tickers yfinance serves — the survivors-only event base in
    the backlog."""
    basis = MODULE_PRICE_BASIS["divergences"]
    # Each source's DISTINCT listing is a full index scan of the 4GB file
    # (minutes) -- do it once and hand the sets to resolve_sources, which
    # would otherwise probe per ticker (right for small lists, minutes for
    # the full universe).
    members = {
        s: {row[0] for row in conn.execute("SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", (s,))}
        for s in sources_for(basis, VENDOR_FALLBACK)
    }
    tickers = sorted(set().union(*members.values()))
    resolved = resolve_sources(conn, tickers, basis, VENDOR_FALLBACK, members=members)
    return resolved, len(tickers) - len(resolved)


def _run_one(conn, derived_conn, ticker, timeframe, as_of, config, plot_path, plot_indicator,
             source=None):
    """Returns (n_divergences, unreliable) on success, or (None, None) if
    this (ticker, timeframe) was skipped for too little data."""
    divergences, report, skip_reason = detect(conn, ticker, timeframe, config, as_of=as_of, source=source)
    if skip_reason is not None:
        print(f"{ticker}/{timeframe.value}: skipped -- {skip_reason}")
        return None, None

    run_id = derived_db.record_run(
        derived_conn, "divergences", ticker, timeframe.value,
        str(as_of) if as_of else None,
        # bar_source makes vendor drift visible: recorded_run_sources reads
        # it back, and a later resolution change triggers a purge+rescan.
        json.dumps({**config.__dict__, "bar_source": source}, default=str),
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
        bars, _ = data_mod.load_and_validate(
            conn, ticker, timeframe, as_of=as_of, basis=config.price_basis, source=source
        )
        series = compute_indicator_series(bars, plot_indicator, config)
        fig = render_divergence_chart(bars, series, divergences, plot_indicator, ticker=ticker)
        fig.write_html(plot_path)
        print(f"Wrote {plot_path}")

    return len(divergences), report.unreliable


def _print_plan(conn, sources: dict[str, str], n_disputed: int, recorded: dict, timeframes) -> None:
    """The --plan dry run: what the resolved universe looks like and what a
    --missing-only backfill would actually touch (never-scanned tickers plus
    vendor-changed ones, which get a purge+rescan), with the delisted/PIT
    breakdown that motivated the fallback. Reads only; writes nothing."""
    from src.signals.divergences.study_universe import DEV_END, DEV_START, membership_intervals

    by_source: dict[str, int] = {}
    for s in sources.values():
        by_source[s] = by_source.get(s, 0) + 1
    print(f"resolved universe: {len(sources)} tickers {by_source}; "
          f"{n_disputed} excluded for whole-history price disputes")

    delisted = {
        r[0] for r in conn.execute("SELECT ticker FROM tickers WHERE active = 0")
    }
    membership = membership_intervals(conn)
    dev_lo, dev_hi = pd.Timestamp(DEV_START), pd.Timestamp(DEV_END)
    for tf in timeframes:
        never = sorted(t for t in sources if t not in recorded[tf])
        changed = sorted(
            t for t in sources if vendor_changed(recorded[tf], t, sources[t])
        )
        todo = never + changed
        todo_member = [
            t for t in todo
            if any(s <= dev_hi and e >= dev_lo for s, e in membership.get(t, ()))
        ]
        todo_member_delisted = [t for t in todo_member if t in delisted]
        print(f"\n{tf.value}: detection already ran on {len(recorded[tf])} tickers; "
              f"--missing-only would run {len(todo)} "
              f"({len(never)} never scanned + {len(changed)} vendor-changed purge+rescans"
              f"{': ' + ', '.join(changed[:6]) if changed else ''})")
        print(f"  of those: {sum(1 for t in todo if t in delisted)} delisted; "
              f"{len(todo_member)} with S&P 500/NDX membership overlapping the dev window "
              f"({DEV_START}..{DEV_END}), {len(todo_member_delisted)} of them delisted")
        if todo_member_delisted:
            sample = ", ".join(todo_member_delisted[:12])
            more = "" if len(todo_member_delisted) <= 12 else f", ... (+{len(todo_member_delisted) - 12})"
            print(f"  delisted dev-window members: {sample}{more}")
    print("\nPLAN ONLY -- nothing was detected or written.")


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
    parser.add_argument(
        "--forms", default="both", choices=["regular", "hidden", "both"],
        help="Which divergence forms to detect and store (default both)",
    )
    parser.add_argument(
        "--missing-only", action="store_true",
        help="With --all: only tickers detection never ran on (per the runs table), plus "
             "tickers whose resolved vendor changed since their last run (purged and "
             "rescanned) -- the additive backfill mode for the vendor fallback",
    )
    parser.add_argument(
        "--plan", action="store_true",
        help="With --all: print the resolved universe and what --missing-only would run, "
             "then exit without detecting or writing anything",
    )
    args = parser.parse_args()

    if not args.all and not args.ticker:
        parser.error("TICKER is required unless --all is given")
    if args.all and args.plot:
        parser.error("--plot is not supported together with --all")
    if (args.plan or args.missing_only) and not args.all:
        parser.error("--plan/--missing-only only make sense with --all")

    conn, derived_conn = derived_db.bootstrap_cli(create_divergences_table)

    config = DivergenceConfig()
    if args.forms != "both":
        config.forms = [args.forms]
    timeframes = (
        [Timeframe.DAILY, Timeframe.WEEKLY] if args.timeframe == "both" else [Timeframe(args.timeframe)]
    )

    if args.all:
        sources, n_disputed = resolve_universe(conn)
        # "Already ran" = the runs table (where detection RAN, not where it
        # found something -- a scanned ticker with zero divergences must not
        # be rescanned either, and controls.py builds its pool from runs).
        # Values carry the recorded bar_source so vendor drift reads as
        # not-done (vendor_changed).
        recorded = {tf: recorded_run_sources(derived_conn, tf.value) for tf in timeframes}
        if args.plan:
            _print_plan(conn, sources, n_disputed, recorded, timeframes)
            conn.close()
            derived_conn.close()
            return
        total, skipped, failed, unreliable, attempted, purged = 0, 0, 0, 0, 0, 0
        for ticker in sorted(sources):
            for tf in timeframes:
                changed = vendor_changed(recorded[tf], ticker, sources[ticker])
                if args.missing_only and ticker in recorded[tf] and not changed:
                    continue
                if changed:
                    n_old = purge_ticker(derived_conn, ticker, tf.value)
                    derived_conn.commit()  # self-healing: a later crash still leaves the stale rows gone
                    purged += 1
                    print(f"{ticker}/{tf.value}: vendor changed "
                          f"({recorded[tf][ticker] or PRIMARY_SOURCE} -> {sources[ticker]}); "
                          f"purged {n_old} stored event(s) before rescan")
                attempted += 1
                try:
                    n, warn = _run_one(conn, derived_conn, ticker, tf, args.as_of, config,
                                       None, args.indicator, source=sources[ticker])
                except Exception:
                    # A failed write leaves its transaction open; without a rollback every
                    # later ticker's write fails too ("database is locked").
                    derived_conn.rollback()
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
            f"\nDone: {attempted} (ticker x timeframe) run(s) over {len(sources)} resolved ticker(s) -- "
            f"{total} divergence(s) total, {skipped} skipped, {failed} failed, {unreliable} unreliable runs; "
            f"{purged} vendor-change purge+rescan(s); "
            f"{n_disputed} ticker(s) excluded for whole-history price disputes."
        )
    else:
        resolved = resolve_sources(conn, [args.ticker], MODULE_PRICE_BASIS["divergences"], VENDOR_FALLBACK)
        if args.ticker not in resolved:
            print(f"{args.ticker}: not runnable -- whole-history price dispute or no bars "
                  "on any source this module reads")
            conn.close()
            derived_conn.close()
            raise SystemExit(1)  # a refusal, distinguishable from a successful run
        plotted = False
        for tf in timeframes:
            recorded_tf = recorded_run_sources(derived_conn, tf.value)
            if vendor_changed(recorded_tf, args.ticker, resolved[args.ticker]):
                n_old = purge_ticker(derived_conn, args.ticker, tf.value)
                derived_conn.commit()
                print(f"{args.ticker}/{tf.value}: vendor changed "
                      f"({recorded_tf[args.ticker] or PRIMARY_SOURCE} -> {resolved[args.ticker]}); "
                      f"purged {n_old} stored event(s) before rescan")
            want_plot = args.plot is not None and not plotted
            n, _warn = _run_one(
                conn, derived_conn, args.ticker, tf, args.as_of, config,
                args.plot if want_plot else None, args.indicator,
                source=resolved[args.ticker],
            )
            if want_plot and n is not None:
                plotted = True
        if args.plot and not plotted:
            print(f"Note: {args.ticker} had no non-skipped timeframe to plot.")

    conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

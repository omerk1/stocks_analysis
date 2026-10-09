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
    PRIMARY_SOURCE,
    create_divergences_table,
    forget_ticker,
    purge_ticker,
    recorded_run_sources,
    stored_tickers,
    upsert_divergences,
    vendor_changed,
)
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.price_basis import (
    MODULE_PRICE_BASIS,
    resolve_sources,
    source_members,
)

logger = logging.getLogger(__name__)

def resolve_universe(conn) -> tuple[dict[str, str], int]:
    """The --all universe: every distinct bars_1d ticker on any source this
    module may read, resolved per ticker (primary vendor preferred,
    whole-history-disputed tickers excluded — `price_basis.resolve_sources`).
    Returns (ticker -> source, n_excluded_as_disputed). Before the fallback
    opt-in this was a single primary-source DISTINCT, which silently limited
    detection to tickers yfinance serves — the survivors-only event base in
    the backlog."""
    basis = MODULE_PRICE_BASIS["divergences"]
    members = source_members(conn, basis, VENDOR_FALLBACK)
    tickers = sorted(set().union(*members.values()))
    resolved = resolve_sources(conn, tickers, basis, VENDOR_FALLBACK, members=members)
    return resolved, len(tickers) - len(resolved)


def _run_one(conn, derived_conn, ticker, timeframe, as_of, config, plot_path, plot_indicator,
             source=None, replace_from=None):
    """Returns (n_divergences, unreliable) on success, or (None, None) if
    this (ticker, timeframe) was skipped for too little data.

    `replace_from` (the recorded old vendor) marks a vendor-changed ticker:
    its stored events and context rows are purged — but only AFTER the new
    vendor's detection succeeded. The purge, the run row and the new events
    are ONE transaction (record_run(commit=False); upsert_divergences
    commits): any failure rolls all three back, so a ticker can never end up
    recorded as scanned on its current vendor without its events (which the
    controls builder would read as "no divergence anywhere"). A skip (too few
    bars on the new vendor) touches nothing: the ticker stays flagged
    vendor-stale instead of losing its events and re-purging every run."""
    divergences, report, skip_reason = detect(conn, ticker, timeframe, config, as_of=as_of, source=source)
    if skip_reason is not None:
        note = (f" (vendor change {replace_from} -> {source} NOT applied: old events kept, "
                "ticker stays vendor-stale)" if replace_from else "")
        print(f"{ticker}/{timeframe.value}: skipped -- {skip_reason}{note}")
        return None, None

    n_old = purge_ticker(derived_conn, ticker, timeframe.value) if replace_from is not None else 0

    run_id = derived_db.record_run(
        derived_conn, "divergences", ticker, timeframe.value,
        str(as_of) if as_of else None,
        # bar_source makes vendor drift visible: recorded_run_sources reads
        # it back, and a later resolution change triggers a rescan that replaces the old events on success.
        json.dumps({**config.__dict__, "bar_source": source}, default=str),
        report.rows_dropped, report.unreliable,
        commit=False,
    )
    for divergence in divergences:
        divergence.run_id = run_id
    upsert_divergences(derived_conn, divergences, run_id)  # commits purge + run row + events together
    if replace_from is not None:
        print(f"{ticker}/{timeframe.value}: vendor changed ({replace_from} -> {source}); "
              f"replaced {n_old} stored event(s)")

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


def _print_plan(conn, sources: dict[str, str], n_disputed: int, recorded: dict, timeframes,
                orphaned: dict) -> None:
    """The --plan dry run: what the resolved universe looks like and what a
    --missing-only backfill would actually touch (never-scanned tickers plus
    vendor-changed ones, which are rescanned and replaced on success), with the delisted/PIT
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
              f"({len(never)} never scanned + {len(changed)} vendor-changed rescans (old events replaced on success)"
              f"{': ' + ', '.join(changed[:6]) if changed else ''})")
        print(f"  of those: {sum(1 for t in todo if t in delisted)} delisted; "
              f"{len(todo_member)} with S&P 500/NDX membership overlapping the dev window "
              f"({DEV_START}..{DEV_END}), {len(todo_member_delisted)} of them delisted")
        if todo_member_delisted:
            sample = ", ".join(todo_member_delisted[:12])
            more = "" if len(todo_member_delisted) <= 12 else f", ... (+{len(todo_member_delisted) - 12})"
            print(f"  delisted dev-window members: {sample}{more}")
        print(f"  unresolved tickers with stored events or runs (--purge-unresolved would forget): "
              f"{len(orphaned[tf])}{': ' + ', '.join(orphaned[tf]) if orphaned[tf] else ''}")
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
             "tickers whose resolved vendor changed since their last run (rescanned; old "
             "events replaced only if the rescan succeeds) -- the additive backfill mode "
             "for the vendor fallback",
    )
    parser.add_argument(
        "--plan", action="store_true",
        help="With --all: print the resolved universe and what --missing-only would run, "
             "then exit without detecting or writing anything",
    )
    parser.add_argument(
        "--purge-unresolved", action="store_true",
        help="With --all: DELETE everything stored for tickers that no longer resolve "
             "(whole-history price dispute or no bars): events, context rows, control pairs "
             "and their divergence runs rows, so a ticker that resolves again later is "
             "rescanned from scratch. Off by default -- destructive; --plan lists who",
    )
    args = parser.parse_args()

    if not args.all and not args.ticker:
        parser.error("TICKER is required unless --all is given")
    if args.all and args.plot:
        parser.error("--plot is not supported together with --all")
    if (args.plan or args.missing_only or args.purge_unresolved) and not args.all:
        parser.error("--plan/--missing-only/--purge-unresolved only make sense with --all")

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
        # Tickers with stored events that no longer resolve: detection never
        # touches them again, so without an explicit purge their events
        # outlive the dispute that disqualified them.
        orphaned = {
            tf: sorted((stored_tickers(derived_conn, tf.value) | set(recorded[tf])) - set(sources))
            for tf in timeframes
        }
        if args.plan:
            _print_plan(conn, sources, n_disputed, recorded, timeframes, orphaned)
            conn.close()
            derived_conn.close()
            return
        n_orphan_rows = 0
        for tf in timeframes:
            if orphaned[tf] and args.purge_unresolved:
                n_tf = sum(forget_ticker(derived_conn, ticker, tf.value) for ticker in orphaned[tf])
                derived_conn.commit()
                n_orphan_rows += n_tf
                print(f"{tf.value}: forgot {len(orphaned[tf])} unresolved ticker(s) "
                      f"({n_tf} stored event(s) deleted): {', '.join(orphaned[tf])}")
            elif orphaned[tf]:
                with_events = stored_tickers(derived_conn, tf.value) & set(orphaned[tf])
                print(f"{tf.value}: WARNING {len(orphaned[tf])} unresolved ticker(s) still recorded as "
                      f"scanned ({len(with_events)} with stored events): {', '.join(orphaned[tf][:10])} "
                      "-- pass --purge-unresolved to forget them")
        total, skipped, failed, unreliable, attempted, replaced = 0, 0, 0, 0, 0, 0
        for ticker in sorted(sources):
            for tf in timeframes:
                changed = vendor_changed(recorded[tf], ticker, sources[ticker])
                if args.missing_only and ticker in recorded[tf] and not changed:
                    continue
                if changed and args.as_of:
                    # A replacement purges the full stored history; a truncated
                    # as-of rescan would then silently drop every later event.
                    print(f"{ticker}/{tf.value}: vendor changed -- not replaced under --as-of "
                          "(run without --as-of to replace its full history)")
                    skipped += 1
                    continue
                attempted += 1
                try:
                    n, warn = _run_one(
                        conn, derived_conn, ticker, tf, args.as_of, config, None, args.indicator,
                        source=sources[ticker],
                        replace_from=(recorded[tf][ticker] or PRIMARY_SOURCE) if changed else None,
                    )
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
                    replaced += int(changed)
                    if warn:
                        unreliable += 1
        print(
            f"\nDone: {attempted} (ticker x timeframe) run(s) over {len(sources)} resolved ticker(s) -- "
            f"{total} divergence(s) total, {skipped} skipped, {failed} failed, {unreliable} unreliable runs; "
            f"{replaced} vendor-change replacement(s); "
            f"{n_disputed} ticker(s) excluded for whole-history price disputes"
            + (f"; {n_orphan_rows} unresolved-ticker event(s) purged." if args.purge_unresolved else ".")
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
            prior = recorded_run_sources(derived_conn, tf.value, ticker=args.ticker)
            changed = vendor_changed(prior, args.ticker, resolved[args.ticker])
            if changed and args.as_of:
                print(f"{args.ticker}/{tf.value}: vendor changed -- not replaced under --as-of "
                      "(run without --as-of to replace its full history)")
                continue
            want_plot = args.plot is not None and not plotted
            n, _warn = _run_one(
                conn, derived_conn, args.ticker, tf, args.as_of, config,
                args.plot if want_plot else None, args.indicator,
                source=resolved[args.ticker],
                replace_from=(prior[args.ticker] or PRIMARY_SOURCE) if changed else None,
            )
            if want_plot and n is not None:
                plotted = True
        if args.plot and not plotted:
            print(f"Note: {args.ticker} had no non-skipped timeframe to plot.")

    conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

import argparse
import sqlite3
from datetime import date

import pandas as pd
import yfinance as yf

from src.foundation.data_processing import db
from src.foundation.data_processing.retry import attempt_with_limited_retries
from src.foundation.data_processing.yfinance_client import to_yfinance_symbol
from src.foundation.utils.config_loader import load_config

JOB_TYPE = "yfinance_daily"


def _fetch_batch(tickers: list[str], start: str, end: str, split_only: bool = False) -> pd.DataFrame:
    # yfinance's `end` is exclusive (confirmed directly against the real API --
    # see yfinance_client.py's _fetch for the same fix), unlike Polygon's
    # inclusive end. Shifted by one day here so callers of this module get the
    # same inclusive-end semantics as bulk_polygon_ingest.py.
    end_inclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    yfinance_symbols = [to_yfinance_symbol(t) for t in tickers]
    # auto_adjust=True (yfinance's default) also adjusts for dividends and
    # spin-offs; False leaves `Close` adjusted for splits only (verified on
    # KO 2012-04-30: 38.16 split-only vs 24.46 fully adjusted).
    return yf.download(
        yfinance_symbols, start=start, end=end_inclusive, threads=True, progress=False, group_by="ticker",
        auto_adjust=not split_only,
    )


def _extract_ticker_frame(batch_result: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """`_fetch_batch` always passes a *list* to yf.download, even for a single
    ticker -- and a list-of-one still comes back MultiIndex-columned by
    ticker (confirmed directly against the real API; this is different from
    yf.download('AAPL', ...) with a bare string, which returns a plain frame
    -- that shortcut doesn't apply here since we never call it that way)."""
    frame = batch_result[ticker]
    frame = frame.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    return frame.dropna(how="all")


def backfill_yfinance_daily(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    batch_size: int = 50,
    as_of: pd.Timestamp | None = None,
    retry_backoff_seconds: float = 5.0,
    job_type: str = JOB_TYPE,
    tickers: list[str] | None = None,
    split_only: bool = False,
) -> None:
    """Bulk-ingest daily bars for `tickers` (default: every ticker in the
    reference table) from yfinance, batched (yf.download has no official
    rate limit to design a pace around, but batching + a per-batch retry cap
    keeps a bad batch from stalling the whole run).

    Resumable per *ticker*, not per batch -- if 3 of 50 tickers in a batch
    come back empty, only those 3 are marked failed and retried on a later
    run; the other 47 aren't redone. A ticker with no data in the response
    (rather than a request-level failure) is also treated as a miss to
    retry later, not a hard error.

    `job_type` scopes resumability: "success" for a ticker under one job_type
    says nothing about whether it succeeded for a *different* start/end range.
    Reuse the same job_type to resume/retry the same logical range; pass a
    different one for a genuinely different range (e.g. a deeper historical
    backfill) so it doesn't get silently skipped as already-done based on an
    unrelated prior run.

    `tickers`, if given, restricts the run to exactly that list instead of
    reading the full reference table -- e.g. for a scoped test run, or a
    manual retry of a specific subset. Without it, behavior is unchanged:
    every `type="CS"` ticker in the reference table (active and delisted).

    `split_only` stores closes adjusted for splits only, under
    `db.YFINANCE_SPLIT_ONLY` -- the price series market caps are built from
    (see `market_cap.PRICE_SOURCE`). Use a distinct `job_type` for it.
    """
    source = db.YFINANCE_SPLIT_ONLY if split_only else db.YFINANCE
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(date.today())

    if tickers is not None:
        all_tickers = sorted(tickers)
    else:
        ticker_table = db.read_tickers(conn, type_="CS")
        if ticker_table.empty:
            raise RuntimeError(
                "No tickers in the reference table -- run ticker_universe.py first "
                "to populate it before bulk ingestion."
            )
        all_tickers = sorted(ticker_table["ticker"])
    pending = db.pending_keys(conn, job_type, all_tickers)

    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        ok, result, error = attempt_with_limited_retries(
            lambda b=batch: _fetch_batch(b, start, end, split_only), backoff_seconds=retry_backoff_seconds
        )
        if not ok:
            for ticker in batch:
                db.record_job_result(conn, job_type, ticker, "failed", error)
            print(f"batch of {len(batch)} starting {batch[0]}: FAILED entirely ({error})")
            continue

        for ticker in batch:
            try:
                ticker_bars = _extract_ticker_frame(result, to_yfinance_symbol(ticker))
            except (KeyError, TypeError) as e:
                db.record_job_result(conn, job_type, ticker, "failed", f"no data returned: {e}")
                continue

            if ticker_bars.empty:
                db.record_job_result(conn, job_type, ticker, "failed", "no data returned")
                continue

            if ticker_bars.index.tz is not None:
                ticker_bars.index = ticker_bars.index.tz_localize(None)
            ticker_bars["is_partial"] = (
                ticker_bars.index.normalize() >= as_of.normalize()
            ).astype(int)

            db.upsert_bars(conn, "bars_1d", ticker, source, ticker_bars)
            db.record_job_result(conn, job_type, ticker, "success")

        print(f"batch of {len(batch)} starting {batch[0]}: processed")


# Incremental updates of the split-only (`traded`) series. Its history only
# changes when a stock splits (dividends don't touch it -- see
# docs/decisions/price-basis.md, "Updates"), so each ticker is fetched from a
# little before its last stored bar and the overlapping closes are checked
# against what's stored: equal -> append the new days; different (a split, or
# a Yahoo restatement) -> re-fetch the full history and replace it.
INCREMENTAL_JOB_TYPE = "yfinance_daily_split_only_incremental"
FULL_HISTORY_START = "1970-01-01"
OVERLAP_CALENDAR_DAYS = 10  # ~6-7 trading days before the last stored bar
# Re-fetched split-only closes match stored ones exactly when nothing changed
# (0.0 on 12 real tickers, 2026-10-04); a split moves them by its ratio.
CLOSE_REL_TOL = 1e-6
# A full re-fetch must reach back to the stored history's start (give or take
# a few days of listing-date noise); a shorter one is refused rather than
# allowed to delete history Yahoo no longer serves.
REFETCH_START_SLACK_DAYS = 7


def _stored_state(conn: sqlite3.Connection, tickers: list[str]) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """ticker -> (first, last) stored split-only bar date, for tickers that have any."""
    out = {}
    for i in range(0, len(tickers), 500):  # SQLite's bound-parameter limit
        batch = tickers[i:i + 500]
        rows = conn.execute(
            f"SELECT ticker, MIN(timestamp), MAX(timestamp) FROM bars_1d WHERE source = ? "
            f"AND ticker IN ({','.join('?' * len(batch))}) GROUP BY ticker",
            (db.YFINANCE_SPLIT_ONLY, *batch),
        ).fetchall()
        out.update({t: (pd.Timestamp(a).normalize(), pd.Timestamp(b).normalize()) for t, a, b in rows})
    return out


def _stored_closes(conn: sqlite3.Connection, ticker: str, start: pd.Timestamp) -> pd.Series:
    """Final (non-partial) stored split-only closes from `start` on, by date."""
    df = pd.read_sql_query(
        "SELECT timestamp, close FROM bars_1d WHERE ticker = ? AND source = ? AND is_partial = 0 AND timestamp >= ?",
        conn, params=(ticker, db.YFINANCE_SPLIT_ONLY, start.isoformat()), parse_dates=["timestamp"],
    )
    return df.set_index(df["timestamp"].dt.normalize())["close"]


def _ticker_bars(result: pd.DataFrame, ticker: str, as_of: pd.Timestamp) -> pd.DataFrame | None:
    """One ticker's frame from a batch download, tz-naive with `is_partial`; None if it came back empty."""
    try:
        bars = _extract_ticker_frame(result, to_yfinance_symbol(ticker))
    except (KeyError, TypeError):
        return None
    if bars.empty:
        return None
    if bars.index.tz is not None:
        bars.index = bars.index.tz_localize(None)
    bars["is_partial"] = (bars.index.normalize() >= as_of.normalize()).astype(int)
    return bars


def _replace_history(conn: sqlite3.Connection, ticker: str, bars: pd.DataFrame) -> None:
    """Swap a ticker's whole split-only history for `bars`, in one transaction."""
    try:
        conn.execute("DELETE FROM bars_1d WHERE ticker = ? AND source = ?", (ticker, db.YFINANCE_SPLIT_ONLY))
        db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE_SPLIT_ONLY, bars)  # commits
    except Exception:
        conn.rollback()
        raise


def update_split_only_incremental(
    conn: sqlite3.Connection,
    end: str | None = None,
    batch_size: int = 50,
    as_of: pd.Timestamp | None = None,
    retry_backoff_seconds: float = 5.0,
    job_type: str | None = None,
    tickers: list[str] | None = None,
) -> dict:
    """Bring the split-only (`traded`) bars up to `end` (default: today)
    without re-downloading every ticker's full history.

    Per ticker: fetch from `OVERLAP_CALENDAR_DAYS` before its last stored bar
    and compare the overlapping final closes with the stored ones.
    - equal: store the fetched days (new days appended; an earlier partial
      bar is overwritten by its final values);
    - different (a split since the last fetch, or a Yahoo restatement), no
      overlapping day to compare, or no stored bars at all: re-fetch the full
      history from `FULL_HISTORY_START` and replace it. A re-fetch that starts
      later than the stored history is refused (failed) -- Yahoo has been
      seen truncating old history (Done #74's 13 tickers).

    Default universe: tickers that already have split-only bars, plus active
    CS tickers that don't yet. Resumable per ticker under `job_type` (default:
    one bucket per `as_of` day), like `backfill_yfinance_daily`.

    Returns {"appended", "no_new_data", "refetched", "failed"} counts plus
    "refetch_reasons" and "failures" (ticker -> reason).
    """
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(date.today())
    end = end or as_of.strftime("%Y-%m-%d")
    job_type = job_type or f"{INCREMENTAL_JOB_TYPE}_{as_of:%Y%m%d}"

    if tickers is not None:
        universe = sorted(set(tickers))
    else:
        stored = {r[0] for r in conn.execute(
            "SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", (db.YFINANCE_SPLIT_ONLY,)
        )}
        universe = sorted(stored | set(db.read_tickers(conn, type_="CS", active=True)["ticker"]))
    pending = db.pending_keys(conn, job_type, universe)
    state = _stored_state(conn, pending)

    report = {"appended": 0, "no_new_data": 0, "refetched": 0, "failed": 0, "refetch_reasons": {}, "failures": {}}

    def fail(ticker: str, reason: str) -> None:
        report["failed"] += 1
        report["failures"][ticker] = reason
        db.record_job_result(conn, job_type, ticker, "failed", reason)

    def download(batch: list[str], start: str):
        ok, result, error = attempt_with_limited_retries(
            lambda: _fetch_batch(batch, start, end, split_only=True), backoff_seconds=retry_backoff_seconds
        )
        if not ok:
            for ticker in batch:
                fail(ticker, f"batch download failed: {error}")
        return result if ok else None

    # Tickers sharing a last stored date share a fetch window -- one download per window and batch.
    to_refetch: dict[str, str] = {t: "no stored bars" for t in pending if t not in state}
    by_start: dict[str, list[str]] = {}
    for ticker in pending:
        if ticker in state:
            start = state[ticker][1] - pd.Timedelta(days=OVERLAP_CALENDAR_DAYS)
            by_start.setdefault(start.strftime("%Y-%m-%d"), []).append(ticker)

    for start, group in sorted(by_start.items()):
        for i in range(0, len(group), batch_size):
            batch = group[i:i + batch_size]
            result = download(batch, start)
            if result is None:
                continue
            for ticker in batch:
                bars = _ticker_bars(result, ticker, as_of)
                if bars is None:
                    fail(ticker, "no data returned")
                    continue
                stored = _stored_closes(conn, ticker, pd.Timestamp(start))
                fetched = bars.loc[bars["is_partial"] == 0, "close"]
                fetched.index = fetched.index.normalize()
                common = fetched.index.intersection(stored.index)
                if common.empty:
                    to_refetch[ticker] = "no overlapping day to compare"
                    continue
                rel = (fetched.loc[common] / stored.loc[common] - 1).abs().max()
                if not rel <= CLOSE_REL_TOL:
                    to_refetch[ticker] = f"overlap closes differ (max rel {rel:.3g})"
                    continue
                # Always store the fetched window: besides new days, it carries the final
                # values of a bar stored earlier as partial (e.g. a Friday intraday run,
                # refreshed on Saturday with no new day).
                db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE_SPLIT_ONLY, bars)
                if (bars.index.normalize() > state[ticker][1]).any():
                    report["appended"] += 1
                else:
                    report["no_new_data"] += 1
                db.record_job_result(conn, job_type, ticker, "success")
            print(f"incremental batch of {len(batch)} from {start} starting {batch[0]}: processed")

    refetch = sorted(to_refetch)
    for i in range(0, len(refetch), batch_size):
        batch = refetch[i:i + batch_size]
        result = download(batch, FULL_HISTORY_START)
        if result is None:
            continue
        for ticker in batch:
            bars = _ticker_bars(result, ticker, as_of)
            if bars is None:
                fail(ticker, f"full re-fetch returned no data ({to_refetch[ticker]})")
                continue
            if ticker in state:
                first_stored, first_new = state[ticker][0], bars.index.min().normalize()
                if first_new > first_stored + pd.Timedelta(days=REFETCH_START_SLACK_DAYS):
                    fail(ticker, f"full re-fetch starts {first_new.date()}, stored history {first_stored.date()} "
                                 f"-- not replaced ({to_refetch[ticker]})")
                    continue
            _replace_history(conn, ticker, bars)
            report["refetched"] += 1
            report["refetch_reasons"][ticker] = to_refetch[ticker]
            db.record_job_result(conn, job_type, ticker, "success")
        print(f"full re-fetch batch of {len(batch)} starting {batch[0]}: processed")

    return report


def _print_incremental_report(report: dict) -> None:
    print(
        f"\nDone: {report['appended']} appended, {report['no_new_data']} no new data, "
        f"{report['refetched']} full re-fetch, {report['failed']} failed"
    )
    for ticker, reason in sorted(report["refetch_reasons"].items()):
        print(f"  re-fetched {ticker}: {reason}")
    for ticker, reason in sorted(report["failures"].items()):
        print(f"  FAILED {ticker}: {reason}")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-ingest daily bars for every reference ticker from yfinance"
    )
    parser.add_argument("--start", help="Start date, YYYY-MM-DD (required unless --incremental)")
    parser.add_argument("--end", help="End date, YYYY-MM-DD (required unless --incremental, which defaults to today)")
    parser.add_argument(
        "--incremental", action="store_true",
        help="With --split-only: append days since each ticker's last stored bar, re-fetching the full "
        "history only for tickers whose overlapping closes changed (a split). Default --job-type is one "
        f"bucket per day ({INCREMENTAL_JOB_TYPE}_YYYYMMDD).",
    )
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument(
        "--job-type",
        default=JOB_TYPE,
        help=(
            f"Resumability bucket (default: {JOB_TYPE!r}). Use a distinct value "
            "for a range that isn't the same logical backfill as a prior run -- "
            "e.g. a deeper historical pull -- so already-succeeded tickers from "
            "that other run aren't silently skipped here."
        ),
    )
    parser.add_argument(
        "--tickers",
        help="Comma-separated ticker list to restrict this run to (default: every "
        "CS ticker in the reference table, active and delisted)",
    )
    parser.add_argument(
        "--split-only", action="store_true",
        help=f"Store split-only-adjusted closes under source {db.YFINANCE_SPLIT_ONLY!r} (for market caps); "
        "pair it with its own --job-type",
    )
    parser.add_argument(
        "--tickers-with-source",
        help="Restrict the run to tickers that already have bars_1d rows under this source (e.g. 'yfinance')",
    )
    args = parser.parse_args()
    if args.incremental and not args.split_only:
        # total_return history rescales on every dividend; appending would leave seams.
        parser.error("--incremental needs --split-only (total-return bars must be re-fetched in full)")
    if not args.incremental and not (args.start and args.end):
        parser.error("--start and --end are required unless --incremental")

    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    tickers = args.tickers.split(",") if args.tickers else None
    if args.tickers_with_source:
        tickers = [r[0] for r in conn.execute(
            "SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", (args.tickers_with_source,)
        )]
    if args.incremental:
        job_type = args.job_type if args.job_type != JOB_TYPE else None
        report = update_split_only_incremental(
            conn, end=args.end, batch_size=args.batch_size, job_type=job_type, tickers=tickers,
        )
        _print_incremental_report(report)
    else:
        backfill_yfinance_daily(
            conn, args.start, args.end, batch_size=args.batch_size,
            job_type=args.job_type, tickers=tickers, split_only=args.split_only,
        )

    conn.close()


if __name__ == "__main__":
    main()

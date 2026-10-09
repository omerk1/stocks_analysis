"""Structural-context scalars per stored divergence event, plus the
point-in-time confluence re-clustering helper.

Scalars (DESIGN: docs/features/divergence-context/DESIGN.md, "Context
scalars (v0)") are measured over bars ending at p2's bar; their
availability timestamp is the event's own `confirmed_at` -- structure is
measured up to the second pivot, but nothing about the pair is knowable
before it confirms. Everything is direction-symmetric: "impulse" is the
move INTO p1 in the event's direction-of-extremes (advance into a HIGH
pair's p1, decline into a LOW pair's p1); all magnitudes are stored
positive. Deliberately crude and few -- step 0 asks "is there mass in this
region," not "what is the final feature set"; ratios are derived at
analysis time from these components.

`pit_confluence` exists because the stored
`confluence_count`/`agreeing_indicators` are FULL-RUN values: the backfill
necessarily runs with as_of=None, and detect() computes confluence after
its as_of filter precisely because confluence is not truncation-stable
(see tests/test_divergences_asof_equivalence.py's docstring). Any per-date
consumer re-clusters from stored rows with this helper instead of reading
the stored columns as as-of-date facts.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3

import numpy as np
import pandas as pd

from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db, indicators
from src.foundation.market_common.models import Timeframe

from src.signals.divergences.config import VENDOR_FALLBACK, DivergenceConfig
from src.signals.divergences.store import builder_sources

logger = logging.getLogger(__name__)

# Fixed lookback (bars) defining "the impulse into p1". With fewer bars of
# history before p1 than this, the impulse scalars are NaN rather than a
# silently-truncated-window value (repo invariant: derived features
# preserve their inputs' missingness).
IMPULSE_LOOKBACK_BARS = 63

_CONTEXT_SCHEMA = """
CREATE TABLE IF NOT EXISTS divergence_context (
    divergence_id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT, p2_date TEXT, confirmed_at TEXT,
    impulse_gain_pct REAL,
    interpeak_retrace_pct REAL,
    interpeak_retrace_frac REAL,
    leg2_gain_pct REAL,
    leg2_bars INTEGER,
    atr_contraction REAL,
    realized_vol_63 REAL,
    run_id TEXT
);
"""

# Columns added after the table first shipped (#164) -- same accumulating
# additive-migration pattern as store.py's, for the same reason: the live
# shared table can be any age.
_MIGRATED_COLUMNS: dict[str, str] = {
    "realized_vol_63": "REAL",  # Track-B matching covariate (PREREG "Controls")
}

_UPSERT_SQL = """
INSERT INTO divergence_context
    (divergence_id, ticker, timeframe, p2_date, confirmed_at,
     impulse_gain_pct, interpeak_retrace_pct, interpeak_retrace_frac,
     leg2_gain_pct, leg2_bars, atr_contraction, realized_vol_63, run_id)
VALUES
    (:divergence_id, :ticker, :timeframe, :p2_date, :confirmed_at,
     :impulse_gain_pct, :interpeak_retrace_pct, :interpeak_retrace_frac,
     :leg2_gain_pct, :leg2_bars, :atr_contraction, :realized_vol_63, :run_id)
ON CONFLICT (divergence_id) DO UPDATE SET
    impulse_gain_pct = excluded.impulse_gain_pct,
    interpeak_retrace_pct = excluded.interpeak_retrace_pct,
    interpeak_retrace_frac = excluded.interpeak_retrace_frac,
    leg2_gain_pct = excluded.leg2_gain_pct,
    leg2_bars = excluded.leg2_bars,
    atr_contraction = excluded.atr_contraction,
    realized_vol_63 = excluded.realized_vol_63,
    run_id = excluded.run_id
"""


def create_context_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CONTEXT_SCHEMA)
    have = {row[1] for row in conn.execute("PRAGMA table_info(divergence_context)")}
    for name, sql_type in _MIGRATED_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE divergence_context ADD COLUMN {name} {sql_type}")
    conn.commit()


def realized_vol_63(close: pd.Series) -> pd.Series:
    """Trailing 63-bar std of daily log returns, aligned so position i uses
    returns through bar i. NaN during warmup (needs the full window --
    derived features preserve their inputs' missingness). The Track-B
    matching covariate (PREREGISTRATION "Controls"); lives here so
    controls.py can share it without an import cycle."""
    log_ret = np.log(close).diff()
    return log_ret.rolling(63).std()


def _nan_to_none(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def compute_context_for_ticker(
    bars: pd.DataFrame, events: pd.DataFrame, atr: pd.Series
) -> list[dict]:
    """Context scalars for one ticker/timeframe's divergence rows against
    its (traded-basis) bars. `events` is a frame of stored `divergences`
    rows; rows whose p1/p2 dates are no longer in `bars`' index (a price
    re-ingest changed the calendar since detection) are skipped and
    counted by the caller via the returned length.

    Pure function over already-loaded inputs, mirroring
    detect.detect_for_indicator's split, so tests hand it small hand-built
    frames directly.
    """
    close = bars["close"]
    vol = realized_vol_63(close)
    out: list[dict] = []

    for ev in events.itertuples(index=False):
        try:
            i1 = bars.index.get_loc(pd.Timestamp(ev.p1_date))
            i2 = bars.index.get_loc(pd.Timestamp(ev.p2_date))
        except KeyError:
            continue
        if i2 <= i1:
            continue

        p1_close = close.iloc[i1]
        p2_close = close.iloc[i2]
        between = close.iloc[i1 : i2 + 1]
        # HIGH pairs (bearish direction, either form) measure advances and
        # downward retracements; LOW pairs mirror everything.
        is_high_pair = ev.direction == "bearish"

        # Impulse into p1 -- NaN with insufficient lookback, never a
        # quietly-shorter window.
        if i1 < IMPULSE_LOOKBACK_BARS:
            impulse_gain = np.nan
            impulse_abs = np.nan
        else:
            impulse_win = close.iloc[i1 - IMPULSE_LOOKBACK_BARS : i1 + 1]
            if is_high_pair:
                base = impulse_win.min()
                impulse_abs = p1_close - base
            else:
                base = impulse_win.max()
                impulse_abs = base - p1_close
            impulse_gain = impulse_abs / base if base > 0 else np.nan

        if is_high_pair:
            interpeak_extreme = between.min()
            extreme_pos = int(np.argmin(between.to_numpy()))
            retrace_abs = p1_close - interpeak_extreme
            leg2_gain = (
                (p2_close - interpeak_extreme) / interpeak_extreme
                if interpeak_extreme > 0
                else np.nan
            )
        else:
            interpeak_extreme = between.max()
            extreme_pos = int(np.argmax(between.to_numpy()))
            retrace_abs = interpeak_extreme - p1_close
            leg2_gain = (
                (interpeak_extreme - p2_close) / interpeak_extreme
                if interpeak_extreme > 0
                else np.nan
            )

        retrace_pct = retrace_abs / p1_close if p1_close > 0 else np.nan
        retrace_frac = (
            retrace_abs / impulse_abs
            if (not np.isnan(impulse_abs)) and impulse_abs > 0
            else np.nan
        )
        leg2_bars = (i2 - i1) - extreme_pos

        a1, a2 = atr.iloc[i1], atr.iloc[i2]
        atr_contraction = (
            a2 / a1 if (pd.notna(a1) and a1 > 0 and pd.notna(a2)) else np.nan
        )
        vol_at_p2 = vol.iloc[i2]

        out.append(
            {
                "divergence_id": ev.id,
                "ticker": ev.ticker,
                "timeframe": ev.timeframe,
                "p2_date": ev.p2_date,
                "confirmed_at": ev.confirmed_at,
                "impulse_gain_pct": _nan_to_none(impulse_gain),
                "interpeak_retrace_pct": _nan_to_none(retrace_pct),
                "interpeak_retrace_frac": _nan_to_none(retrace_frac),
                "leg2_gain_pct": _nan_to_none(leg2_gain),
                "leg2_bars": int(leg2_bars),
                "atr_contraction": _nan_to_none(atr_contraction),
                "realized_vol_63": _nan_to_none(vol_at_p2),
            }
        )

    return out


def pit_confluence(
    events: pd.DataFrame, bar_index: pd.DatetimeIndex, pairing_window: int = 3
) -> pd.Series:
    """Cluster sizes (distinct agreeing indicators) as they were knowable
    at the as_of the CALLER already filtered `events` to (confirmed_at <=
    as_of) -- the PIT replacement for the stored full-run
    confluence_count. Same clustering walk as detect._apply_confluence:
    within each (direction, form) group, sort by p2 bar position and break
    a cluster when the gap to the previous member exceeds
    `pairing_window`; every member gets the cluster's distinct-indicator
    count. Returns an int Series aligned to `events.index`.

    One ticker/timeframe at a time -- bar positions only mean anything
    against that ticker's own calendar, so mixed input would silently
    cluster unrelated tickers' rows into one "swing". Rows whose p2_date
    is no longer on the bar calendar (a price re-ingest changed it since
    detection) can't be positioned and stay solo (count 1) -- the same
    skip stance compute_context_for_ticker takes.
    """
    for col in ("ticker", "timeframe"):
        if col in events.columns and events[col].nunique() > 1:
            raise ValueError(
                f"pit_confluence clusters one ticker/timeframe at a time; got multiple {col}s"
            )
    counts = pd.Series(1, index=events.index, dtype=int)
    if events.empty:
        return counts
    locs = bar_index.get_indexer(pd.DatetimeIndex(pd.to_datetime(events["p2_date"])))
    pos = pd.Series(locs, index=events.index)
    located = events.loc[pos[pos >= 0].index]

    for _, group in located.groupby(["direction", "form"]):
        ordered = pos.loc[group.index].sort_values()
        cluster: list = []
        prev_pos: int | None = None

        def flush(members: list) -> None:
            if not members:
                return
            n = events.loc[members, "indicator"].nunique()
            counts.loc[members] = n

        for idx, bar_pos in ordered.items():
            if prev_pos is not None and bar_pos - prev_pos > pairing_window:
                flush(cluster)
                cluster = []
            cluster.append(idx)
            prev_pos = bar_pos
        flush(cluster)

    return counts


def build_context(
    raw_conn: sqlite3.Connection, derived_conn: sqlite3.Connection
) -> tuple[int, int, int, int, int]:
    """Compute+store context scalars for every stored daily divergence row.
    Returns (rows_written, tickers_processed, rows_skipped,
    tickers_unresolved, tickers_vendor_stale). Reruns are idempotent
    (deterministic recompute, upsert by divergence_id)."""
    config = DivergenceConfig()
    create_context_table(derived_conn)

    tickers = [
        r[0]
        for r in derived_conn.execute(
            "SELECT DISTINCT ticker FROM divergences WHERE timeframe = 'daily' ORDER BY ticker"
        )
    ]
    # Same per-ticker vendor the detector read: context scalars must come
    # from the bars the events were found on. Unresolved and vendor-stale
    # tickers (store.builder_sources) get their context rows purged and are
    # skipped, never computed on a mismatched vendor; a vendor-stale ticker
    # recovers once detection replaces its events.
    sources, flagged = builder_sources(
        raw_conn, derived_conn, tickers, config.price_basis, VENDOR_FALLBACK
    )
    written = skipped = processed = unresolved = vendor_stale = 0
    for ticker in tickers:
        if ticker in flagged:
            n_purged = derived_conn.execute(
                "DELETE FROM divergence_context WHERE ticker = ? AND timeframe = 'daily'",
                (ticker,),
            ).rowcount
            derived_conn.commit()
            logger.warning("%s: %s -- purged %d stale context row(s)%s", ticker, flagged[ticker], n_purged,
                           "; rescan detection first" if flagged[ticker] == "vendor_stale" else "")
            if flagged[ticker] == "unresolved":
                unresolved += 1
            else:
                vendor_stale += 1
            continue
        events = pd.read_sql_query(
            "SELECT * FROM divergences WHERE ticker = ? AND timeframe = 'daily'",
            derived_conn,
            params=[ticker],
        )
        # The write path sits INSIDE the per-ticker guard too: a single
        # bad row must mean one skipped ticker (rolled back, counted,
        # logged), never an aborted backfill with the remaining tickers
        # unprocessed. A committed runs row for a failed ticker is
        # acceptable (same stance as cli.py's --all loop).
        try:
            bars, report = data_mod.load_and_validate(
                raw_conn, ticker, Timeframe.DAILY, basis=config.price_basis,
                source=sources[ticker],
            )
            if len(bars) == 0:
                skipped += len(events)
                continue
            atr = indicators.atr(bars, config.atr_period)
            rows = compute_context_for_ticker(bars, events, atr)
            run_id = derived_db.record_run(
                derived_conn, "divergence_context", ticker, "daily", None,
                json.dumps({"impulse_lookback_bars": IMPULSE_LOOKBACK_BARS}),
                report.rows_dropped, report.unreliable,
            )
            for row in rows:
                row["run_id"] = run_id
                derived_conn.execute(_UPSERT_SQL, row)
            derived_conn.commit()
        except Exception:
            derived_conn.rollback()
            logger.exception("%s: context computation failed", ticker)
            skipped += len(events)
            continue

        written += len(rows)
        skipped += len(events) - len(rows)
        processed += 1

    return written, processed, skipped, unresolved, vendor_stale


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute structural-context scalars for stored daily divergences"
    )
    parser.parse_args()

    raw_conn, derived_conn = derived_db.bootstrap_cli(create_context_table)
    written, processed, skipped, unresolved, vendor_stale = build_context(raw_conn, derived_conn)
    print(f"Done: {processed} ticker(s), {written} context row(s) written, {skipped} event(s) skipped, "
          f"{unresolved} ticker(s) unresolved (stale context purged), "
          f"{vendor_stale} skipped for a vendor change (rescan detection first).")
    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

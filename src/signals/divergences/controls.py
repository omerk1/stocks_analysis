"""Control-pair extraction for the divergence-context study's Track-B run
(PREREGISTRATION.md "Controls"): every consecutive same-kind price-pivot
pair, price geometry and context scalars attached, with a flag for whether
a stored regular divergence (any indicator) sits on the same swing.

The table is the SAMPLING FRAME for both sides of the comparison: rows
with `has_divergence=0` and regular geometry are the matched-control pool
(step 0 measured it at ~71% of shaped pairs); the divergence events
themselves come from the `divergences` table as usual. Pairs are extracted
with the exact pivot machinery detection uses (same ATR-adaptive
`detect_pivots`, same 2x-ATR threshold, same warmup slicing), so a control
pair is "the same kind of swing, minus the divergence" by construction
rather than by approximation.

Timing: a pair's `confirmed_at` is its p2 pivot's own price-only
confirmation -- knowable without any indicator. Divergence events confirm
at max(price, indicator) confirmation, so events enter on average slightly
later than controls; the pre-registered difference-in-differences absorbs
this level difference (recorded there, not "fixed" here).

Like `divergences`/`divergence_context`, the table spans full history and
the study's holdout lock applies at read time (DESIGN.md "Holdout boundary
of this table, explicitly").
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import uuid

import numpy as np
import pandas as pd

from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db, indicators
from src.foundation.market_common.models import PivotKind, Timeframe
from src.foundation.market_common.pivots import detect_pivots
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.context import compute_context_for_ticker

logger = logging.getLogger(__name__)

# How close (in bars) a stored divergence's p2 must be to a pair's p2 to
# flag the pair as divergence-bearing. Matches the detector's own
# pairing_window: that is already this config family's notion of "the same
# swing".
DIVERGENCE_MATCH_BARS = 3

_CONTROL_PAIRS_SCHEMA = """
CREATE TABLE IF NOT EXISTS divergence_control_pairs (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT,
    direction TEXT,
    p1_date TEXT, p2_date TEXT,
    p1_price REAL, p2_price REAL,
    span_bars INTEGER,
    regular_geometry INTEGER,
    confirmed_at TEXT,
    has_divergence INTEGER,
    nearest_divergence_bars INTEGER,
    impulse_gain_pct REAL,
    interpeak_retrace_pct REAL,
    interpeak_retrace_frac REAL,
    leg2_gain_pct REAL,
    leg2_bars INTEGER,
    atr_contraction REAL,
    realized_vol_63 REAL,
    run_id TEXT,
    UNIQUE (ticker, timeframe, direction, p2_date)
);
"""

_UPSERT_SQL = """
INSERT INTO divergence_control_pairs
    (id, ticker, timeframe, direction, p1_date, p2_date, p1_price, p2_price,
     span_bars, regular_geometry, confirmed_at, has_divergence,
     nearest_divergence_bars, impulse_gain_pct, interpeak_retrace_pct,
     interpeak_retrace_frac, leg2_gain_pct, leg2_bars, atr_contraction,
     realized_vol_63, run_id)
VALUES
    (:id, :ticker, :timeframe, :direction, :p1_date, :p2_date, :p1_price, :p2_price,
     :span_bars, :regular_geometry, :confirmed_at, :has_divergence,
     :nearest_divergence_bars, :impulse_gain_pct, :interpeak_retrace_pct,
     :interpeak_retrace_frac, :leg2_gain_pct, :leg2_bars, :atr_contraction,
     :realized_vol_63, :run_id)
ON CONFLICT (ticker, timeframe, direction, p2_date) DO UPDATE SET
    p1_date = excluded.p1_date,
    p1_price = excluded.p1_price,
    p2_price = excluded.p2_price,
    span_bars = excluded.span_bars,
    regular_geometry = excluded.regular_geometry,
    confirmed_at = excluded.confirmed_at,
    has_divergence = excluded.has_divergence,
    nearest_divergence_bars = excluded.nearest_divergence_bars,
    impulse_gain_pct = excluded.impulse_gain_pct,
    interpeak_retrace_pct = excluded.interpeak_retrace_pct,
    interpeak_retrace_frac = excluded.interpeak_retrace_frac,
    leg2_gain_pct = excluded.leg2_gain_pct,
    leg2_bars = excluded.leg2_bars,
    atr_contraction = excluded.atr_contraction,
    realized_vol_63 = excluded.realized_vol_63,
    run_id = excluded.run_id
"""


def create_control_pairs_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CONTROL_PAIRS_SCHEMA)
    conn.commit()


def extract_pairs_for_ticker(
    bars: pd.DataFrame, config: DivergenceConfig, ticker: str
) -> pd.DataFrame:
    """Every consecutive same-kind price-pivot pair with span >=
    min_pivot_span_bars, using detection's own pivot machinery and warmup
    slicing. Returns a frame shaped like `divergences` rows where the
    context computation expects them (direction/p1_date/p2_date/...), plus
    pair-only columns (span_bars, regular_geometry, price-only
    confirmed_at). Pure over loaded bars, so tests can hand-build input.
    """
    warm = min(config.warmup_bars, max(len(bars) - 2, 0))
    close_s = bars["close"].iloc[warm:]
    atr = indicators.atr(bars, config.atr_period)
    atr_s = atr.iloc[warm:]
    pivots = detect_pivots(
        close_s, threshold_fn=lambda i: config.price_pivot_atr_mult * atr_s.iloc[i]
    )

    rows = []
    for kind, direction in ((PivotKind.HIGH, "bearish"), (PivotKind.LOW, "bullish")):
        same_kind = [p for p in pivots if p.kind == kind]
        for k in range(len(same_kind) - 1):
            p1, p2 = same_kind[k], same_kind[k + 1]
            span = p2.bar_index - p1.bar_index
            if span < config.min_pivot_span_bars:
                continue
            # Strict geometry, matching the detector's tol=0 default:
            # regular-bearish shape = higher high, regular-bullish = lower
            # low. Equal extremes are neither (regular_geometry=0).
            if kind == PivotKind.HIGH:
                regular = p2.value > p1.value
            else:
                regular = p2.value < p1.value
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "ticker": ticker,
                    "timeframe": "daily",
                    "direction": direction,
                    "p1_date": p1.timestamp,
                    "p2_date": p2.timestamp,
                    "p1_price": float(p1.value),
                    "p2_price": float(p2.value),
                    "span_bars": int(span),
                    "regular_geometry": int(regular),
                    "confirmed_at": pd.Timestamp(p2.confirmed_at).isoformat(),
                }
            )
    return pd.DataFrame(rows)


def flag_divergences(
    pairs: pd.DataFrame, stored_p2_dates: pd.DatetimeIndex, bar_index: pd.DatetimeIndex
) -> pd.DataFrame:
    """`has_divergence` / `nearest_divergence_bars` per pair: bar distance
    from the pair's p2 to the nearest stored regular divergence p2 (any
    indicator) OF THE SAME DIRECTION -- callers pass per-direction date
    sets. Distance in BARS on this ticker's own calendar, not calendar
    days. Pairs or stored dates off the calendar count as no-match."""
    pairs = pairs.copy()
    pairs["has_divergence"] = 0
    pairs["nearest_divergence_bars"] = None
    if pairs.empty or len(stored_p2_dates) == 0:
        return pairs

    stored_pos = bar_index.get_indexer(stored_p2_dates)
    stored_pos = np.sort(stored_pos[stored_pos >= 0])
    if len(stored_pos) == 0:
        return pairs

    pair_pos = bar_index.get_indexer(pd.DatetimeIndex(pd.to_datetime(pairs["p2_date"])))
    for i, pos in enumerate(pair_pos):
        if pos < 0:
            continue
        j = np.searchsorted(stored_pos, pos)
        candidates = []
        if j < len(stored_pos):
            candidates.append(abs(int(stored_pos[j]) - pos))
        if j > 0:
            candidates.append(abs(int(stored_pos[j - 1]) - pos))
        nearest = min(candidates)
        pairs.iloc[i, pairs.columns.get_loc("nearest_divergence_bars")] = nearest
        if nearest <= DIVERGENCE_MATCH_BARS:
            pairs.iloc[i, pairs.columns.get_loc("has_divergence")] = 1
    return pairs


def build_control_pairs(
    raw_conn: sqlite3.Connection, derived_conn: sqlite3.Connection
) -> tuple[int, int, int]:
    """Extract+store control pairs for every ticker that has stored daily
    divergences (the study's universe is defined by where detection ran).
    Idempotent: deterministic recompute, upserted by natural key. Returns
    (rows_written, tickers_processed, tickers_skipped)."""
    config = DivergenceConfig()
    create_control_pairs_table(derived_conn)

    tickers = [
        r[0]
        for r in derived_conn.execute(
            "SELECT DISTINCT ticker FROM divergences WHERE timeframe = 'daily' ORDER BY ticker"
        )
    ]
    written = skipped = processed = 0
    for ticker in tickers:
        try:
            bars, report = data_mod.load_and_validate(
                raw_conn, ticker, Timeframe.DAILY, basis=config.price_basis
            )
            if len(bars) < config.min_bars:
                skipped += 1
                continue
            pairs = extract_pairs_for_ticker(bars, config, ticker)
            if pairs.empty:
                skipped += 1
                continue

            stored = pd.read_sql_query(
                "SELECT p2_date, direction FROM divergences"
                " WHERE ticker = ? AND timeframe = 'daily' AND form = 'regular'",
                derived_conn,
                params=[ticker],
            )
            flagged = []
            for direction, grp in pairs.groupby("direction"):
                dates = pd.DatetimeIndex(
                    pd.to_datetime(stored.loc[stored["direction"] == direction, "p2_date"])
                )
                flagged.append(flag_divergences(grp, dates, bars.index))
            pairs = pd.concat(flagged, ignore_index=True)

            atr = indicators.atr(bars, config.atr_period)
            ctx_rows = compute_context_for_ticker(bars, pairs, atr)
            scalar_cols = [
                "impulse_gain_pct", "interpeak_retrace_pct", "interpeak_retrace_frac",
                "leg2_gain_pct", "leg2_bars", "atr_contraction", "realized_vol_63",
            ]
            if ctx_rows:
                ctx = pd.DataFrame(ctx_rows).rename(columns={"divergence_id": "id"})
            else:
                ctx = pd.DataFrame(columns=["id", *scalar_cols])
            merged = pairs.merge(ctx[["id", *scalar_cols]], on="id", how="left")

            run_id = derived_db.record_run(
                derived_conn, "divergence_control_pairs", ticker, "daily", None,
                json.dumps({"divergence_match_bars": DIVERGENCE_MATCH_BARS}),
                report.rows_dropped, report.unreliable,
            )
            for row in merged.to_dict("records"):
                row["run_id"] = run_id
                row["leg2_bars"] = None if pd.isna(row.get("leg2_bars")) else int(row["leg2_bars"])
                for key, value in row.items():
                    if isinstance(value, float) and np.isnan(value):
                        row[key] = None
                derived_conn.execute(_UPSERT_SQL, row)
            derived_conn.commit()
            written += len(merged)
            processed += 1
        except Exception:
            derived_conn.rollback()
            logger.exception("%s: control-pair extraction failed", ticker)
            skipped += 1
            continue

    return written, processed, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract price-only pivot pairs (the Track-B control sampling frame)"
    )
    parser.parse_args()
    raw_conn, derived_conn = derived_db.bootstrap_cli(create_control_pairs_table)
    written, processed, skipped = build_control_pairs(raw_conn, derived_conn)
    print(f"Done: {processed} ticker(s), {written} pair(s) written, {skipped} skipped.")
    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

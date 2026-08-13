"""python -m src.analysis.gap_fill_predictive_power [--horizons 5,10,20,60]
    [--fill-threshold 50] [--per-bar-csv PATH] [--summary-csv PATH]

Standalone, read-only research script for the backlog item "Gap
fill-percentage predictive-power analysis" (docs/backlog.md).

`gaps` (data/derived/analysis.sqlite) stores only the *collapsed* lifecycle
outcome per gap: one final `max_fill_pct`, plus three threshold-crossing
dates/bar-offsets (first touch, `soft_close_pct`, 100%). There's no way to
tell "81% filled" from "99% filled", or how fast fill % moved *between*
milestones, from the stored table alone.

This script reconstructs the FULL per-bar fill-% time series by replaying
`gaps.lifecycle._penetration_pct` (imported directly, never reimplemented)
bar-by-bar against `bars_1d`, from each gap's `created_at` onward, then
correlates candidate fill-based signals -- peak fill %, how fast fill %
reached a threshold, whether it ever fully closed -- against direction-
adjusted forward returns at several bar horizons.

Two forward-return reference points are computed (a deliberate design
call, since the backlog leaves this open): (a) N bars after `created_at`
("did the gap's fill behavior predict what happened to the stock next"),
and (b) N bars after the gap's own peak-fill bar ("does a deep/fast
retracement predict a reaction right after it tops out"). Returns are
direction-adjusted (positive = continuation in the gap's own original
direction) so bullish and bearish gaps can be pooled into one correlation,
the same "favorable move in the original direction" convention
`gaps.lifecycle._apply_reaction` and `divergences.lifecycle.apply_outcome`
already use for their own forward-looking checks.

Read-only by construction, not just convention: both DB connections are
opened in SQLite's own `mode=ro` URI mode, so a write would fail at the
sqlite3 layer even if this script tried one. It never imports
`gaps.store`/`gaps.detect`, never creates a table, never touches
`src/gaps/*`'s own schema. `fill_by` is NOT a column on the `gaps` table
(confirmed by reading `src/gaps/store.py`'s actual `_GAPS_SCHEMA` before
writing this -- only `GapConfig`/`runs.config_json` carry it), so it's
recovered here via a join against `runs.config_json`.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd
from scipy import stats

from src.data_processing import db as raw_db
from src.gaps.lifecycle import _penetration_pct
from src.gaps.models import Direction
from src.market_common import data as data_mod
from src.market_common import derived_db
from src.market_common.models import Timeframe
from src.utils.config_loader import load_config

DEFAULT_HORIZONS = (5, 10, 20, 60)
DEFAULT_FILL_THRESHOLD = 50.0


def _read_only_connection(db_path: Path) -> sqlite3.Connection:
    """Opens `db_path` in SQLite's own read-only URI mode -- a write
    attempt fails at the sqlite3 layer itself, not just by convention of
    this script never issuing one."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def load_gaps(derived_conn: sqlite3.Connection) -> pd.DataFrame:
    """Every stored gap, joined against its own `runs` row to recover
    `fill_by` -- the one piece of `GapConfig` `_penetration_pct` needs that
    isn't itself a `gaps` column (see module docstring)."""
    df = pd.read_sql_query(
        """
        SELECT g.*, r.config_json
        FROM gaps g
        JOIN runs r ON r.run_id = g.run_id
        """,
        derived_conn,
    )
    df["fill_by"] = df["config_json"].apply(lambda s: json.loads(s)["fill_by"])
    return df.drop(columns=["config_json"])


def reconstruct_fill_series(bars: pd.DataFrame, gap: pd.Series) -> pd.DataFrame | None:
    """Replays `_penetration_pct` bar-by-bar from `gap['created_at']`
    (exclusive) forward, returning a DataFrame indexed by
    `bars_since_creation` (1, 2, ...) with columns `date`, `raw_pct` (that
    single bar's own penetration, not cumulative -- exactly what
    `_penetration_pct` returns) and `cummax_pct` (the running-max fill %,
    the same quantity `lifecycle._walk` collapses straight to
    `max_fill_pct` and discards the path to).

    Stops as soon as `cummax_pct` first reaches 100% -- once a gap is
    fully closed, `cummax_pct` can never move again (it's a running max
    saturated at its own ceiling), so every bar walked past that point
    would just repeat the same 100.0 forever. This mirrors `_walk`'s own
    `n_approaches` bounding logic in `src/gaps/lifecycle.py` ("once cummax
    first reaches 100%, the gap is fully closed and done" -- confirmed
    there against real data, where *not* bounding this way let a real
    AAPL gap keep accumulating unrelated activity for two more years).
    A gap that never closes still walks to the end of available data,
    same as `_walk` itself.

    Returns None if `created_at` isn't found in `bars` (this ticker's
    history in the currently-loaded `bars_1d` doesn't reach back that
    far, or a stale row from a since-changed universe).
    """
    idx = bars.index
    try:
        created_pos = idx.get_loc(pd.Timestamp(gap["created_at"]))
    except KeyError:
        return None

    direction = Direction(gap["direction"])
    zone_top = float(gap["zone_top"])
    zone_bottom = float(gap["zone_bottom"])
    fill_by = gap["fill_by"]

    rows = []
    running_max = 0.0
    for offset, pos in enumerate(range(created_pos + 1, len(idx)), start=1):
        bar = bars.iloc[pos]
        pct = _penetration_pct(direction, zone_top, zone_bottom, bar, fill_by)
        running_max = max(running_max, pct)
        rows.append((offset, idx[pos], pct, running_max))
        if running_max >= 100.0:
            break

    if not rows:
        return None
    series = pd.DataFrame(rows, columns=["bars_since_creation", "date", "raw_pct", "cummax_pct"])
    return series.set_index("bars_since_creation")


def _return_pct(bars: pd.DataFrame, from_pos: int, to_pos: int, direction: Direction) -> float | None:
    """Direction-adjusted %% price return of `close` between two absolute
    bar positions in `bars` -- positive means continuation in the gap's
    own original direction, negative means reversal, regardless of
    whether the gap itself was bullish or bearish. None if `to_pos` runs
    past the end of available data.
    """
    if to_pos >= len(bars) or from_pos < 0:
        return None
    base_close = bars["close"].iloc[from_pos]
    fwd_close = bars["close"].iloc[to_pos]
    if base_close <= 0:
        return None
    ret = (fwd_close - base_close) / base_close * 100.0
    return ret if direction == Direction.BULLISH else -ret


def compute_signals(fill_series: pd.DataFrame, fill_threshold: float) -> dict:
    """Candidate predictive signals derived from one gap's reconstructed
    series -- covers both angles the backlog names: "peak fill %" (how
    deep) and "how fast" (bars to reach a threshold / to reach its own
    ultimate peak)."""
    cummax = fill_series["cummax_pct"]
    peak_fill_pct = float(cummax.iloc[-1])
    bars_to_peak = int(cummax.idxmax())  # first occurrence of the max, since cummax is monotonic

    hit_threshold = cummax[cummax >= fill_threshold]
    bars_to_threshold = int(hit_threshold.index[0]) if not hit_threshold.empty else None

    hit_100 = cummax[cummax >= 100.0]
    bars_to_closed_recomputed = int(hit_100.index[0]) if not hit_100.empty else None

    return {
        "peak_fill_pct": peak_fill_pct,
        "bars_to_peak": bars_to_peak,
        "bars_to_threshold": bars_to_threshold,
        "bars_to_closed_recomputed": bars_to_closed_recomputed,
        "ever_closed_recomputed": int(bars_to_closed_recomputed is not None),
    }


def build_dataset(
    raw_conn: sqlite3.Connection,
    derived_conn: sqlite3.Connection,
    horizons: tuple[int, ...],
    fill_threshold: float,
    ticker_filter: str | None = None,
    timeframe_filter: str | None = None,
    per_bar_rows: list | None = None,
) -> tuple[pd.DataFrame, int]:
    """Returns (per-gap results DataFrame, n_skipped). `per_bar_rows`, if
    given a list, gets one row per (gap, bar-since-creation) appended to it
    -- the full reconstructed series, for the optional --per-bar-csv.
    """
    gaps_df = load_gaps(derived_conn)
    if ticker_filter:
        gaps_df = gaps_df[gaps_df["ticker"] == ticker_filter]
    if timeframe_filter:
        gaps_df = gaps_df[gaps_df["timeframe"] == timeframe_filter]

    bars_cache: dict[tuple[str, str], pd.DataFrame] = {}
    records = []
    n_skipped = 0

    for _, gap in gaps_df.iterrows():
        key = (gap["ticker"], gap["timeframe"])
        if key not in bars_cache:
            bars, _report = data_mod.load_and_validate(raw_conn, gap["ticker"], Timeframe(gap["timeframe"]))
            bars_cache[key] = bars
        bars = bars_cache[key]

        fill_series = reconstruct_fill_series(bars, gap)
        if fill_series is None:
            n_skipped += 1
            continue

        idx = bars.index
        created_pos = idx.get_loc(pd.Timestamp(gap["created_at"]))
        direction = Direction(gap["direction"])
        signals = compute_signals(fill_series, fill_threshold)
        peak_pos = created_pos + signals["bars_to_peak"]

        record = {
            "gap_id": gap["id"],
            "ticker": gap["ticker"],
            "timeframe": gap["timeframe"],
            "kind": gap["kind"],
            "direction": gap["direction"],
            "created_at": gap["created_at"],
            "stored_max_fill_pct": gap["max_fill_pct"],
            "stored_status": gap["status"],
            **signals,
        }
        for h in horizons:
            record[f"fwd_return_from_creation_{h}b"] = _return_pct(bars, created_pos, created_pos + h, direction)
            record[f"fwd_return_from_peak_{h}b"] = _return_pct(bars, peak_pos, peak_pos + h, direction)
        records.append(record)

        if per_bar_rows is not None:
            for offset, row in fill_series.iterrows():
                per_bar_rows.append({
                    "gap_id": gap["id"],
                    "ticker": gap["ticker"],
                    "timeframe": gap["timeframe"],
                    "kind": gap["kind"],
                    "bars_since_creation": offset,
                    "date": row["date"].isoformat(),
                    "raw_pct": row["raw_pct"],
                    "cummax_pct": row["cummax_pct"],
                })

    return pd.DataFrame.from_records(records), n_skipped


def _corr_row(df: pd.DataFrame, signal_col: str, target_col: str) -> dict:
    sub = df[[signal_col, target_col]].dropna()
    n = len(sub)
    row = {"signal": signal_col, "target": target_col, "n": n,
           "pearson_r": None, "pearson_p": None, "spearman_rho": None, "spearman_p": None}
    if n < 3 or sub[signal_col].nunique() < 2 or sub[target_col].nunique() < 2:
        return row
    pearson_r, pearson_p = stats.pearsonr(sub[signal_col], sub[target_col])
    spearman_rho, spearman_p = stats.spearmanr(sub[signal_col], sub[target_col])
    row.update(pearson_r=pearson_r, pearson_p=pearson_p, spearman_rho=spearman_rho, spearman_p=spearman_p)
    return row


def correlation_report(df: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    """One row per (signal, target, horizon) -- the two "how deep" signals
    (peak_fill_pct, ever_closed_recomputed) and two "how fast" signals
    (bars_to_threshold, bars_to_peak) against both forward-return
    reference points, at every requested horizon.
    """
    signal_cols = ["peak_fill_pct", "ever_closed_recomputed", "bars_to_threshold", "bars_to_peak"]
    rows = []
    for h in horizons:
        for ref in ("from_creation", "from_peak"):
            target_col = f"fwd_return_{ref}_{h}b"
            for signal_col in signal_cols:
                rows.append(_corr_row(df, signal_col, target_col))
    return pd.DataFrame(rows)


def _fmt(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    return f"{x:.3f}" if isinstance(x, float) else str(x)


def print_report(df: pd.DataFrame, n_skipped: int, corr: pd.DataFrame, fill_threshold: float) -> None:
    print(f"Gaps reconstructed: {len(df)} (skipped {n_skipped} -- created_at not found in loaded bars)")
    if df.empty:
        print("No gaps to report on.")
        return

    print(f"By ticker: {dict(df['ticker'].value_counts())}")
    print(f"By kind: {dict(df['kind'].value_counts())}")
    print(f"By direction: {dict(df['direction'].value_counts())}")
    print(f"Ever closed (recomputed): {int(df['ever_closed_recomputed'].sum())}/{len(df)}")
    print(f"Reached >= {fill_threshold:.0f}% fill: "
          f"{int((df['peak_fill_pct'] >= fill_threshold).sum())}/{len(df)}")
    print(f"peak_fill_pct: mean={df['peak_fill_pct'].mean():.1f} median={df['peak_fill_pct'].median():.1f}")

    print("\nCorrelations (signal vs. direction-adjusted forward return; "
          "positive = signal predicts continuation in the gap's own original direction):")
    header = f"{'signal':<24}{'target':<28}{'n':>6}{'pearson_r':>12}{'pearson_p':>12}{'spearman':>12}{'spear_p':>12}"
    print(header)
    print("-" * len(header))
    for _, row in corr.iterrows():
        print(
            f"{row['signal']:<24}{row['target']:<28}{row['n']:>6}"
            f"{_fmt(row['pearson_r']):>12}{_fmt(row['pearson_p']):>12}"
            f"{_fmt(row['spearman_rho']):>12}{_fmt(row['spearman_p']):>12}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only: correlate reconstructed gap fill-% history against forward returns."
    )
    parser.add_argument("--horizons", default=",".join(str(h) for h in DEFAULT_HORIZONS),
                         help="Comma-separated bar horizons for forward returns (default: 5,10,20,60)")
    parser.add_argument("--fill-threshold", type=float, default=DEFAULT_FILL_THRESHOLD,
                         help="Fill %% threshold for the 'how fast' bars_to_threshold signal (default: 50)")
    parser.add_argument("--ticker", default=None, help="Restrict to one ticker (default: all)")
    parser.add_argument("--timeframe", default=None, choices=["daily", "weekly"],
                         help="Restrict to one timeframe (default: both)")
    parser.add_argument("--per-bar-csv", default=None, metavar="PATH",
                         help="Write the full reconstructed per-bar fill-%% series here")
    parser.add_argument("--summary-csv", default=None, metavar="PATH",
                         help="Write the per-gap signal/forward-return table here")
    args = parser.parse_args()

    horizons = tuple(int(h) for h in args.horizons.split(","))

    app_config = load_config()
    raw_path = raw_db.default_db_path(app_config.data_paths.raw)
    derived_path = derived_db.default_derived_db_path(app_config.data_paths.derived)
    raw_conn = _read_only_connection(raw_path)
    derived_conn = _read_only_connection(derived_path)

    per_bar_rows: list | None = [] if args.per_bar_csv else None
    df, n_skipped = build_dataset(
        raw_conn, derived_conn, horizons, args.fill_threshold,
        ticker_filter=args.ticker, timeframe_filter=args.timeframe,
        per_bar_rows=per_bar_rows,
    )
    raw_conn.close()
    derived_conn.close()

    corr = correlation_report(df, horizons)
    print_report(df, n_skipped, corr, args.fill_threshold)

    if args.summary_csv and not df.empty:
        df.to_csv(args.summary_csv, index=False)
        print(f"\nWrote per-gap summary CSV: {args.summary_csv}")
    if args.per_bar_csv and per_bar_rows:
        pd.DataFrame.from_records(per_bar_rows).to_csv(args.per_bar_csv, index=False)
        print(f"Wrote per-bar fill-%% series CSV: {args.per_bar_csv} ({len(per_bar_rows)} rows)")


if __name__ == "__main__":
    main()

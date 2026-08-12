"""python -m src.sr_lines.cli TICKER [--preset ...] [--timeframe daily|weekly] [--as-of YYYY-MM-DD] [--out PATH]
python -m src.sr_lines.cli --all [--preset ...] [--timeframe daily|weekly] [--as-of YYYY-MM-DD]

Detects support/resistance lines (horizontal, optionally diagonal via
--diagonals), upserts them into the derived DB, and -- single-ticker only
-- writes a Plotly review chart. `--all` iterates every distinct ticker in
`bars_1d` instead of one named TICKER -- continue-on-error per ticker, with
a pass/fail/skip tally at the end, matching gaps/cli.py's pattern; chart
rendering is skipped entirely under --all (would otherwise write one HTML
file per ticker in the whole universe).
"""

from __future__ import annotations

import argparse
import json

import pandas as pd

from src.data_processing import db
from src.data_processing import resample as resample_mod
from src.market_common import derived_db
from src.sr_lines import data as data_mod
from src.sr_lines import engine
from src.sr_lines import store
from src.sr_lines.config import SRConfig, get_preset
from src.sr_lines.models import DetectionResult
from src.sr_lines.plotting import render_review_chart


def _run_for_ticker(
    raw_conn, derived_conn, ticker: str, sr_config: SRConfig, preset: str, timeframe: str,
    as_of: str | None, strength_floor: float | None = None,
) -> DetectionResult:
    """Runs detection and persists the result. Always records a `runs` row
    when detection actually ran and found data (even if it found zero
    lines) -- a run that legitimately found nothing is still a completed
    run, distinct from one skipped outright for too little data (see the
    `rows_loaded == 0` check, mirroring gaps/cli.py's `skip_reason`)."""
    result = engine.detect(raw_conn, ticker, sr_config, as_of=as_of, strength_floor=strength_floor)
    if result.data_quality.rows_loaded == 0:
        return result

    run_id = derived_db.record_run(
        derived_conn, "sr_lines", ticker, timeframe, as_of,
        json.dumps(sr_config.to_dict()), result.data_quality.rows_dropped, result.data_quality.unreliable,
    )
    store.upsert_lines(derived_conn, result.lines, ticker, timeframe, preset, run_id)
    return result


def main():
    parser = argparse.ArgumentParser(description="Detect support/resistance lines (horizontal, optionally diagonal)")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("ticker", nargs="?", help="Ticker to run detection for")
    target.add_argument("--all", action="store_true", help="Run for every distinct ticker in bars_1d")
    parser.add_argument("--preset", default="medium_term", choices=["medium_term", "long_term"])
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD; default: latest available data")
    parser.add_argument(
        "--out", default=None,
        help="Output HTML path (default: review_<ticker>.html). Single-ticker only.",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--top-n", type=int, default=None, help="Override the preset's top-N line count")
    selection.add_argument(
        "--strength-floor", type=float, default=None,
        help="Return every line scoring at or above this instead of a fixed top-N",
    )
    parser.add_argument(
        "--dedup-threshold", type=float, default=None,
        help="Override how aggressively nearby zones merge (as a fraction of their average "
        "width; default 0.6). Higher merges more -- useful for tuning against clutter of "
        "several close-but-separate zones on a chart.",
    )
    parser.add_argument(
        "--zone-width-atr", type=float, default=None,
        help="Override the initial clustering tolerance (ATR multiple; default 0.4). Higher "
        "produces fewer, wider zones from the start -- the more direct lever than "
        "--dedup-threshold when several pivots that should read as one broad area keep "
        "showing up as separate narrow zones. Also used for diagonal band/inlier tolerance "
        "when --diagonals is given.",
    )
    parser.add_argument(
        "--diagonals", action="store_true",
        help="Also detect diagonal (RANSAC-style, log-price) trendlines, not just horizontal "
        "zones. Off by default so horizontal-only charts stay comparable to earlier runs.",
    )
    parser.add_argument(
        "--timeframe", default="daily", choices=["daily", "weekly"],
        help="Bar resolution. 'weekly' resamples live from daily bars (see "
        "data.load_bars/resample.to_weekly) and rescales the bar-count-denominated config "
        "knobs (fakeout_reclaim_bars, touch_reaction_window_bars, "
        "diagonal_min_pivot_separation_bars, max_diagonal_slope_atr_per_bar) to a first-pass "
        "weekly-equivalent -- not yet empirically calibrated against real charts.",
    )
    args = parser.parse_args()

    if args.out and args.all:
        parser.error("--out requires a single TICKER (not --all)")

    raw_conn, derived_conn = derived_db.bootstrap_cli(store.create_sr_lines_tables)

    preset_name = f"{args.preset}_weekly" if args.timeframe == "weekly" else args.preset
    sr_config = get_preset(preset_name)
    if args.top_n is not None:
        sr_config.top_n = args.top_n
    if args.dedup_threshold is not None:
        sr_config.dedup_overlap_threshold = args.dedup_threshold
    if args.zone_width_atr is not None:
        sr_config.zone_width_atr = args.zone_width_atr
    if args.diagonals:
        sr_config.diagonal_enabled = True

    if args.all:
        tickers = [
            row[0] for row in raw_conn.execute(
                "SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", (db.YFINANCE,)
            ).fetchall()
        ]
        n_success, n_failed, n_empty = 0, 0, 0
        for ticker in tickers:
            try:
                result = _run_for_ticker(
                    raw_conn, derived_conn, ticker, sr_config, args.preset, args.timeframe, args.as_of,
                    strength_floor=args.strength_floor,
                )
            except Exception as exc:  # continue-on-error per ticker, as specced
                n_failed += 1
                print(f"{ticker}: FAILED -- {exc}")
                continue

            if result.data_quality.rows_loaded == 0:
                n_empty += 1
                print(f"{ticker}: SKIPPED -- no data")
                continue

            n_success += 1
            print(f"{ticker}: {len(result.lines)} lines detected")

        print(f"\nDone: {n_success} succeeded, {n_empty} skipped, {n_failed} failed")
        raw_conn.close()
        derived_conn.close()
        return

    result = _run_for_ticker(
        raw_conn, derived_conn, args.ticker, sr_config, args.preset, args.timeframe, args.as_of,
        strength_floor=args.strength_floor,
    )
    detection_bars, _ = data_mod.load_and_validate(raw_conn, args.ticker, sr_config, end=args.as_of)

    if detection_bars.empty:
        print(f"No data for {args.ticker} (source={data_mod.REQUIRED_SOURCE}) in the requested window.")
        raw_conn.close()
        derived_conn.close()
        return

    reference_date = detection_bars.index[-1]

    if args.as_of:
        # Detection only ever sees bars up to as_of (no lookahead) -- but for
        # manually eyeballing "did this zone hold up," the chart itself should
        # keep showing real price action past that cutoff. Same start as the
        # detection window, extended through whatever's latest available.
        # For weekly, the detection window's own start already fell on a
        # calendar Monday (load_bars resampled it that way) -- read daily
        # bars from that same Monday so to_weekly's week buckets line up
        # identically, then resample and validate at daily resolution
        # *before* aggregating, same as load_bars itself does.
        raw = db.read_bars(
            raw_conn, "bars_1d", ticker=args.ticker, source=data_mod.REQUIRED_SOURCE,
            start=detection_bars.index[0].strftime("%Y-%m-%d"),
        )
        if "is_partial" in raw.columns:
            raw = raw[raw["is_partial"] != 1]
        raw = raw[["open", "high", "low", "close", "volume"]]
        display_bars, _ = data_mod.validate_bars(raw, args.ticker, sr_config)
        if sr_config.bar_interval == "1w":
            # as_of=display_bars.index.max(), not wall-clock "now" -- same
            # reasoning as data.load_bars: judging week-closure against real
            # time instead of the data's own latest timestamp can silently
            # treat a week the local DB hasn't fully caught up on yet as
            # closed. See data.py's load_bars for the real PAAS case that
            # caught this.
            as_of = display_bars.index.max() if not display_bars.empty else pd.Timestamp.now()
            weekly = resample_mod.to_weekly(display_bars.assign(is_partial=False), as_of=as_of)
            display_bars = weekly[weekly["is_partial"] != True][  # noqa: E712
                ["open", "high", "low", "close", "volume"]
            ]
    else:
        display_bars = detection_bars

    fig = render_review_chart(display_bars, result, reference_date=reference_date)
    out_path = args.out or f"review_{args.ticker}.html"
    fig.write_html(out_path)
    print(f"{args.ticker}: {len(result.lines)} lines detected. Wrote {out_path}")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

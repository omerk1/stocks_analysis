import argparse

import pandas as pd
from dotenv import load_dotenv

from src.data_processing import db
from src.data_processing import resample as resample_mod
from src.sr_lines import data as data_mod
from src.sr_lines import engine
from src.sr_lines.config import get_preset
from src.sr_lines.plotting import render_review_chart
from src.utils.config_loader import load_config


def main():
    parser = argparse.ArgumentParser(description="Render an S/R line detection review chart")
    parser.add_argument("ticker")
    parser.add_argument("--preset", default="medium_term", choices=["medium_term", "long_term"])
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD; default: latest available data")
    parser.add_argument("--out", default=None, help="Output HTML path (default: review_<ticker>.html)")
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
        "diagonal_min_pivot_separation_bars) to a first-pass weekly-equivalent -- not yet "
        "empirically calibrated against real charts.",
    )
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)

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
    result = engine.detect(conn, args.ticker, sr_config, as_of=args.as_of, strength_floor=args.strength_floor)
    detection_bars, _ = data_mod.load_and_validate(conn, args.ticker, sr_config, end=args.as_of)

    if detection_bars.empty:
        print(f"No data for {args.ticker} (source={data_mod.REQUIRED_SOURCE}) in the requested window.")
        conn.close()
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
            conn, "bars_1d", ticker=args.ticker, source=data_mod.REQUIRED_SOURCE,
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

    conn.close()


if __name__ == "__main__":
    main()

import argparse

from dotenv import load_dotenv

from src.data_processing import db
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
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)

    sr_config = get_preset(args.preset)
    if args.top_n is not None:
        sr_config.top_n = args.top_n
    result = engine.detect(conn, args.ticker, sr_config, as_of=args.as_of, strength_floor=args.strength_floor)
    bars, _ = data_mod.load_and_validate(conn, args.ticker, sr_config, end=args.as_of)

    if bars.empty:
        print(f"No data for {args.ticker} (source={data_mod.REQUIRED_SOURCE}) in the requested window.")
        conn.close()
        return

    fig = render_review_chart(bars, result)
    out_path = args.out or f"review_{args.ticker}.html"
    fig.write_html(out_path)
    print(f"{args.ticker}: {len(result.lines)} lines detected. Wrote {out_path}")

    conn.close()


if __name__ == "__main__":
    main()

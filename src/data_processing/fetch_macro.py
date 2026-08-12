import argparse

from dotenv import load_dotenv

from src.data_processing import db
from src.data_processing.fred_client import CURATED_SERIES, FredClient
from src.utils.config_loader import load_config


def main():
    parser = argparse.ArgumentParser(description="Fetch macro/meta-financial series into SQLite")
    parser.add_argument(
        "--series",
        required=True,
        help='Comma-separated FRED series ids (e.g. "M2SL,DGS10"), or "all" for the curated list',
    )
    parser.add_argument("--start", default=None, help="Start date, YYYY-MM-DD (default: full history)")
    parser.add_argument("--end", default=None, help="End date, YYYY-MM-DD (default: full history)")
    args = parser.parse_args()

    series_ids = list(CURATED_SERIES) if args.series == "all" else [
        s.strip().upper() for s in args.series.split(",")
    ]

    load_dotenv()
    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    client = FredClient()
    for series_id in series_ids:
        values = client.get_series(series_id, start=args.start, end=args.end)
        db.upsert_macro_series(conn, series_id, db.FRED, values)
        print(f"{series_id}: {len(values)} observations stored in {db_path}")

    conn.close()


if __name__ == "__main__":
    main()

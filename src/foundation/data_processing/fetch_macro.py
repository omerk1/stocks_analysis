import argparse

import pandas as pd
from dotenv import load_dotenv

from src.foundation.data_processing import db
from src.foundation.data_processing.fred_client import CURATED_SERIES, SAME_DAY_PUBLISHED_SERIES, FredClient
from src.foundation.utils.config_loader import load_config


def _publication(client: FredClient, series_id: str, values: pd.Series, start, end) -> pd.DataFrame:
    """`published_at`/`first_published_value`, indexed by date, for one
    series -- either FRED's real ALFRED first-release data, or (for
    `SAME_DAY_PUBLISHED_SERIES`, or a series that falls back to the same
    failure mode -- see `FredClient.get_series_first_release`) a same-day
    construction directly from `values`, requiring no second API call.
    """
    if series_id not in SAME_DAY_PUBLISHED_SERIES:
        publication = client.get_series_first_release(series_id, start=start, end=end)
        if not publication.empty:
            return publication
        print(f"{series_id}: first-release data unavailable, falling back to same-day published")
    return pd.DataFrame(
        {"published_at": [d.strftime("%Y-%m-%d") for d in values.index], "first_published_value": values.values},
        index=values.index,
    )


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
        publication = _publication(client, series_id, values, args.start, args.end)
        db.upsert_macro_series(conn, series_id, db.FRED, values, publication=publication)
        print(f"{series_id}: {len(values)} observations stored in {db_path}")

    conn.close()


if __name__ == "__main__":
    main()

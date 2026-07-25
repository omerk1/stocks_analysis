import sqlite3

from dotenv import load_dotenv

from src.data_processing import db
from src.data_processing.polygon_client import PolygonClient
from src.utils.config_loader import load_config


def refresh_ticker_universe(client: PolygonClient, conn: sqlite3.Connection) -> None:
    """(Re)populate the `tickers` reference table from Polygon.

    Polygon is the single source of truth for "which tickers exist" here --
    price-data ingestion for any source (Polygon or yfinance) reads this
    table rather than each maintaining its own ticker list. Pulls both active
    and inactive/delisted common stock so downstream ingestion isn't
    survivorship-biased by construction; whether a given delisted ticker's
    actual price history is still reachable depends on the 2-year historical
    entitlement, separately.
    """
    for active in (True, False):
        tickers = client.list_common_stock_tickers(active=active)
        db.upsert_tickers(conn, tickers)


def main():
    load_dotenv()
    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    client = PolygonClient()
    refresh_ticker_universe(client, conn)

    counts = db.read_tickers(conn).groupby("active").size().to_dict()
    print(f"Ticker universe refreshed: {counts}")

    conn.close()


if __name__ == "__main__":
    main()

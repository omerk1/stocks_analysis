import argparse
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.data_processing.polygon_client import PolygonClient
from src.utils.config_loader import load_config


def fetch_ticker(client: PolygonClient, ticker: str, start: str, end: str, output_dir: Path) -> Path:
    """Fetch daily bars for `ticker` and merge them into output_dir/{ticker}.csv.

    Incremental: existing rows are kept, new dates are appended, and the
    result is de-duplicated by date so re-running with overlapping ranges is safe.
    """
    new_bars = client.get_daily_bars(ticker, start, end)

    output_path = output_dir / f"{ticker}.csv"
    if output_path.exists():
        existing = pd.read_csv(output_path, index_col="date", parse_dates=["date"])
        combined = pd.concat([existing, new_bars])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    else:
        combined = new_bars

    output_dir.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Fetch daily OHLCV bars from Polygon.io")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers, e.g. AAPL,MSFT")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD")
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    output_dir = Path(config.data_paths.raw) / "polygon"

    client = PolygonClient()
    for ticker in args.tickers.split(","):
        ticker = ticker.strip().upper()
        path = fetch_ticker(client, ticker, args.start, args.end, output_dir)
        print(f"{ticker}: saved to {path}")


if __name__ == "__main__":
    main()

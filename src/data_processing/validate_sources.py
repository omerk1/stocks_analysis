import argparse

import pandas as pd

from src.data_processing.polygon_client import PolygonClient
from src.data_processing.yfinance_client import YFinanceClient


def compare_daily_bars(
    ticker: str,
    start: str,
    end: str,
    tolerance: float = 0.01,
    polygon_client: PolygonClient | None = None,
    yfinance_client: YFinanceClient | None = None,
) -> pd.DataFrame:
    """Compare Polygon vs yfinance daily closes for `ticker`.

    Returns only the dates where the two sources disagree by more than
    `tolerance` (relative, default 1%) -- an empty result means everything
    matched within tolerance. Only dates present in both sources are compared;
    a date missing from one source entirely is not flagged here.
    """
    polygon_client = polygon_client or PolygonClient()
    yfinance_client = yfinance_client or YFinanceClient()

    polygon_df = polygon_client.get_daily_bars(ticker, start, end)
    yfinance_df = yfinance_client.get_daily_bars(ticker, start, end)

    merged = polygon_df[["close"]].join(
        yfinance_df[["close"]], lsuffix="_polygon", rsuffix="_yfinance", how="inner"
    )
    merged["pct_diff"] = (
        (merged["close_polygon"] - merged["close_yfinance"]).abs() / merged["close_yfinance"]
    )
    return merged[merged["pct_diff"] > tolerance]


def main():
    parser = argparse.ArgumentParser(description="Compare Polygon vs yfinance daily closes")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--tolerance", type=float, default=0.01)
    args = parser.parse_args()

    discrepancies = compare_daily_bars(args.ticker, args.start, args.end, args.tolerance)
    if discrepancies.empty:
        print(f"{args.ticker}: no discrepancies beyond {args.tolerance:.2%} tolerance")
    else:
        print(discrepancies)


if __name__ == "__main__":
    main()

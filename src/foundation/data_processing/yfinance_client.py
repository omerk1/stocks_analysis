from fractions import Fraction

import pandas as pd
import yfinance as yf

_COLUMN_MAP = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


class YFinanceClient:
    """Secondary data source: cross-checking Polygon and covering lower
    timeframes Polygon's free tier doesn't offer (intraday bars)."""

    def get_daily_bars(self, ticker: str, start, end) -> pd.DataFrame:
        return self._fetch(ticker, start, end, interval="1d", keep_time=False)

    def get_hourly_bars(self, ticker: str, start, end) -> pd.DataFrame:
        """Fetch hourly bars. Yahoo only retains ~730 days of 1h history --
        requesting further back silently returns a truncated range, it does
        not raise."""
        return self._fetch(ticker, start, end, interval="1h", keep_time=True)

    def get_shares_outstanding(self, ticker: str, start, end) -> pd.Series:
        """Real historical share counts (from actual filing dates), not just
        a current snapshot -- confirmed on real AAPL data going back to
        2015, hundreds to 1000+ points per ticker depending on filing
        frequency. This is the only source of shares-outstanding *history*
        this project has access to: Polygon's equivalent (financials/balance
        sheet endpoints) returned NOT_AUTHORIZED on our current plan.

        Deliberately NOT split-adjusted, unlike this project's bars_1d price
        series -- confirmed directly on real AAPL data: the raw count jumps
        ~4x exactly on 2020-08-31, AAPL's real 4-for-1 split date, rather
        than reading as a smooth pre/post-split-adjusted series. A caller
        wanting a real historical market cap (price x shares) must
        reconcile this against bars_1d's own split-adjustment convention
        first -- multiplying the two blindly will be wrong across any split.
        Not attempted here; this method only returns the raw, as-reported
        counts.

        Also deduplicated (keep last) on same-calendar-day entries -- Yahoo's
        underlying data has genuine same-day duplicate rows around
        volatile filing periods (confirmed on the same real AAPL split
        window: 2 of 6 raw rows shared a date with another row, values
        differing by ~2%, most likely a same-day filing revision).
        """
        raw = yf.Ticker(ticker).get_shares_full(start=start, end=end)
        if raw is None or raw.empty:
            return pd.Series(dtype="float64", name="shares_outstanding").rename_axis("date")

        # Usually tz-aware (confirmed on real AAPL data), but not always --
        # confirmed live on several delisted/acquired tickers (e.g. X, XEC,
        # XLNX, YHOO) where yfinance returns a tz-naive index instead.
        # tz_convert requires tz-aware input, so it's only safe to call when
        # there's actually a timezone to convert from.
        idx = raw.index.tz_convert("UTC").tz_localize(None) if raw.index.tz is not None else raw.index
        idx = idx.normalize()
        raw = raw.set_axis(idx)
        raw = raw[~raw.index.duplicated(keep="last")].sort_index()
        raw.index.name = "date"
        raw.name = "shares_outstanding"
        return raw

    def get_sector_info(self, ticker: str) -> dict:
        """GICS-style sector/industry classification from yfinance's `.info`
        -- confirmed live against real tickers (AAPL/JPM/XOM/JNJ) to use a
        fixed 11-sector taxonomy ("Technology", "Financial Services",
        "Energy", "Healthcare", ...) that maps one-to-one onto the 11 SPDR
        sector ETFs (see `relative_strength.config.SECTOR_ETF_MAP`).

        No bulk endpoint -- one call per ticker, same shape as
        `PolygonClient.get_ticker_details`.
        """
        info = yf.Ticker(ticker).get_info()
        return {"ticker": ticker, "sector": info.get("sector"), "industry": info.get("industry")}

    def get_splits(self, ticker: str) -> pd.DataFrame:
        """Full split history, in the same shape as
        `PolygonClient.get_splits` (execution_date, split_from, split_to,
        ratio) so `db.upsert_splits` and every reader treat both sources
        alike. yfinance reports a single multiplier per split (4.0 for a
        4-for-1 forward split, 0.05 for a 1-for-20 reverse split); it's
        turned back into whole from/to factors here.

        Delisted tickers usually come back empty (confirmed on XLNX) --
        stored as a successful zero-row fetch, same as a ticker that never
        split.
        """
        raw = yf.Ticker(ticker).splits
        columns = ["execution_date", "split_from", "split_to", "ratio"]
        if raw is None or raw.empty:
            return pd.DataFrame(columns=columns)

        # Exchange-local midnight (America/New_York) -- drop the tz rather
        # than converting to UTC so the calendar date stays the real one.
        idx = raw.index.tz_localize(None) if raw.index.tz is not None else raw.index
        rows = []
        for date, mult in zip(idx.normalize(), raw.to_numpy()):
            # Real split factors are small-denominator fractions (4/1, 3/2,
            # 1/15), so the nearest such fraction recovers them exactly --
            # plain rounding of 1/0.066667 gives 14.9999, not 15.
            frac = Fraction(float(mult)).limit_denominator(1000)
            split_from, split_to = float(frac.denominator), float(frac.numerator)
            rows.append({
                "execution_date": date, "split_from": split_from,
                "split_to": split_to, "ratio": split_to / split_from,
            })
        df = pd.DataFrame(rows, columns=columns)
        return df.sort_values("execution_date").reset_index(drop=True)

    @staticmethod
    def _fetch(ticker: str, start, end, interval: str, keep_time: bool) -> pd.DataFrame:
        # yfinance's `end` is exclusive (Python-slice style) -- confirmed directly:
        # end="2026-07-21" only returns through 2026-07-20. Polygon's end is
        # inclusive, so without this adjustment the two sources would silently
        # cover different date ranges for the "same" start/end request. Shifting
        # by one day here makes `end` inclusive for every caller of this client.
        end_inclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        raw = yf.Ticker(ticker).history(start=start, end=end_inclusive, interval=interval)
        if raw.empty:
            columns = ["open", "high", "low", "close", "volume"]
            return pd.DataFrame(columns=columns).rename_axis("timestamp")

        df = raw.rename(columns=_COLUMN_MAP)[["open", "high", "low", "close", "volume"]]

        idx = df.index.tz_convert("UTC")
        if not keep_time:
            idx = idx.normalize()
        df.index = idx.tz_localize(None)
        df.index.name = "timestamp"
        return df

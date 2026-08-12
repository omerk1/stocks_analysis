import os

import pandas as pd
import requests

ENV_KEY = "FRED_API_KEY"

_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED's sentinel for "no value published for this date" (e.g. a holiday in a
# daily series, or a not-yet-released period at the edge of history) -- shows
# up as the literal string "." in the observations payload, not a JSON null.
_MISSING_VALUE = "."

# Starting set of macro/meta-financial series -- covers money supply, the Fed
# balance sheet, policy + full Treasury curve, inflation (CPI and the Fed's
# preferred PCE gauge), growth, labor, credit spreads, a dollar index, and the
# S&P 500 level. DTWEXBGS substitutes for the real ICE DXY, which FRED doesn't
# carry for free. Not exhaustive -- a reasonable starting point, easy to
# extend later.
CURATED_SERIES = {
    "M2SL": "M2 money stock",
    "WALCL": "Fed total assets (balance sheet)",
    "DFF": "Effective federal funds rate (daily)",
    "DGS3MO": "3-month Treasury yield",
    "DGS2": "2-year Treasury yield",
    "DGS10": "10-year Treasury yield",
    "T10Y2Y": "10Y-2Y Treasury spread",
    "CPIAUCSL": "CPI, all items, seasonally adjusted",
    "CPILFESL": "Core CPI (ex food & energy)",
    "PCEPI": "PCE price index",
    "PCEPILFE": "Core PCE price index",
    "GDPC1": "Real GDP",
    "UNRATE": "Unemployment rate",
    "ICSA": "Initial jobless claims (weekly)",
    "BAMLH0A0HYM2": "High-yield credit spread (OAS)",
    "DTWEXBGS": "Trade-weighted broad dollar index",
    "SP500": "S&P 500 index level (daily)",
}


class FredClient:
    """Thin wrapper around FRED's REST API for pulling macro/meta-financial
    time series. Free tier: a self-service API key, no cost, generous rate
    limits -- no proactive pacing needed for the small number of series this
    project pulls (contrast PolygonClient's shared RateLimiter, needed there
    for a 5 req/min free-tier ceiling)."""

    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.getenv(ENV_KEY)
        if not api_key:
            raise ValueError(
                f"No FRED API key found. Set the {ENV_KEY} env var or pass api_key explicitly."
            )
        self._api_key = api_key

    def get_series(self, series_id: str, start: str | None = None, end: str | None = None) -> pd.Series:
        """Fetch a single FRED series as a float Series indexed by date.

        `start`/`end` (YYYY-MM-DD) are optional -- omitted, FRED returns the
        series' full available history. Returns the latest-known value per
        date (no vintage/point-in-time selection), and drops dates FRED
        reports as missing rather than coercing "." to a crashing float().
        """
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
        }
        if start is not None:
            params["observation_start"] = start
        if end is not None:
            params["observation_end"] = end

        response = requests.get(_OBSERVATIONS_URL, params=params, timeout=30)
        response.raise_for_status()
        observations = response.json()["observations"]

        dates, values = [], []
        for obs in observations:
            if obs["value"] == _MISSING_VALUE:
                continue
            dates.append(obs["date"])
            values.append(float(obs["value"]))

        index = pd.to_datetime(dates)
        return pd.Series(values, index=index, name=series_id, dtype=float)

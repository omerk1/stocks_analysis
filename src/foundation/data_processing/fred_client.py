import logging
import os

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ENV_KEY = "FRED_API_KEY"

_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED's sentinel for "no value published for this date" (e.g. a holiday in a
# daily series, or a not-yet-released period at the edge of history) -- shows
# up as the literal string "." in the observations payload, not a JSON null.
_MISSING_VALUE = "."

# FRED's own "since the beginning of time" sentinel range for ALFRED vintage
# queries (seen verbatim in its own error messages) -- passed to
# get_series_first_release to request a series' *entire* publication
# history, not just vintages within some bounded window.
_FIRST_RELEASE_REALTIME_START = "1776-07-04"
_FIRST_RELEASE_REALTIME_END = "9999-12-31"

# Series get_series_first_release can't cleanly serve first-publication data
# for -- live-verified against the real API, two distinct failure modes:
# SP500 isn't tracked in ALFRED at all ("The series does not exist in
# ALFRED"); DFF/DGS3MO/DGS2/DGS10/T10Y2Y/VIXCLS get a new ALFRED vintage
# stamped on essentially every business day, so a full-history query exceeds
# FRED's 2000-vintage-date cap for this file type (confirmed: 3099-5102
# vintage dates for these six). Callers should treat these as same-day
# published (published_at = date) instead -- true in practice, not just a
# workaround: these are all daily market-quoted values (Treasury yields, an
# index level, VIX, the Fed funds rate) with no real multi-day revision lag.
SAME_DAY_PUBLISHED_SERIES = {"DFF", "DGS3MO", "DGS2", "DGS10", "T10Y2Y", "VIXCLS", "SP500"}

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
    "VIXCLS": "CBOE Volatility Index (VIX, daily close)",
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

    def get_series_first_release(
        self, series_id: str, start: str | None = None, end: str | None = None
    ) -> pd.DataFrame:
        """Fetch each observation's *first-published* value and the date it
        was first published (FRED's ALFRED vintage data), via
        `output_type=4` ("initial release only"). Distinct from
        `get_series`, which returns today's latest-known/most-revised value
        per date -- this instead answers "what did this data point say, and
        when did anyone actually know it," which a point-in-time-safe join
        (see `market_common.macro.as_of_join`) needs to avoid look-ahead
        (e.g. treating a GDP figure as known on the date it describes,
        rather than ~1-4 months later when it was actually released).

        Not every FRED series supports this cleanly -- see
        `SAME_DAY_PUBLISHED_SERIES`, which callers should check *before*
        calling this at all for those. As a second line of defense (e.g. a
        series creeping past the vintage-date cap over time), a FRED-side
        error response for this request is treated as an expected, not
        exceptional, outcome: logged and returned as an empty DataFrame
        (columns `published_at`/`first_published_value`, no rows) rather
        than raised.
        """
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "output_type": 4,
            "realtime_start": _FIRST_RELEASE_REALTIME_START,
            "realtime_end": _FIRST_RELEASE_REALTIME_END,
        }
        if start is not None:
            params["observation_start"] = start
        if end is not None:
            params["observation_end"] = end

        response = requests.get(_OBSERVATIONS_URL, params=params, timeout=30)
        payload = response.json()

        if "error_code" in payload:
            logger.warning(
                "FRED first-release data unavailable for %s: %s",
                series_id, payload.get("error_message"),
            )
            return pd.DataFrame(columns=["published_at", "first_published_value"])

        response.raise_for_status()

        dates, published_ats, values = [], [], []
        for obs in payload["observations"]:
            if obs["value"] == _MISSING_VALUE:
                continue
            dates.append(obs["date"])
            published_ats.append(obs["realtime_start"])
            values.append(float(obs["value"]))

        index = pd.to_datetime(dates)
        return pd.DataFrame(
            {"published_at": published_ats, "first_published_value": values}, index=index
        )

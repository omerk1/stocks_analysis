import pandas as pd

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume", "is_partial"]


def to_weekly(daily_bars: pd.DataFrame, as_of: pd.Timestamp | str | None = None) -> pd.DataFrame:
    """Resample daily bars (Mon-Fri) into weekly bars, one row per calendar week."""
    return _resample(daily_bars, period_freq="W-SUN", as_of=as_of)


def to_monthly(daily_bars: pd.DataFrame, as_of: pd.Timestamp | str | None = None) -> pd.DataFrame:
    """Resample daily bars into monthly bars, one row per calendar month."""
    return _resample(daily_bars, period_freq="M", as_of=as_of)


def _resample(daily_bars: pd.DataFrame, period_freq: str, as_of) -> pd.DataFrame:
    """Aggregate daily OHLCV bars into `period_freq` periods.

    Design notes (see conversation for the reasoning):
    - Rows are labeled by the period's *nominal start* (the Monday of the week /
      the 1st of the month), not by the last trading day seen so far. Labeling by
      the last-seen day would make an in-progress period's row key shift as new
      days arrive, leaving stale duplicate rows behind instead of being replaced.
    - A period is "closed" (is_partial=False) once `as_of` is strictly after the
      period's last *weekday* on/before its nominal calendar end -- so a week
      ending Sun Jul 26 is treated as closed as of Sat Jul 25, not only once the
      following Monday arrives. This does NOT account for market holidays inside
      the period (e.g. a Thursday early close before a Friday holiday); the
      period is still considered closed based on the calendar, not a trading
      calendar. Detecting holiday gaps would need a market calendar and is out
      of scope for this basic pass.
    - is_partial is also set True if any constituent daily bar is itself partial
      (e.g. today's still-open trading day), regardless of the period's own
      calendar closure.
    - Missing daily bars from a failed/incomplete fetch (as opposed to a real
      non-trading day) are indistinguishable from holidays here -- the resulting
      OHLC will silently be computed from whatever days are present. Validate
      fetch completeness upstream if this matters for your use case.
    """
    if daily_bars.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS).rename_axis("timestamp")

    as_of = pd.Timestamp(as_of).normalize() if as_of is not None else pd.Timestamp.today().normalize()

    df = daily_bars.sort_index()
    periods = df.index.to_period(period_freq)

    rows = []
    for period, group in df.groupby(periods):
        period_start = period.start_time.normalize()
        nominal_end = period.end_time.normalize()
        last_weekday = _last_weekday_on_or_before(nominal_end)
        period_closed = as_of > last_weekday
        is_partial = (not period_closed) or bool(group["is_partial"].any())

        rows.append(
            {
                "timestamp": period_start,
                "open": group["open"].iloc[0],
                "high": group["high"].max(),
                "low": group["low"].min(),
                "close": group["close"].iloc[-1],
                "volume": group["volume"].sum(min_count=1),
                "is_partial": is_partial,
            }
        )

    result = pd.DataFrame(rows).set_index("timestamp").sort_index()
    return result


def _last_weekday_on_or_before(ts: pd.Timestamp) -> pd.Timestamp:
    while ts.weekday() >= 5:  # Saturday=5, Sunday=6
        ts -= pd.Timedelta(days=1)
    return ts

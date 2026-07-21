# Known limitations

Deliberate simplifications in the data pipeline, tracked here so they don't
get lost. Each entry says what's *not* handled and why that was an acceptable
tradeoff for now — not necessarily a to-do.

## No real trading calendar

`src/data_processing/resample.py` (`_resample`, see docstring at the top of that
function) decides whether a week/month is "closed" using pure calendar logic:
the last weekday on/before the period's nominal end. It has no concept of
market holidays.

- A holiday-shortened week (e.g. last trading day is Thursday because Friday
  is a holiday) is treated the same as a normal week — the row just gets
  whatever days are actually present.
- A gap caused by a **missing/failed fetch** looks identical to a real
  non-trading day. If a fetch silently drops days mid-period, the resulting
  weekly/monthly OHLC will be wrong (e.g. open computed from the second day of
  the week instead of the first) with no signal that anything's off.
- Fixing this properly needs an actual market calendar (e.g. `pandas_market_calendars`)
  to know expected trading days per period and flag when the actual count is short.

## `is_partial` is a same-day heuristic, not a market-clock check

`src/data_processing/fetch_data.py` (`mark_partial`) flags a daily bar as
partial if its date is `>= as_of`'s date. It doesn't know the actual market
close time.

- Practical effect: a bar fetched right after today's close is still marked
  partial until the *next* run, when its date is finally `< as_of`. It just
  self-corrects on the next fetch, not immediately.

## Polygon free tier has no intraday data

Only end-of-day (1D) bars are available from Polygon on the free tier
(`src/data_processing/polygon_client.py`), rate-limited to 5 requests/minute.
This is why `bars_1h` is sourced from yfinance instead, and why `bars_4h`
doesn't exist yet at all.

## 4H timeframe not implemented

`bars_1h` exists in the schema (`src/data_processing/db.py`) and is populated
via `YFinanceClient.get_hourly_bars`, but there's no `bars_4h` yet and no
resampling path from 1H -> 4H. Deferred deliberately: unlike daily->weekly/
monthly, bucketing intraday bars into 4H windows needs market-session
awareness (regular trading hours don't divide evenly into 4H blocks, half
days, and daylight-saving transitions on session boundaries), which is a
different and harder problem than the calendar-based weekly/monthly
resampling done today.

## yfinance intraday history is short and silently truncated

`YFinanceClient.get_hourly_bars` requests are capped by Yahoo to roughly the
trailing 730 days of 1h history. Asking for more doesn't raise an error — it
just returns a truncated range starting later than requested.

## Source validation only checks dates present in both sources

`src/data_processing/validate_sources.py` (`compare_daily_bars`) does an inner
join on date before comparing closes. A date missing entirely from one source
is not flagged as a discrepancy — only dates where both sources have data but
disagree beyond tolerance are reported.

## Weekly/monthly bars are recomputed from full history every fetch

`fetch_ticker` (`src/data_processing/fetch_data.py`) reads *all* stored daily
bars for a ticker and re-resamples the whole history into `bars_1w`/`bars_1mo`
on every run, rather than only the periods touched by the newly fetched range.
Correct (a still-open period needs its earlier days re-read anyway) but doesn't
scale — fine at current data volumes, would need to become incremental if
history grows large or fetches become frequent.

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
(`src/data_processing/polygon_client.py`), rate-limited to 5 requests/minute
(confirmed via Polygon's own pricing page and by testing the actual 2-year
historical boundary directly). This is why yfinance is the intended intraday
source, and why `bars_4h` doesn't exist yet at all.

`PolygonClient` paces itself proactively against this limit via
`RateLimiter` (one shared instance per client, since the budget is
account-wide across every endpoint -- grouped-daily, per-ticker aggs, and
reference/tickers pagination all draw from the same bucket). The library's
own retry-on-429 (`backoff_factor=0.1`, well under a second total across 3
attempts) is nowhere near enough on its own for a hard per-minute budget --
relying on it alone reliably produces "too many 429 error responses"
under any sustained load, which is how this was discovered.

`get_grouped_daily_bars` (one call = the whole market for one day) is what
makes a full-market backfill tractable at all under this limit: ~504 trading
days for a 2-year backfill / 5 req/min ≈ 100 minutes for literally every
ticker, versus being completely infeasible per-ticker (~11,500 tickers would
need ~11,500 individual calls). There's no equivalent bulk endpoint on the
yfinance side, though -- see below.

## yfinance bulk ingestion has no documented rate limit to design a pace against

Unlike Polygon, Yahoo doesn't publish a rate limit for yfinance to pace
against -- `bulk_yfinance_ingest.py` batches requests (default 50
tickers/`yf.download()` call) and treats a failing batch as "flag and move
on" rather than assuming a specific safe throughput, but the actual safe
pace at real scale (~11,500 tickers) is genuinely unknown; a small-scale
test (20 tickers in ~3s) doesn't reveal Yahoo's actual blocking threshold
under sustained load. Expect this to need more than one run, and possibly
tuning `--batch-size` down, if blocking is encountered in practice.

`curl_cffi` (browser TLS impersonation, yfinance's own recommended mitigation
for reducing block risk) is pinned to `0.7.4` in `requirements.txt` rather
than yfinance's own recommended `>=0.15` -- newer versions failed to import
on the development machine with a native-extension linking error (`dlopen:
symbol not found '_CFRelease'`), which looks like a macOS-specific
incompatibility rather than a curl_cffi problem in general. Worth retrying a
newer pin on a different machine/OS rather than assuming 0.7.4 is a hard
ceiling everywhere.

## `bars_1h` storage isn't wired up yet

The schema (`src/data_processing/db.py`) reserves a `bars_1h` table, and
`YFinanceClient.get_hourly_bars` returns correctly-shaped data for it, but
`fetch_data.py` only ever fetches daily bars right now -- nothing calls
`get_hourly_bars` and upserts the result. This is a smaller gap than the 4H
timeframe below (no resampling/session-alignment problem, just a missing
fetch path) but still open.

## 4H timeframe not implemented

There's no `bars_4h` table and no resampling path from 1H -> 4H. Deferred
deliberately: unlike daily->weekly/monthly, bucketing intraday bars into 4H
windows needs market-session awareness (regular trading hours don't divide
evenly into 4H blocks, half days, and daylight-saving transitions on session
boundaries), which is a different and harder problem than the calendar-based
weekly/monthly resampling done today.

## yfinance intraday history is short and silently truncated

`YFinanceClient.get_hourly_bars` requests are capped by Yahoo to roughly the
trailing 730 days of 1h history. Asking for more doesn't raise an error — it
just returns a truncated range starting later than requested.

## Source validation only checks dates present in both sources

`src/data_processing/validate_sources.py` (`compare_stored_daily_bars`) does
an inner join on date before comparing closes, over data both sources have
already had fetched and stored (it's a DB query, not a live re-fetch). A date
missing entirely from one source is not flagged as a discrepancy — only dates
where both sources have data but disagree beyond tolerance are reported. In
practice Polygon and yfinance are often a day apart in how current their most
recent bar is, so the most recent day or two commonly falls outside the
overlap and isn't compared at all.

## Delisted tickers in the reference table aren't all actually fetchable

`ticker_universe.py` deliberately includes inactive/delisted common stock
(via `active=False`, with `delisted_utc`) so the ticker universe itself isn't
survivorship-biased. But Polygon's 2-year historical entitlement is separate
from what the reference metadata knows about -- a ticker delisted in 2019
(e.g. Altaba, formerly Yahoo!) shows up in the reference table, but its
actual price bars aren't reachable on this plan; only tickers delisted within
roughly the last 2 years have retrievable history here. `bulk_polygon_ingest.py`
handles this fine on its own (a grouped-daily call for an old date the plan
doesn't cover fails 429/NOT_AUTHORIZED like any other out-of-range date, and
gets flagged like any other failed date) -- it's just not the same as having
true multi-year survivorship-bias-free history, which would need a paid tier.

## Weekly/monthly bars are recomputed from full history every fetch

`fetch_ticker` (`src/data_processing/fetch_data.py`) reads *all* stored daily
bars for a ticker and re-resamples the whole history into `bars_1w`/`bars_1mo`
on every run, rather than only the periods touched by the newly fetched range.
Correct (a still-open period needs its earlier days re-read anyway) but doesn't
scale — confirmed in practice, not just theoretically: `resample_bulk.py` took
~111 seconds for ~5,230 tickers with only *2 days* of stored history each
(one `db.read_bars` + two `db.upsert_bars` calls per ticker, each its own
commit). A full 2-year backfill (~252x more daily rows per ticker to read and
resample) will take meaningfully longer at this step — worth batching commits
or making this incremental if it becomes a bottleneck in practice.

## yfinance's `end` parameter is exclusive, unlike Polygon's

Found by comparing real API responses, not by reading docs: requesting
`end="2026-07-21"` from yfinance only returns bars through **2026-07-20** --
Polygon's `end` is inclusive of that date. Both `YFinanceClient._fetch` and
`bulk_yfinance_ingest.py`'s `_fetch_batch` now shift `end` forward by one day
before calling yfinance, so every caller of either gets the same inclusive-end
semantics as Polygon. Worth remembering if any new yfinance call site gets
added directly (bypassing both of these) -- it would silently reintroduce the
off-by-one.

A related, separately-confirmed gotcha: `yf.download` returns a *plain* frame
when called with a bare ticker string (`yf.download('AAPL', ...)`), but a
MultiIndex-columned frame (columns keyed by ticker) when called with a
**list**, even a list of exactly one ticker (`yf.download(['AAPL'], ...)`).
`bulk_yfinance_ingest.py` always passes a list, so it always gets the
MultiIndex shape -- an earlier version of this code assumed single-item
batches were shaped like the bare-string case and shipped with a mocked test
that "passed" because the mock encoded the same wrong assumption. Caught by
testing against the real API, not by the test suite.

## Polygon and yfinance use different ticker symbols for share classes

Polygon uses `.` for share classes (`BF.A`, `BF.B` -- Brown-Forman's Class
A/B shares); yfinance wants `-` (`BF-A`, `BF-B`) and silently returns nothing
("possibly delisted; no timezone found") for the dotted form -- confirmed
directly against both real APIs. Since Polygon is the ticker universe's
source of truth, a real pull of the reference table turned up **183 tickers
(~3.4% of active common stock)** using the dotted convention; without
translating them, they'd fail *every single run, forever* (a structurally
impossible ticker can never move from "pending" to "success").
`bulk_yfinance_ingest.py`'s `_to_yfinance_symbol` now translates `.` -> `-`
only for the yfinance API call itself -- bars are still stored under the
original Polygon-style ticker, so both sources key the same company under
the same symbol.

This fix is confirmed correct for ordinary share classes, not for every
dotted suffix Polygon uses -- the reference table also has suffixes like
`.U` (units), `.W`/`.Bw` (warrants), and `.T` (seen on some foreign
listings), and a blanket `.` -> `-` replacement hasn't been individually
verified against yfinance's actual symbol for each of those instrument
types. Some of the 183 may still fail for reasons other than the dot itself.

## Ticker metadata has no bulk endpoint and is current-state only

`bulk_ticker_metadata_ingest.py` refreshes `ticker_metadata` (market cap, SIC
industry code/description, shares outstanding, employee count) via Polygon's
`get_ticker_details` -- confirmed this is per-ticker only, with nothing
equivalent to the grouped-daily bulk endpoint bars use. For ~5,300 active
tickers at the same shared 5 req/min budget, a full refresh is on the order
of **hours, not minutes** (vs. ~100 minutes for a full 2-year *bars*
backfill) -- and since it draws from the same account-wide rate limit as
every other `PolygonClient` call, running it at the same time as a bars
backfill just makes both slower, not faster.

It's also scoped to `active=True` tickers only, and each ticker is a single
overwritten row -- a current snapshot, not a history of past values. There's
no point-in-time market cap here: computing what a ticker's market cap *was*
on some past date would need combining historical shares-outstanding (not
tracked over time either) with historical close price, which this table
doesn't attempt.

## Index membership uses free community datasets, not Polygon, despite the "one source of truth" preference

`index_membership.py` tracks point-in-time S&P 500 / Nasdaq-100 constituents
(`index_membership` table) from two free, MIT-licensed, community-maintained
sources instead of Polygon's paid "ETF Global" constituents add-on.

Polygon's option was investigated first and is technically better in one
respect: `get_etf_global_constituents` takes a generic `composite_ticker`
parameter (confirmed via the library's signature, not just docs), so it isn't
S&P-specific -- it would cover any composite with a tracking ETF (SPY, QQQ,
DIA, IWM, ...) from the *same* account already used for everything else here,
with real point-in-time filtering (`effective_date` + range variants). That's
a genuine "one source of truth" story. It costs **$99/month**, though, and
that was the deciding factor -- the free route was chosen deliberately over
that architectural cleanliness.

What "free" actually means here, and the limitations that come with it:

- **Two unrelated sources, not one.** S&P 500 comes from `fja05680/sp500`
  (`sp500_ticker_start_end.csv`, already shaped as ticker/start_date/end_date
  intervals). Nasdaq-100 comes from `nasdaq-100-ticker-history`
  (`jmccarrell/n100tickers`), a git-only package (not on PyPI, pinned to a
  commit SHA in `requirements.txt` for reproducibility) exposing a
  `tickers_as_of(year, month, day)` function plus a `changes` submodule.
  There's no single upstream authority for "which composites a ticker
  belongs to" the way Polygon is for price/reference data -- adding "other
  major composites" later means finding and vetting a *third* source, not
  extending an existing one.
- **Nasdaq-100 coverage starts 2015-01-01.** Before that, `tickers_as_of`
  raises `NotImplementedError` -- there's no data, not an empty result.
- **A real gotcha found while building the Nasdaq-100 reconstruction, not
  assumed from the docs**: `nasdaq_100_ticker_history.changes.changes_before()`
  describes events walking *backward* from `BASELINE_DATE` (2020-01-01), and
  its `additions`/`removals` are relative to that backward walk, not normal
  forward-time semantics. Confirmed directly: the earliest `changes_before()`
  entry lists `EQIX` as an "addition" and `WBA` as a "removal" effective
  2015-03-23, but `tickers_as_of(2015, 1, 1)` -- a date *before* that event --
  already has `EQIX` in and `WBA` out, the opposite of reading those fields
  as a normal forward-time delta. `fetch_nasdaq100_membership` avoids this
  trap entirely by sampling `tickers_as_of` (the library's own ground truth)
  at every distinct change date and diffing consecutive snapshots, rather
  than interpreting `changes_before()`'s additions/removals directly. Anyone
  reaching for that submodule directly for anything else should keep this in
  mind.
- **S&P 500 dataset is Wikipedia-derived and self-admittedly imperfect** for
  its earliest years (per its own README: pre-~2001 coverage may be missing
  some symbols, membership count doesn't stabilize near the nominal 500
  until ~2001) -- acceptable for this project's purposes, not a claim of
  perfect historical accuracy.
- Both sources are point-in-time membership *only* -- no index weighting,
  float-adjusted shares, or anything needed to reconstruct actual index
  levels, just "was ticker X a member on date Y."

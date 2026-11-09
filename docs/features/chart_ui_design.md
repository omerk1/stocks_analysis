# Chart UI — design

Status: steps 1–4 and 6 built (Done #175–#178, #181, #182, #184, #186, 2026-11-09); step 5 waits on
the guidance extraction. Lean first version, wider later.

## One-liner

A local, single-ticker chart page that opens with a few relevant indicators already drawn.
A side menu turns indicator families, or single items, on and off. Earnings results sit on
the chart, each with an arrow to the bar where it happened.

## Why

Every signal module has its own Plotly review chart (`src/signals/*/plotting.py`), one
module per chart, built by a CLI call. Nothing shows them together on one chart, and
nothing picks what is worth looking at today. The UI is a viewer over what the repo already
computes. It doesn't add signals and it makes no claims: "relevant" means close to price
and strong by the module's own score, not "predictive". The modeling scorecards found that
indicators and levels don't improve the picks (`docs/done.md` #155, #172), so the default
selection must not read as advice.

## Scope of the first version

### Chart

- One ticker at a time, typed into a box. The universe is whatever `market_data.sqlite` has.
- **Daily / weekly toggle.** Weekly bars are resampled from daily (week ending Friday, open
  = first open, high = max, low = min, close = last close, volume = sum). Overlays come from
  that timeframe's own stored run. A family with no weekly run is greyed out in the menu
  ("no weekly run") rather than drawn from daily data.
- **Line / OHLC bars / candles toggle.** Volume in a small pane below, on by default.
- Default view: the last 18 months daily, or 5 years weekly. Zoom and pan as usual. Overlays
  are computed for the whole history, so zooming out doesn't refetch.
- Prices on the same basis the signal modules use (`market_common.data`), so lines sit on
  the bars they were computed from.

### Relative strength strip (header)

A one-line strip above the chart, read from `relative_strength` and
`sector_relative_strength` as of the last bar:

- **RS rating** (1–99, `rs_rating`) against the market (SPY) and against the ticker's own
  sector, each with its change over the last 4 weeks (↑/↓).
- The **sector**, its own RS rating against the market, and its rank among the sectors
  (e.g. "Technology · RS 81 · 2nd of 11").
- The **industry** as text only (`ticker_sector.industry`). Industry ranks need a new
  computation (see "Groups and rankings" below).

Each number shows a small "as of" date, so a stale run is visible. The full RS line
(Mansfield) is the pane in the menu, off by default.

### Indicator menu (left side)

Families, each with a family checkbox and a list of its items:

| Family | Items | Drawn as | Strength for ranking |
|---|---|---|---|
| Moving averages | SMA/EMA 20, 50, 100, 200 (weekly: 10, 30, 40) | lines | none, proximity only |
| Support / resistance | `sr_lines` rows | horizontal or diagonal segments | `strength` |
| Fibonacci | `fib_sets` / `fib_levels` | level lines over the swing | none, proximity only |
| Anchored VWAP | `avwap_anchors` | curve from the anchor bar | none, proximity only |
| Gaps / FVG | `gaps`, state from `gaps/relevance.py` | shaded zones until filled | `size_atr` |
| Volume profile | `volume_profiles` | POC / value-area lines (side histogram later) | none, proximity only |
| Chart patterns | `pattern_matches` | outline + label | `confidence` |
| Divergences | `divergences` | segment on price + segment on the oscillator pane | `strength` |
| Market structure | `market_structure_events` | BOS/CHoCH markers | none, recency only |
| Oscillators | RSI, MACD (`market_common.indicators`) | panes below the chart | not ranked, off by default |
| Relative strength | `relative_strength` (Mansfield) | pane below | not ranked, off by default |

- Checking a family shows its top items by the ranking below, not all of them. Each item can
  be picked or unpicked on its own. The family row shows "3 of 41 shown".
- **Caps:** at most 3 items per family by default and 10 overlays on the price pane in
  total. The cap only limits the default selection. Picking by hand can go past it, and
  the menu shows a "12 / 10 — busy" warning instead of blocking.
- Each item's hover shows its source numbers (strength, touches, age, distance from price
  in ATR), so it's clear why it was picked.
- "Reset to defaults" restores the automatic selection.

### Default selection: "relevant now"

The question the sketch left open. Decided: **a combined score of both, weighted towards
proximity.** An item has to be within reach to count at all, and the score mixes how close it
is with how strong it is. The weight and the reach are set after looking at a handful of
tickers with step 2 built, not before.

1. **Alive:** not broken, filled, expired or invalidated as of the last bar (each module's
   own `status` / lifecycle).
2. **In reach:** distance from the last close to the item, in ATR(14), ≤ 3. Zones use the
   nearer edge, lines their value at the last bar. Same idea as the `in_reach` test in
   `gaps/relevance.py`.
3. **Score:** `w × proximity + (1 − w) × strength`, with `w = 0.7` to start. Proximity is
   `1 − distance/reach`. Strength is the module's own score, scaled to 0–1 inside that family
   (percentile among the ticker's alive items). A weighted sum lets a very strong line a bit
   further away beat a weak one right at price. A product would let one weak side zero the
   other. Families with no strength use proximity alone; market structure uses recency
   (bars since the event).
4. Top 3 per family, then the top 10 across families by score. Moving averages count as one
   group: the two closest to price.

A "ranking" control in the menu (proximity ↔ strength slider) can come with step 2, so the
weight is tried on live charts instead of argued about. The thresholds (reach 3 ATR, the
weight, 3 per family, 10 in total) are display settings, kept in one config
object. They aren't tuned against anything and must not be tuned against returns.

`src/models/features/levels.py` already builds point-in-time S/R, AVWAP and gap levels per
ticker and day. Reuse its distance-in-ATR helpers instead of writing a second version.

### Earnings on the chart

- One marker per announcement from `earnings_announcements`, placed on `reaction_date` (the
  first bar that can reflect it). The hover shows `accepted_at` and `timing`
  (before open / after close).
- A **card** for each marker, connected by an arrow to that bar's high (or low, if the bar
  fell). It shows:
  - period (e.g. "Q2 FY2025"), filing date, before/after market;
  - revenue and diluted EPS from `fundamentals`, each with the change vs the same quarter a
    year earlier (there's no analyst consensus, so this isn't a "beat/miss" against
    expectations — label it "vs year-ago");
  - the reaction: gap % at the open and the day's close-to-close %, in ATR as well.
- **Guidance:** a row on the card, empty for now ("guidance: not yet extracted"). It gets
  filled once the guidance fetch and extraction land (`docs/fundamentals/plan.md` step 5).
  Then it shows the items and raised / maintained / lowered, as computed by code, not by the
  model.
- To keep the chart readable, cards start collapsed to a small "E" flag, except the latest
  one. Click a flag to expand its card. There's also an "expand all in view" toggle.

## Out of scope for the first version

- Several tickers, watchlists, screeners, alerts.
- Live or intraday data. The chart ends at the last stored bar.
- Running the signal modules from the UI. It reads what's stored. A family with no stored
  run for the ticker shows "not computed — `python -m src.signals.<name>.cli …`" in the menu.
- Drawing tools, saved layouts, login, deployment.
- Breadth (market-wide, not per ticker).

## Architecture

**Recommendation: Plotly Dash, one local app, Python only.**

- Plotly is already the charting library of every `plotting.py`. Dash adds the menu, the
  toggles and callbacks without a separate frontend build.
- Annotations with arrows (`fig.add_annotation(..., showarrow=True)`) are built in, which is
  exactly the earnings card.
- Alternative if Plotly gets slow with many overlays on 15+ years of daily bars: TradingView
  Lightweight Charts (Apache-2.0) behind a small JSON API. Faster, but a JS frontend to
  maintain. Not worth it until speed is a measured problem.

Layout (repo convention, like `src/signals/<name>/`):

```
src/ui/chart/
  app.py          Dash layout + callbacks; `python -m src.ui.chart.app` serves on localhost
  bars.py         load daily bars, resample to weekly
  overlays.py     one adapter per family: stored rows -> list[Overlay]
  relevance.py    alive / in-reach / score / caps -> default selection
  earnings.py     announcements + fundamentals -> earnings cards
  figure.py       Overlay list + bars + chart type -> plotly Figure (no Dash in here)
  config.py       caps, reach, default MA set, default date span
tests/test_chart_ui_*.py
```

One shared shape per drawable item, so the menu, the ranking and the drawing don't need to
know about families:

```python
@dataclass(frozen=True)
class Overlay:
    family: str            # "sr_lines", "fibonacci", ...
    item_id: str           # stable within the family, for the menu
    label: str             # "Support 182.40 (5 touches)"
    kind: str              # "hline" | "segment" | "zone" | "series" | "marker" | "pane_series"
    geometry: dict         # kind-specific: x0/x1/y0/y1, or a series
    strength: float | None # module's own score, unscaled
    alive: bool
    hover: dict            # source numbers shown on hover
```

- **Read-only** on both databases: open with `mode=ro` (`derived_db.get_connection(...,
  uri=True)`), never write.
- `figure.py` builds a plain `Figure` with no Dash in it, so it can be tested directly
  and reused by a CLI `--html` export.
- Dash goes into `requirements.txt` and the shared venv.

## Look-ahead and the holdout

- The first version shows the chart as of the last stored bar, and the stored signal rows are
  current-state (`gaps/relevance.py` explains why). That's correct for "now" and wrong for
  any earlier date, so the first version has **no as-of date picker**.
- A later as-of replay needs point-in-time state per family (`gaps/relevance.py`,
  `models/features/levels.py`) and has to cut fundamentals at `available_date`.
- The UI is for looking at charts, not for research. The research studies' holdout rules
  (e.g. `CLAUDE.md` invariant 1) apply to analysis, and nothing the UI shows is a result.
  Don't use it to pick parameters or thresholds for a pre-registered test.

## Build steps (small PRs)

1. **Chart:** `bars.py`, `figure.py`, the app with the ticker box, the daily/weekly and
   line/bars/candles toggles, volume, the moving averages, and the RS strip (stored numbers
   only, no new computation). Tests: weekly resample values on a fixture, the figure has the
   expected trace types per chart type, the strip shows "no RS run" when there are no rows.
   **As built (Done #175):**
   - Prices are traded (split-only), the basis the price-level modules use.
   - Weekly bars reuse the shared loader's resample, so there's no `bars.py` copy of it.
   - Moving averages are computed on the displayed closes.
   - A zoom/pan callback refits the y-axes to the visible window.
   - The weekly chart leaves out the last week when the data ends on its Friday (the shared
     resample counts that week as still in progress).
2. **Menu and defaults:** the `Overlay` adapters for S/R, gaps, AVWAP and Fibonacci (the
   families `levels.py` already covers), `relevance.py`, the menu with caps and reset, and the
   proximity ↔ strength slider. Tests: ranking and caps on hand-built overlays, dead items
   never selected by default. Then look at a handful of tickers and set the weight and reach.
   **As built (Done #176):**
   - Every family runs its own detector live on the ticker's bars as of the last bar, cached
     per ticker and timeframe, instead of reading stored rows. `sr_lines` and `fib_sets` are
     empty in the derived database, and the stored gaps and AVWAP rows are only as fresh as
     their last batch run. A daily chart takes 1–3 s, a weekly one 3–8 s (Fibonacci on
     the whole weekly history is most of it). The chart draws first and the menu fills
     in after.
   - S/R uses both of the module's presets (short and long lookback). Gaps are drawn as
     their unfilled part. AVWAP curves are recomputed from the anchor. Each Fibonacci level
     of the module's selected swings is its own item.
   - Alive: S/R not broken (flipped counts), gaps open or partial, AVWAP active, Fibonacci
     swing not invalidated.
   - Within a family, an item that overlaps one already picked, or is within 0.1 ATR of it,
     is the same level and doesn't take a second slot. Examples: a classic gap and an FVG
     over one zone, one S/R level found by both presets, AVWAPs anchored days apart.
   - Ticking a family picks its best 3. With nothing in reach, it picks its 3 nearest alive
     items instead. Each menu item shows its distance in ATR; hover shows the source numbers,
     the strength percentile and the score.
   - Moving the slider re-picks the defaults at the new weight, replacing hand picks. Reset
     also puts the slider back to 0.7.
   - Moving averages stay a fixed default set (step 1), outside the ranking and the cap of
     10. The "two closest" rule in "Default selection" isn't built.
   - Weight and reach stay at 0.7 and 3 ATR. On 10 large caps (daily), 3 ATR gives 3–10
     picks. Names at an all-time high get the fewest, since nothing sits above them.
3. **Earnings cards:** markers, collapsed flags, cards without guidance. Tests: marker lands
   on `reaction_date`, year-ago change, gap %.

   As built (`src/ui/chart/earnings.py`, Done #177):
   - The period label ("Q2 FY2027") comes from the announcements themselves: quarters
     reported in a 10-K end the fiscal years, and a fiscal year is named by the calendar
     year it ends in. Without a 10-K within a year, the card shows only the quarter's end.
   - "Filing date" is the announcement's acceptance (the 8-K, else the 10-Q/10-K), in ET,
     with the timing and the form.
   - EPS is as filed, so it's put on today's share basis (divided by the splits executed
     after its filing) before the year-ago comparison, like the split-adjusted bars.
     Without that, NVDA's 2024 10:1 split reads as −87%. A fourth quarter has no EPS: the
     10-K reports the year, and EPS doesn't add up across quarters.
   - Revenue is compared only when both quarters use the same measure (the
     revenue-growth feature's `REVENUE_FAMILY`). The % is shown only against a positive
     year-ago value; against a loss, the card gives both numbers.
   - The reaction is measured on daily bars, also on the weekly chart: gap and day move vs
     the previous close, in ATR(14) as of the bar before. No gap for news out during the
     session: that day's open came before it. On the weekly chart the flag sits on the bar
     of the reaction week; the week still in progress has no bar and no flag, and the
     latest card with a bar is the one open by default.
   - Revenue and EPS match the announcement's quarter within 7 days (the two tables'
     quarter ends can differ on 52/53-week years; 42 announcements).
   - Clicking a flag opens its card and clicking a card closes it, remembered per ticker.
     "Expand all" opens every card (plotly hides the ones out of view) and ignores clicks. On a weekly chart
     over several years they overlap: zoom in. A checkbox hides the flags altogether.
   - Cards are built for every announcement in about 0.6 s per ticker and cached.
4. **The other families:** patterns, divergences (with the oscillator pane), volume profile,
   market structure, RSI/MACD and relative-strength panes.

   Split into four PRs, each a usable app: 4a the panes, 4b divergences on them, 4c volume
   profile and market structure, 4d chart patterns.

   As built, 4a (`src/ui/chart/panes.py`, Done #178):
   - RSI 14 (30/70 bands), MACD 12/26/9 (line, signal, histogram) and RS vs SPY, as
     panes under the volume pane in that order. Off by default, not ranked.
   - RSI and MACD are computed on the chart's own bars, so they end on its last bar.
   - The RS pane is recomputed with the relative-strength module's own functions instead
     of read from the stored `rs_mansfield`, which is only as fresh as the last RS run (5
     weeks behind at the time). That's the weekly total-return ratio to SPY vs its
     52-week average, in %, on completed weeks; a daily chart carries the last week
     completed before each day, so it steps weekly. It matches the stored values
     exactly (KO, NVDA, AAPL checked). It needs no RS run, only SPY's bars; without
     them the header says so.
   - Every pane's y-axis refits on zoom and pan like the price pane (RSI stays 0–100;
     MACD and RS keep 0 in view; an empty window, e.g. a warmup, gets a neutral range).
     Dragging any pane pans them all. With every pane on, the price pane keeps at least
     half the height.
   - An open earnings card now goes on the side of its bar with more room in the price
     axis, re-decided on every zoom and pan: so it isn't cut off at the top of the
     figure or pushed into the panes below (step 3's review finding, worse with the
     shorter price pane).

   As built, 4b (divergences in the level menu, Done #181):
   - The divergence module's detector runs live like the other families (RSI, MACD
     histogram and OBV; regular and hidden). Each divergence is a line from its first
     price pivot to its second, green bullish / red bearish, dashed when hidden, with a
     short tag ("RSI↑", "MACD↓h"). With the RSI or MACD pane shown, the same divergence
     is also drawn there between the paired indicator values. OBV has no pane, so only
     its price line is drawn. The module stores the indicator pivots' values but not
     their dates (they pair within 3 bars of the price pivots), so the pane line uses
     the price pivots' dates.
   - Alive is the module's own rule: not invalidated (price went past the pair's
     extreme within its 20-bar outcome window). Old divergences stay alive for good, so
     a divergence isn't ranked by distance from price but by recency: in reach when
     confirmed at most `reach_bars` ago (40 daily, about two months; 12 weekly, about a
     quarter), proximity = 1 − age / reach, mixed with the module's strength like the
     other families. The menu shows "12 bars ago" for each, and the family count reads
     "1 of 2 recent" ("3 shown, 0 recent" when older ones are ticked).
   - Divergences on the same second pivot and direction (RSI and MACD on one low) are
     one event and take one default slot. Ticking the family with nothing recent picks
     the 3 latest alive ones, also one per event.
   - The adapter runs the module's own pipeline on the chart's bars (same basis) rather
     than loading them again, so each divergence's age counts the bars it was found on.
   - On 10 large caps, 0–2 divergences per chart are in reach daily and 0–1 weekly, so
     they're picked only when there's a recent one (none on AAPL).
   - The detector adds about 2–3 s per chart. The menu now takes about 3–8 s daily and
     4–17 s weekly; most of the weekly time is gaps, AVWAP and Fibonacci. Running the
     detectors on threads doesn't help (they're CPU-bound Python); separate processes
     would, a later change if the wait gets in the way.

   As built, 4c (volume profile and market structure in the level menu, Done #182):
   - **Volume profile:** each anchored profile (the same anchors as AVWAP) gives three
     lines from its anchor: POC, VAH and VAL. Lines, not a value-area zone: the zone is
     usually wide (NVDA daily: 166–233) with price inside it, so it always ranked first
     and pushed the POC out. The tag names the anchor's month ("POC Jan 25"). No
     strength in the module, so ranked on proximity alone. Alive follows the anchor's
     status, but without the module's stored previous run only anchors that still
     qualify are found, so every line is alive in practice (AVWAP is the same). The
     side histogram is still for later.
   - **Market structure:** each BOS (the trend continuing) or CHoCH (the trend flipping)
     is an event, drawn as a line at the broken pivot's price from the pivot to the bar
     whose close broke it ("CHoCH↓", BOS dashed). No lifecycle, so all are alive and
     ranked by recency alone (the same 40 / 12-bar reach as divergences). The latest
     event's hover says the trend now.
   - Both run on the chart's bars (traded basis), with no second load, through a new
     `detect_on_bars` in each module that its own `detect` now calls too (as AVWAP
     already had), so the chart can't drift from the module. Divergences got the same.
     Market structure uses the module's preset for the timeframe (weekly needs 20
     bars, not 60).
   - On 10 large caps, volume profile has 3–15 lines in reach and gets its 3 picks on
     every chart; market structure 0–2. With them, most charts reach the cap of 10
     (before: 3–10). If the defaults look crowded, volume profile is the first
     candidate to start unticked.
   - Market structure adds 0.5–4 s to the menu, volume profile under 0.3 s: menus now
     take about 2.5–13 s daily and 4–12 s weekly (the spread is mostly machine load).

   As built, 4d (chart patterns in the level menu, Done #184):
   - Each live pattern from the patterns module (pending, or broken out with its target
     neither hit nor given up within the module's horizon) is an event: its pivots
     joined as an outline, its trigger as a dotted line up to the breakout (the
     neckline, a triangle's two sides, a 1-2-3's point 2, a VCP's pivot price), and
     after a breakout its target as a dashed line to the right edge, tagged ("2Bot↑
     target"). Green bullish, red bearish, grey for a pending symmetric triangle that
     has no direction yet.
   - Ranked like the other events, by recency (bars since the breakout, or since the
     last pivot while pending; the same 40 / 12-bar reach) mixed with the module's
     confidence. Patterns that are one structure take one default slot: those ending on
     the same pivot in the same direction (a double top, a head and shoulders and a
     1-2-3 on one peak), and pending ones of one type whose pivots mostly overlap (the
     same pending triangle found from windows a pivot apart, which the module only
     merges once they share a breakout; the module's own overlap rule). The two rules
     don't chain, so unrelated patterns can't be joined through a third. On 10 large
     caps that's 2–10 events from 4–11 patterns daily.
   - The id leaves out the direction, which a triangle only gets at its breakout, so a
     ticked pattern stays ticked when it breaks out (added back only if two matches
     would share an id).
   - The y-axis fits the outline and trigger, while they're in view, but not the
     target: a measured move can sit far from price (NVDA weekly: 100 with price at
     200). The hover gives it.
   - Where each trigger line starts is the patterns module's own rule
     (`plotting.trigger_lines`), shared with its chart. Moving it there fixed a flag's
     channel being drawn back across its pole, and the module's chart now also draws
     a 1-2-3's and a VCP's trigger.
   - The module's `scan_bars` runs on the chart's bars (traded basis) with its preset
     for the timeframe, but only on the last 2000 bars (8 years daily). A live pattern
     is at most 3 × its formation + 252 bars old (formation, up to twice that waiting
     for a breakout, then the target horizon), and the longest typical formation is
     400 bars, so the window leaves room for formations up to ~580 bars (the module
     scores length, it doesn't cap it). It found the same live patterns as the whole
     history on 10 large caps, daily and weekly, in about 0.7 s instead of 2–9 s daily.
     A live pattern starting within 250 bars of the window's first bar may have been
     cut short by it, so then the window is doubled until none does (none of the 20
     charts needed it). That can't catch a pattern the window cut short and the
     scanner found again from a later start; none showed up in the check above.
   - On 10 large caps, 4–11 patterns per chart are live and 0–9 in reach; they get 0–3
     of the 10 default picks. Menu times are unchanged (about 2–12 s).
5. **Guidance on the cards,** once the extraction exists.
6. **Groups and rankings, basic:** a second page with the sector table (below).

   As built (`src/ui/chart/groups.py`, a Groups tab in the app, Done #186):
   - A second tab next to the chart (`--page groups` opens on it): the sectors table on
     the left, the selected sector's members on the right. Click a sector for its
     members, and a member to open its chart on the Chart tab. Both tables sort by any
     column. RS is shaded green to red, changes and distances from the averages are
     green or red, the breadth shares are drawn as bars, and a stock within 5% of its
     52-week high is green.
   - **One date for the whole page:** the latest date in the 7 days (both ends
     included) before the last rated date on which the most sectors are rated. It's
     one rule (`rs.rank_date`) shared with the strip's sector rank, so the two agree.
     Membership, ratings and the price columns are all as of that date. The header
     says when the bars run further (today: page 2026-09-30, bars to 2026-11-06,
     until relative strength is rerun), and **Reload** rebuilds the page after a rerun
     (a failed reload keeps the previous page and says why).
   - A sector with members but no rating that day is listed last, unranked, so its
     members don't drop off the page.
   - **Sectors:** rank and rating of the sector ETF against SPY, the change in rank
     over 4 and 13 weeks (on each earlier date's own rank date; blank for a sector
     not ranked then), the share of members above their 50- and 200-day averages
     (the hover gives how many members it counts), and the member count.
   - **Members:** rating against the market and its 4-week change, which index the
     rating is ranked within ("rated in": the S&P 500 or Nasdaq-100 run, whichever
     wrote the row last, so about 97 Nasdaq-100 names are ranked against Nasdaq-100
     peers only; the strip reads the same rows), distance from the 52-week high
     (daily highs), and the last close against the 50- and 200-day averages.
   - **Membership** is point-in-time, S&P 500 and Nasdaq-100 together, sectors from
     `ticker_sector`. A ticker that left both in the 91 days before the page date
     stays listed in grey after the members, with its last values; it isn't counted
     in the member count or breadth. It's "delisted" only when the tickers table marks
     it inactive (today's flag, not point-in-time) and it has no bar on the page date;
     otherwise "left the index", saying when its bars end or that it has none. A member
     without a bar on the page date, or whose rating is older than it, says so; the
     former isn't in the breadth. Members without a sector are listed in the header
     (today: FISV).
   - **Prices** are on the chart's basis (traded), read in bulk per source and not
     validated bar by bar. A ticker with no yfinance bars is read from Tiingo (ARM,
     ASML, PDD, delisted members); the Chart tab still reads yfinance only, so
     clicking one of those shows "No bars". A 50/200-day average or 52-week high
     needs its full window of bars, else it's blank and not counted.
   - Built the first time the tab opens (about 4–7 s), then cached until Reload or a
     restart. Nothing is stored. `dash_table.DataTable` is deprecated in Dash 4 in
     favour of dash-ag-grid; it still works, and swapping it is a later change.

Each step is a usable app on its own.

## Groups and rankings

A TradingView / IBD-style page next to the chart: which groups lead, and which stocks lead
inside them. Click a row to open the chart.

**Basic (step 6):**

- **Sectors table:** every sector with its RS rating against the market, its rank, the
  change in rank over 4 and 13 weeks, the share of its members above their 50- and 200-day
  averages, and the member count. All of it from `sector_relative_strength` and the price
  data; nothing new is stored.
- **Members of a sector:** its tickers sorted by RS rating, with the rating, the 4-week
  change, the distance from the 52-week high, and price vs the 50/200-day averages.
- Membership is point-in-time (`db.read_index_membership`), so a delisted ticker shows as
  delisted instead of silently disappearing.

**Later:**

- **Industry groups:** a rating per `ticker_sector.industry`, e.g. the median member RS
  rating, ranked like the sectors. Needs a small new computation and a minimum member count
  (an industry with 2 tickers has a noisy rank), and a stored table if it gets slow.
- **Rank history:** a small chart of a group's rank over time, to see rotation (a group
  climbing from 40th to 5th).
- **Leaders list:** across the universe, tickers with a high RS rating in a top-ranked group.
  It's a screen, not a signal. Nothing here has been tested as one.

## More ambitious directions

Not planned, written down so the first version doesn't close them off. The `Overlay`
shape, the read-only adapters and `figure.py` with no Dash in it are what keep them open.

- **As-of replay:** a date slider that redraws everything point-in-time, to see what the
  chart looked like on a past day, with the next N bars hidden or revealed. Same blind
  chart idea as the strategy agent's grounding step (`docs/strategy-agent/idea.md`).
  Needs point-in-time state for every family, not just gaps and levels.
- **Practice and journaling on top of replay:** hide the future, mark what you'd do, reveal,
  and keep a log of your calls. A personal record of how your own reads turn out.
- **Screener:** filter the universe by any stored state ("within 1 ATR of a strong
  support, RS above 80, sector in the top 3") and page through the matching charts. The
  groups page is its first, narrow version.
- **Confluence highlight:** shade price bands where items from several families stack within
  1 ATR. It's the level stack the strategy agent's next finder builds
  (`docs/backlog.md`, LLM section).
- **Model picks:** open the chart from the combined model's top-k list for a date, with the
  pick's features in the side panel.
- **Strategy agent in the UI:** type an idea, answer its questions in a side panel, and see
  the matching events and near-misses drawn on the chart, then the exploratory look. Today
  it saves static charts.
- **Ask the docs / explain this chart:** a panel that sends "what does this line mean?" to
  the research-docs `ask` command with the item's family, or asks for a plain-language
  summary of what's on the chart. Text only, nothing feeds back into a test.
- **Alerts:** notify when price comes within reach of a selected item, or when a group's
  rank jumps. Needs a daily data refresh first.
- **Multi-chart layouts:** a ticker against its sector ETF and SPY, or a grid of a group's
  members, with shared crosshair.
- **Hosted version:** if it's ever used by more than you. Then the Lightweight Charts
  frontend and a proper API become worth it.
- Smaller ones: volume profile as a side histogram, a watchlist, saved layouts, export the
  current view to HTML/PNG.

## Decided (2026-11-06)

- **Local only** for now.
- **Ranking:** a combined score, weighted towards proximity. The weight and reach get set
  after looking at a handful of tickers with step 2 built.
- **Earnings cards:** revenue, EPS and the reaction to start. Margins and more fields later.
- **RS:** the strip goes into step 1, and the groups page with the sector table is step 6.
  Industry groups and the bigger directions come later.


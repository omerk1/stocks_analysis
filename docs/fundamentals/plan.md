# Company financials: earnings, fundamentals, guidance — plan

Status (2026-10-15): steps 1 (earnings dates), 2 (fundamentals table) and 3 (features,
valuation included) built, see their "As built" notes; steps 4–5 not started. The order and scope below are a starting point to
revisit after each step, not commitments.

## One-liner

Bring company financials into the database: when each company reported results,
what it reported, and what it said about the future. All of it point-in-time, so the
model and the research can use it without look-ahead.

## Why

- **Earnings dates are the largest known gap for the model.** An earnings gap jumps
  straight through both barriers of a triple-barrier label, and today nothing can flag
  "earnings inside the horizon" (`docs/modeling/IDEAS.md`, "Earnings dates" in §3 and §7).
- **The model only sees prices.** Growth, surprise and valuation are an independent
  source of information: the classic academic effects (post-earnings drift, value,
  quality) come from here, not from charts.
- **The raw data is already on disk and nearly unused.** `data/raw/sec/submissions.zip`
  (~1.6 GB, every filer's filing index) and `data/raw/sec/companyfacts.zip` (~1.4 GB,
  every XBRL fact). Today only share counts are read from them (Done #60).

## Ground rules

- **Point-in-time by filing time.** Every value is available only from its EDGAR
  acceptance timestamp onward. A filing accepted after the close is usable at the
  next day's open, never the same bar.
- **First-reported values, not restated ones.** Companies revise past numbers in later
  filings; using the revised value is look-ahead. Keep each value as it was first filed,
  and keep later revisions as separate rows if needed.
- **Delisted companies stay in.** EDGAR covers them; drop none.
- **Holdout and trial rules from the modeling thread apply** to anything that reaches a
  model or a test (`docs/modeling/VALIDATION_HARNESS.md`).

## Data sources

| What | Source | Point-in-time | Notes |
|---|---|---|---|
| Earnings dates | `submissions.zip`: 8-K filings with item 2.02 (results of operations) | yes, acceptance time | local, free; covers delisted filers |
| Reported financials | `companyfacts.zip`: XBRL facts (revenue, EPS, margins, cash, debt, ...) | yes, `filed` date per fact | ~2009–2011 onward (XBRL mandatory for all filers by 2011) |
| Guidance | 8-K item 2.02 exhibit 99.1 (the press release), item 7.01 updates | yes, acceptance time | free text, must be fetched from EDGAR and extracted (step 5) |
| Analyst consensus | none free | — | so "surprise" is measured against the company's own history |

## Steps

Each step is one small PR, useful on its own. Steps 1–3 are pure data work; only step 4
touches research or the model.

### 1. Earnings dates

- Local-only ingest from `submissions.zip`, in the style of `bulk_sec_shares_ingest.py`:
  8-K filings with item 2.02 → table of (CIK, ticker, acceptance time, accession number).
- Classify timing: before the open / during the session / after the close, from the
  acceptance time. Derive the first tradable bar.
- Ticker mapping via `db.verified_cik(ticker)` (the existing rule for SEC joins).
- Checks: coverage per index member per year (expect ~4 per year), spot-check a sample
  against known announcement dates, compare the next-day gap size on earnings days vs
  other days.
- **Payoff right away:** an "earnings inside the horizon" flag for the model, and a
  measurement of how much barrier noise comes from earnings gaps.

**As built (2026-10-14):** `sec_earnings.py` + `bulk_sec_earnings_ingest.py`, table
`earnings_announcements`. Two changes from the outline above, both found in the data:

- **Anchored on the quarterly report, not on every item 2.02 8-K.** Banks and insurers
  also file item 2.02 for mid-quarter conference presentations (PNC: 8–16 a year). So
  each row is one 10-Q/10-K period, and its announcement is the first item 2.02 8-K
  between the period end and the report's filing day, falling back to the report itself
  (flagged in `source`) when there is none. This also answers the 10-Q/10-K fallback
  question below.
- **Predecessor CIKs.** A holding-company reorganisation moves a company to a new CIK
  (Alphabet, Disney, Cigna, BlackRock, Exxon...), and SEC's ticker file gives only
  today's. A hand-checked map (`PREDECESSOR_CIKS`) adds the earlier history.

Not covered: foreign filers (20-F/6-K, no 10-Q: Baidu, JD, ASML...) and delisted members
without a verified CIK, the same gap the share counts and sectors have.

**Look-ahead warning for whoever builds the flag:** a realized announcement date is
future information on any day before it. A model feature must use the *expected* next
date as known on the day (e.g. the same quarter last year + one year, or the last
reaction date + the company's usual spacing); realized dates are for labels and
diagnostics only.

### 2. Fundamentals table

- Quarterly and annual facts from `companyfacts.zip`: revenue, EPS (basic and diluted),
  gross and operating income, net income, operating cash flow, cash, total debt,
  equity.
- Stored as-of the filed date, first-reported value kept.
- **Most of the work is tag normalization:** the same concept appears under several XBRL
  tags (e.g. several revenue tags) that vary across companies and years. Keep an explicit
  mapping table with its own coverage report.
- Derive quarterly values where only year-to-date or annual figures are filed
  (Q4 = annual − 9-month YTD).
- Checks: coverage per member per quarter, hand-check a handful of companies against
  their filings.

**As built (2026-10-14):** `sec_fundamentals.py` + `bulk_sec_fundamentals_ingest.py`, table
`fundamentals`: one long table, one row per (ticker, concept, period type, period end), with
the period type quarter, fiscal year, or instant (balance-sheet date). Same universe and
ticker-to-CIK rules as step 1. Choices and what the data forced:

- **Concepts:** revenue, gross profit, operating income, net income, EPS basic and diluted,
  operating cash flow, cash, equity, and debt as two concepts: `long_term_debt` (current
  maturities included) and `long_term_debt_noncurrent`. These are not interchangeable and
  there's no reliable "total debt" tag. Tags and their order are in `sec_fundamentals.CONCEPTS`.
- **First-reported value per period,** across all of the concept's tags: the earliest filing
  wins. Within one filing, tag order breaks ties, except for revenue, where the largest value
  wins. Some filers put a partial figure under `Revenues` next to the full one (Conagra
  FY2014: $2.2B vs $17.7B).
- **When a value is known:** acceptance time from `submissions.zip`, not the facts file's
  filing date. `available_date` is the first session whose close may use the value. It is
  usually days after the press release, because the XBRL comes with the 10-Q/10-K: median
  6 calendar days after the earnings reaction date, 90th percentile 26.
- **Derived quarters:** a quarter missing as a three-month value is the difference of two
  year-to-date values with the same start and tag (`derived` = 1). This covers 73% of
  operating cash flow quarters and 8–15% of income items, mostly fourth quarters. EPS is
  never derived.
- **XBRL errors handled:** a fact whose period ends after its own filing (REG's 10-K of
  2012-02-29 reporting a quarter to 2012-03-31) is dropped. So is a "quarter" equal to the
  same filing's full year (Oracle tags full-year revenue as Q4).
- **Predecessor CIKs:** a predecessor's reports count when they were filed before the
  successor's first 10-Q/10-K. So Google's own 2014 10-K is used, not Alphabet's 2016
  comparative, and Apache's post-2021 subsidiary reports are not.

Checks (`--check`, run on 2026-10-14):

- **Coverage of step 1's company periods, 2010–2021:**
  - net income, operating cash flow, cash, equity: 96–100%;
  - revenue: 88–91% before 2017, 96–98% after. Banks without a revenue tag are uncovered;
  - EPS: ~91%, falling to 76% in 2021 once 10-Ks stopped carrying quarterly data, and EPS
    is never derived;
  - operating income: 77%; gross profit: 46% (many companies don't report it);
  - long-term debt: 22–50% (current maturities included) or 56–71% (noncurrent).
- **Four quarters vs the fiscal year:** they add up within 1% for 94% (revenue) to 99%
  (operating cash flow) of fiscal years. Most misses are expected, not bugs: quarters as
  first reported vs a year recast after a spin-off or sale (Arconic 2016, SAIC 2014,
  Delphi 2017, McGraw-Hill 2012). About 1% are more than 20% off.
- **Hand checks against the filings:** Apple, Microsoft (June fiscal year), JPMorgan (derived
  Q4), Exxon and Google (predecessor CIKs), Walmart.

Known problems, left for step 3 to handle:

- **Per-share values are as filed:** they jump at splits (Apple Q3→Q4 FY2020: $2.58, then
  $0.73 after the 4:1 split) and carry the filer's scale errors. About 0.15% of EPS values
  are off by 10^4–10^9: BBWI 2010–2015, WMT Q4 FY2020, BRO. Features must split-adjust EPS
  and sanity-check it, or use net income per share from the share-count table.
- **Tags can still mix across periods** (a narrower tag in one filing, the full one in the
  next). `tag` is stored, so growth features can require the same tag a year earlier.
- **In ~0.1% of quarters the 10-Q was accepted 1–3 days before the press-release 8-K.**
  There the 10-Q was the first public report, so step 1's date is slightly late. The same
  happens in two reorganisation quarters (Eaton Q3 2012, ICE Q2 2013): step 1 takes the
  successor's report, but the predecessor's came out up to two weeks earlier.

### 3. Features

Simple, well-known ones only, all computed point-in-time:

- Growth: revenue and EPS, year-over-year (same quarter last year).
- Earnings surprise against the company's own history: standardized unexpected earnings
  (change vs the same quarter last year, scaled by the trailing volatility of that change).
- Valuation: P/E and P/S, using the market cap already computed from SEC share counts.
- Quality: margins and their trend, debt to equity.
- Registered in the model's feature registry like any other feature.

**As built (2026-10-14), part one (valuation is part two, below):** `src/models/features/fundamentals.py`,
registered as group `fundamentals` (prior null: untested here). Seven columns. Plain
quarter-over-quarter growth is left out on purpose (it mostly measures seasonality;
acceleration replaces it), and so is an EPS surprise: a SUE is a ratio, so on EPS it equals
the net-income one up to share-count changes (corr 0.985 on 20 large caps), while as-filed
EPS needs split adjustment, a derived Q4 and scale-error cleaning that kept producing edge
cases (tried and dropped 2026-10-14). Buybacks/dilution belong in a share-count-change feature.

| Column | What it is |
|---|---|
| `days_since_earnings` | business days since the last earnings reaction date |
| `days_to_earnings_expected` | business days to the *expected* next one: the same quarter's reaction a year earlier + 52 weeks, 0 when overdue. Never the realized date |
| `sue_net_income` (+ rank) | the surprise against the company's own history: net income minus the same quarter a year earlier, over the standard deviation of the previous 8 such changes (at least 4). Net income, not EPS: see above for why |
| `rev_growth_accel` | this quarter's YoY revenue growth minus the previous quarter's: whether growth is speeding up. Stands in for quarter-over-quarter growth, which mostly measures seasonality |
| `rev_growth_yoy` (+ rank) | revenue vs the same quarter a year earlier; only when both measure the same thing: the same tag, or two total-revenue tags, since ASC 606 moved nearly every filer between them in 2018 |
| `net_margin_ttm` | trailing four quarters' net income over their revenue |
| `debt_to_equity` | long-term debt (total, else noncurrent) over equity; NaN for non-positive equity or no debt tag |

How point-in-time is enforced:

- **When a value counts:** from its `available_date` (the reaction date, for the earnings
  columns).
- **Every input counts:** a feature's value counts only once *all* its inputs are known,
  including the year-ago quarter and the window's quarters. A quarter whose own value isn't
  known yet produces nothing.
- **Late reports are ignored:** a late report of an old quarter (or a late earnings
  announcement for an old period) is dropped before anything is computed, so it can't
  change, after the fact, which quarter counted as "a year earlier".
- **Values go stale:** a quarter's value is NaN once the quarter ended more than 200 days
  before.
- **Leakage gate:** it gets a `future_filings` perturbation that rewrites every filing after
  the cut: values, deleted rows, moved reaction dates, and a late report of a mid-history
  period for both tables. It also gets a canary that reads net income by period end
  instead of filing date.
  - **Straddling quarters:** the synthetic filings use December, January and February
    fiscal years, so some quarters end before the cut and are filed after it. That's the
    case a period-end leak gets wrong, and a test plants such a leak and checks the gate
    catches it.
  - **Two leaks caught in the first version, both fixed:** a late report changed which
    quarter matched as "a year earlier"; and a quarter with revenue filed but net income
    not yet filed counted as known from its inputs' dates.
  - **Passes** on synthetic data (3 seeds) and on 20 real tickers.

Coverage on S&P 500 member rows (150-ticker sample, 81 with bars in the window):
- earnings timing: 94–100%;
- SUE: 90–99% from 2012 (it needs three years of quarters, so 2010–2011 are thin);
- revenue growth: 87–94%;
- net margin: 90–95%;
- debt to equity: 70–78%.

**As built (2026-10-15), part two, valuation:** `src/models/features/valuation.py`, its own
panel source on the traded basis, same group and prior. Three ranked columns:

| Column | What it is |
|---|---|
| `earnings_yield` (+ rank) | trailing four quarters' net income over market cap (E/P) |
| `sales_yield` (+ rank) | trailing four quarters' revenue over market cap (S/P) |
| `book_to_market` (+ rank) | equity at the latest balance-sheet date over market cap; NaN for non-positive equity |

- **Yields, not P/E and P/S:** a P/E is undefined at zero earnings and flips from the most
  expensive end to the cheapest as earnings cross zero; E/P runs through zero, so a loss
  maker ranks below every profitable company instead of dropping out. Book-to-market is
  added because it is the classic value measure and the equity is already loaded.
- **Market cap = the price that traded × the share count known that day.** The traded-basis
  close is split-adjusted, so it is multiplied back by the splits after the day; the two
  cancel, which the gate's `future_split` checks (a test plants an adjusted price level and
  the gate catches it). A count is carried across splits since its filing date, and a
  filing that still reports the pre-split count is bridged, so AAPL's 2014 split leaves the
  cap continuous.
- **Share counts:** usable from the session after their date (the date has no time, so the
  filing may come after the close; a test plants a same-day use and the gate's
  `future_filings`, which now rewrites counts from the cut on, catches it). Stale after 200
  days. SEC EDGAR first; yfinance only on a date where SEC has none from the previous 200
  days. That is decided from the past only, and it restores 76 tickers whose SEC series
  stops early (multi-class issuers: V, MA, CMCSA, F, NKE). Scale errors (~1e3/1e6 off) and
  placeholders are dropped at load (`share_counts.drop_scale_runs`, SEC judged against
  yfinance as at ingest). That cleaning judges the whole series with hindsight, and the gate
  can't see it (it perturbs counts after loading). It's accepted as a data fix like the SEC
  ingest's own.
- **Checks:** the gate passes on synthetic data (3 seeds) and on 20 real tickers. Values on
  2019-12-31: P/E AAPL 23.6, MSFT 29.3, JPM 12.5, AMZN 80.7. The largest day-to-day jumps are
  on earnings days. Medians on S&P member rows: E/P 0.05, S/P 0.56, B/M 0.34.
- **Coverage on S&P 500 member rows** (the same 150-ticker sample): E/P 81–95% from 2012,
  S/P 76–89%, B/M 79–87%; 2010–2011 are thinner (trailing twelve months need four XBRL
  quarters).
  Gaps: multi-class issuers before yfinance's counts start (~late 2015), and filers whose
  revenue tag isn't read (XOM).
- **Known limit:** the share count is the company's, so each class of a multi-class
  company carries the whole company's cap (GOOG and GOOGL, as in cap-weighted breadth).

**As built (2026-10-15), part three, share-count change:** one more ranked column in
`valuation.py`, same group and prior. It covers buybacks and dilution, the part of an EPS
surprise that the net-income one misses.

| Column | What it is |
|---|---|
| `share_change_yoy` (+ rank) | log of the latest known share count over the count dated a year before it (the nearest within ±30 days); positive is dilution, negative buybacks |

- **A year between two counts, not "the count known a year before t":** both counts are
  then a fixed year apart (an annual rate, like `rev_growth_yoy`), and the value moves only
  when a new count lands. NaN when the latest count is stale (200 days) or nothing is dated
  within ±30 days of a year before it.
- **Log, not percent:** halving and doubling are equally large, and a stock-funded merger
  that multiplies the count doesn't swamp the scale. It is also the usual net-issuance
  definition (Pontiff and Woodgate).
- **Mergers and spin-offs stay in:** issuing stock to buy a company is dilution, and a
  spin-off leaves the parent's count alone.
- **Splits:** the vendors' split tables also hold spin-offs' price factors (EBAY 2.376 for
  PayPal, NI, YUM, HPE), which leave the count alone. Dividing every count by its splits
  turned those into fake buybacks of 40–65%. A split between the two counts is therefore
  taken out only where it explains their change better than no split does. That also
  handles a filing, on either side, that still reports the pre-split count (no bridge
  needed; a split up to 120 days before the year-ago count is judged too, if that count is
  within 20% of the last pre-split one). It uses only splits executed by the later count's
  date.
- **Same source:** both counts come from SEC, or both from yfinance. For multi-class
  issuers SEC can carry one class and yfinance all of them, so a change across the
  hand-off was an artifact (CMCSA +14% in 2016, MA +12% in 2010). After a hand-off the
  column is NaN for a year. **Limits:** a real change about half a split's
  size is misread (±20% across a 3-for-2); a vendor factor that merges a reverse split with
  a spin-off leaves a residual (MSI 2011: −41%); two splits within the year are judged one
  at a time, so one can take the other's ratio; a reused symbol compares two companies
  (FOX/FOXA 2019–2020: −66%).
- **Leakage gate:** passes on synthetic data (3 seeds) and on the 20 real tickers. Two tests
  plant leaks and check the gate catches them: a count used on its filing date
  (`future_filings`), and a change mixing two split bases, the latest count on day t's
  basis and the year-ago one on the data's final basis (`future_split`).
  - The real-ticker run also found a leak in `debt_to_equity`, now fixed. For IP's
    2018-12-31 balance sheet, total debt was first reported as a comparative in the next
    year's 10-K. It replaced the noncurrent figure known since 2019-02-21, so a filing after
    t decided what counted on t.
- **Checks (2010–2021):**
  - Buybacks: AAPL −4% to −8% a year from 2014, ORCL to −16% (2019), AZO −5% to −12%.
  - Dilution: AAL +115% (US Airways, 2014), BMY +38% (Celgene), CCL +62% (2021 raises),
    TSLA +23% (SolarCity).
  - On S&P member rows: median −0.7% a year; 1st percentile −14%, 99th +45% (stock
    mergers). 43–56% of rows show net buybacks over 1% (2011–2020), 14–20% dilution over 1%.
  - The largest values are real issuance: AIG's 2011 recapitalisation, JCI–Tyco, LUMN's
    acquisitions, the 2021 cruise-line raises.
- **Coverage on S&P 500 member rows** (all 643 members with bars): 23% in 2010 (it needs a
  year of counts, and SEC's start in 2009), 63–78% 2011–2016, 81–85% 2017–2019, 90–92%
  2020–2021. The gaps come from the share-count table: 122 members never get a value, many
  with no count at all (EA, K, HOLX, AVB).
- **Found, not fixed (backlog):** the same spin-off factors inflate the market cap.
  `market_caps` carries a count across them and bridges the filings after them as stale,
  so EBAY's cap reads 2.4× from mid-2015 to late 2017 and NI's 2.5× from 2015 to 2019.

### 4. Research questions

Run under the usual protocol (matched control, effective N, costs, three-way verdict),
pre-registered before running:

- **Post-earnings drift:** after a large positive or negative surprise, does the stock
  keep drifting in the same direction, beyond what price momentum alone predicts?
- **Combined model:** does adding the step-3 features to the combined model improve top-k
  R/R after costs? Judged on the existing scorecard, like any other feature set.
- **Earnings as risk:** does excluding or flagging setups with earnings inside the horizon
  change realized R/R?

### 5. Guidance (later, after a feasibility probe)

Guidance is not in XBRL; it lives in the earnings press release (exhibit 99.1 of the
item 2.02 8-K) and in mid-quarter updates (item 7.01), and on earnings calls (not on
EDGAR).

- **Feasibility probe first:** fetch ~50 press releases, hand-label the guidance in them
  (present or not, metric, period, range), and see how often it's there and how well an
  extraction prompt recovers it.
- **If it holds up:** fetch the press releases for the universe (~25–30k for
  S&P 500 + Nasdaq-100 since 2010; EDGAR allows ~10 requests/s, so hours, not days)
  and extract guidance into a table.
- **The useful signal without consensus:** raised / maintained / lowered relative to the
  company's own previous guidance.
- **Conflict to resolve before any of this enters a test:** the LLM track's ground rule
  says LLM output never enters the backtested path
  (`docs/ideation/llm_agentic_workflows.md`, "Ground rule"). Extraction would need an
  explicit, documented exception: a frozen prompt version, cached outputs, and accuracy
  measured against the hand-labeled set before any backtest trusts it.
- **Paid alternatives, not checked yet:** structured guidance datasets exist (LSEG I/B/E/S,
  FactSet, S&P Capital IQ at institutional prices; Benzinga at retail prices, possibly via
  Polygon as an add-on). Pricing, history depth and point-in-time quality unverified.

## Known limits

- No analyst consensus, so surprise is the weaker own-history version.
- XBRL history starts ~2009–2011, which fits the modeling window but not earlier studies.
- XBRL tagging is inconsistent across companies and years; coverage will be below 100%
  and must be reported, not assumed.
- Earnings call content (much of the real guidance) is out of reach for free.

## Open questions

- ~~Table layout: one long facts table (ticker, concept, period, filed, value) or wide
  per-quarter rows?~~ Long (step 2, "As built"); features pivot what they need.
- ~~Does step 1 also pick up 10-Q/10-K filing dates as a fallback when no item 2.02 8-K
  exists?~~ Yes, flagged in `source` (step 1, "As built").
- ~~Universe: S&P 500 + Nasdaq-100 first (the modeling universe), or everything EDGAR has?~~
  All-time S&P 500 + Nasdaq-100 members for both steps (`--indices` widens it).

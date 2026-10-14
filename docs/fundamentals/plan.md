# Company financials: earnings, fundamentals, guidance — plan

Status (2026-10-14): steps 1 (earnings dates) and 2 (fundamentals table) built, see their
"As built" notes; steps 3–5 not started. The order and scope below are a starting point to
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
  6 sessions after the earnings reaction date, 90th percentile 26.
- **Derived quarters:** a quarter missing as a three-month value is the difference of two
  year-to-date values with the same start and tag (`derived` = 1). This covers 73% of
  operating cash flow quarters and 8–15% of income items, mostly fourth quarters. EPS is
  never derived.
- **XBRL errors handled:** a fact whose period ends after its own filing (REG's 10-K of
  2012-02-29 reporting a quarter to 2012-03-31) is dropped. So is a "quarter" equal to the
  same filing's full year (Oracle tags full-year revenue as Q4).
- **Predecessor CIKs:** a predecessor's reports count when they were filed before the
  successor's first filing. So Google's own 2014 10-K is used, not Alphabet's 2016
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

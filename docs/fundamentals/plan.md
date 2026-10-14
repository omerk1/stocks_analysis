# Company financials: earnings, fundamentals, guidance — plan

Status: plan outline (2026-10-14). Nothing built. The order and scope below are a starting
point to revisit after each step, not commitments.

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

- Table layout: one long facts table (ticker, concept, period, filed, value) or wide
  per-quarter rows?
- ~~Does step 1 also pick up 10-Q/10-K filing dates as a fallback when no item 2.02 8-K
  exists?~~ Yes, flagged in `source` (step 1, "As built").
- Universe: S&P 500 + Nasdaq-100 first (the modeling universe), or everything EDGAR has?

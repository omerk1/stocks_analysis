# Guidance feasibility probe

Step 5 of `docs/fundamentals/plan.md`: before fetching press releases for the whole
universe, label ~50 by hand and see how often they carry guidance and how well an
extraction prompt recovers it. Exploratory: no returns, no backtest, no claims. The
decision it feeds is go / no-go on the full fetch.

## Sample (fixed before any release was read)

`src/llm/guidance/probe/sample.csv`, drawn by `python -m src.llm.guidance.sample`
(seed 20261018; the draw is in the module docstring).

- **Frame:** every item 2.02 8-K announcement in `earnings_announcements` (Done #137,
  `source` = '8-K'; the 10-Q/10-K fallback rows are out) accepted in 2010–2021, New York
  time, one row per release (share classes such as NWS/NWSA file one release under two
  tickers; the class with the largest cap stands for it). 23,089 releases from 619
  companies (CIKs) after two filters: a sector in
  `ticker_sector` (today's, not point-in-time) and a market cap of at least $2B at the
  last close on or before the period end, from a close at most 7 days and a share count
  at most 400 days old (large ≥ $10B, mid $2–10B). Nothing accepted after 2021-12-31.
- **Draw:** 50 releases, 50 companies (distinct CIKs), one per (year, sector, size) cell: 4–5 per year
  (2018 and 2019 get 5), 4–5 per sector across all 11, 26 large and 24 mid. No cell
  needed the size fallback.
- **Not represented:** foreign filers (no item 2.02 8-K), companies under $2B, filers
  without a sector. The universe is all-time S&P 500 + Nasdaq-100 members, so "mid"
  means a member while it was mid-sized, not the S&P 400.

## Label schema

`src/llm/guidance/schema.py`. One label per release: `guidance_present`, a list of
items, free-text `notes`. One item per (metric, period, basis) the company gives an
outlook for:

| Field | Values |
|---|---|
| `metric` | `revenue` (total revenue / net sales), `eps` (any basis), `margin` (gross, operating, EBITDA or net, % of revenue), `other` (segment revenue, net income, EBITDA $, capex, cash flow, tax rate, production, ...) |
| `metric_text` | the release's own name for it |
| `period` | `quarter`, `year`, `other` (half year, multi-year, long-term) |
| `period_text` | the release's own name for it |
| `shape` | `range`, `point` (low = high), `floor` (low only), `ceiling` (high only), `qualitative` (no numbers) |
| `low`, `high` | numbers in the release's unit |
| `unit` | `USD per share`, `USD millions`, `USD billions`, `percent`, `percent growth`, ... |
| `basis` | `gaap`, `adjusted`, `unstated` |
| `revision` | `raised`, `maintained`, `lowered` (vs the company's previous outlook, as the release says), `initiated` (first outlook for the period), `withdrawn`, `not_stated` |
| `evidence` | the source sentence, verbatim |

## Labeling rules

The same rules are in the extraction prompt (`src/llm/guidance/prompt.py`, v1), so the
labels and the model answer the same question.

- **Guidance** is the company's own outlook for a metric of a future period, or of the
  current period before it ends: a number, range, floor or ceiling, or a worded
  outlook tied to a metric and period ("mid-single-digit revenue growth in 2016" is
  `qualitative`; words are never turned into numbers). Reaffirmed outlooks, long-term
  targets and operating metrics (production, units, store openings) count. A withdrawn
  outlook is one `qualitative` item with revision `withdrawn`.
- **Not guidance:** safe-harbor boilerplate, results of ended periods, declared
  dividends or buybacks, macro or industry commentary with no metric and period of the
  company's own, analysts' estimates, anything outside exhibit 99.1 (slides, call
  transcripts).
- **Revision** comes from the release's words only. "Narrowed"/"updated" with the prior
  figures stated: compare midpoints. Without them: `not_stated`. Never from an earlier
  release or outside knowledge.
- **Amounts** as written ("$1.2 billion" → 1.2, `USD billions`); "approximately X" is a
  point at X.

## Extraction prompt

`src/llm/guidance/prompt.py`, version v1, written before any release was read and
pinned by hash in `tests/test_llm_guidance.py`. Gemini 2.5 Flash, temperature 0,
thinking off. Only the release text is sent (no ticker, no date). A changed prompt is
a new version, never an edit of v1.

## Result (2026-10-30)

Exploratory: reading accuracy and coverage only, nothing about returns. N is 50
releases from 50 companies. Every share below has its 95% Wilson interval, and they are wide.

### How the gold set was made

The plan was to draft labels and have them corrected by hand. Checking 50 releases
item by item turned out to need more domain reading than was reasonable, so the gold
set was **adjudicated** instead (`src/llm/guidance/adjudicate.py`):

1. **Fetch** (`fetch.py`): all 50 releases from EDGAR, each with an EX-99 exhibit, cached
   raw under `data/raw/sec/press_releases/`. The User-Agent named a contact, and requests
   were at most ~6.7 a second.
2. **Two independent readings.** Drafts by Claude subagents (`probe/drafts.json`) were
   committed before any extraction ran. Then v1's extractions by Gemini
   (`probe/extractions/v1/`) were cached and committed, with no unusable reply.
3. **Agreed scope**, set before adjudicating and applied by code to both readings
   (`score.in_scope`): a number (not words), for a quarter or a fiscal year, no year
   later than the one after the release. That drops worded outlooks, half years and
   multi-year targets. The judgment calls were left to the person: synergy targets,
   capital-return plans and non-financial goals are not guidance.
4. **Questions where the readings differ** (`probe/questions.md`, answered by the
   person). There were 67 over 43 releases:
   - 17 where a field differs, with the readings as A and B in a seeded random order;
   - 23 where only one reading has the item;
   - 19 releases with only non-headline items, asking whether any of them counts;
   - 8 seeded spot checks of releases where the readings fully agree.

   Answers in words became labels in `probe/answer_overrides.json`, each with its
   reason. Where both readings agree, the reading stands as gold.

Outcome of the disputes: the draft's reading was right in 24 and Gemini's in 14, 1 was
split and 1 neither (`probe/gold_meta.json`). The spot checks found 8 of 8 right. That doesn't measure
errors both readings share, though: 0 in 8 only rules out a rate above about a third
(interval 0–0.32).

Two rulings to know about:

- **Revision rule.** The question sheet simplified the rule to "raised, kept or
  lowered only when the release says so in words". v1's rule, fixed with the prompt
  before any release was read, also says: "updated" or "narrowed" with the prior
  figures printed means compare the midpoints. The gold set uses v1's rule (the person's
  decision), which changed three items: Iron Mountain ×2 lowered, Teleflex raised.
- **"Initiated" counts as "not stated"** (`score.revision_kind`). Neither revises
  earlier guidance. The readings split on it by habit (26 of the first 89 questions), so it
  is one category for both the questions and the score.

Keysight's first-half 2018 figures were flagged as missing. They stay out: a half year
is outside the agreed scope.

**One reply changed after adjudication.** The code review's fix for nested tables
changed the text of one release, Newell Brands (slot 46). Its slide appendix no longer
reads as "X | X". v1 was rerun on that text, one call. The new reply differs: net-sales
growth is now filed as "other", not revenue, and an EPS-growth item appears twice. The
gold set stands as adjudicated, and the score is against the new reply.
`probe/question_readings.json` freezes the model readings the questions were built
from, Newell's old reply included. The gold set is rebuilt from that file, not from
today's cache, and it rebuilds byte for byte. So the same frozen prompt, at temperature 0, gave a
different answer when only the table formatting changed. The text conversion is part
of what has to be frozen.

### Coverage: how often releases carry guidance

| | releases | headline (revenue, EPS, margin) | any guidance in scope |
|---|---|---|---|
| all | 50 | 24 (48%, 0.35–0.61) | 40 (80%, 0.67–0.89) |
| large caps | 26 | 12 | 20 |
| mid caps | 24 | 12 | 20 |

By sector, as headline / any, with 4–5 releases each:

| sector | n | headline | any |
|---|---|---|---|
| Real Estate | 5 | 4 | 4 |
| Utilities | 5 | 4 | 5 |
| Healthcare | 4 | 3 | 3 |
| Technology | 4 | 3 | 4 |
| Basic Materials | 5 | 3 | 5 |
| Industrials | 5 | 3 | 3 |
| Consumer Cyclical | 4 | 2 | 3 |
| Consumer Defensive | 5 | 2 | 5 |
| Energy | 5 | 0 | 4 |
| Financial Services | 4 | 0 | 1 |
| Communication Services | 4 | 0 | 3 |

- **Year:** with 4–5 releases a year, headline guidance runs 1–4 a year (2018 is
  highest, at 4 of 5) and any guidance 2–5. There's no trend that could be told apart from noise.
- **Pattern:** Energy guides on capex and production, not on earnings. Banks barely
  guide at all. So a headline guidance feature would be missing by sector, not at random.

### Accuracy of prompt v1 (Gemini 2.5 Flash) against the gold set

| | result |
|---|---|
| presence, headline | precision 23/23, recall 23/24 (0.80–0.99) |
| presence, any guidance | precision 39/40, recall 39/40 (the one false alarm is a synergy target, which v1 was never told to skip) |
| headline items found | recall 68/73 (0.85–0.97), precision 68/76 (0.81–0.95) |
| values, on matched items | 67/68 (scale-aware: $1.2 billion = $1,200 million) |
| adjusted vs GAAP | 59/68 (0.77–0.93), the weakest field: it says "not said" where the release calls the figure non-GAAP, or the reverse |
| revision, on matched items | 63/68 |

The unit's wording isn't scored. The adjudication never asked about it, so gold's
wording is just the draft's.

Of the 76 headline items Gemini returned, 8 were wrong extras. Most were parts rather
than the company total, filed as revenue or EPS: Alliant's per-subsidiary EPS (3), Broadridge's
recurring-fee revenue growth and Stryker's organic growth. Two were BorgWarner's
operating-margin floors, which the person ruled out, and one is Newell's repeated
EPS-growth item.

- **Quotes are real.** 166 of the 177 in-scope evidence quotes appear verbatim in the
  release text. The other 11 are stitched from pieces that all appear, sometimes with a
  table column header added. None is made up. This was a one-off check, not code in
  the repo; the exception below would need it in code.

### Raised / maintained / lowered: how often can it be read at all

- **How often the release says it:** 23 of the 73 gold headline items (32%), in 13 of the 24 releases with
  headline guidance (0.35–0.72). That's about a quarter of all releases.
- **When the gold says it, Gemini agrees:** 22 of 23.
- **When Gemini says it, it's right:** 22 of 27 (0.63–0.92). "Lowered" is right 4 of 7 times: it
  reads "narrowed" without prior figures (BorgWarner, three items) as lowered.
  Gemini over-reads revisions more than it misses them.

### Paid alternatives (checked 2026-10-18, about 30 minutes, nothing signed up for)

| source | price | history | point-in-time |
|---|---|---|---|
| Benzinga corporate guidance, via Polygon (now "Massive") | $99/month per dataset for individual use; business use by quote | from Sep 2011 per the docs (the partner page says 2012) | each record has a date/time and `last_updated`, plus the previous min/max, so raised/lowered can be derived. EPS and revenue only, no margins. Whether revisions overwrite records, and coverage of delisted companies, aren't stated. |
| Benzinga direct | quote only | same data | same |
| LSEG I/B/E/S Guidance | institutional (or through WRDS) | US from 1994 | yes, the reference dataset |
| FactSet | quote only | not stated | not stated |
| S&P Capital IQ | quote only | not stated | point-in-time snapshots only from Aug 2016 |
| FMP, Wall Street Horizon, Zacks, EODHD, Nasdaq Data Link, Seeking Alpha | no guidance dataset | | |

### Decision for the owner: go / no-go on fetching the full universe

**Recommendation: go on the fetch, and go on extraction only once a ground-rule
exception is written.**

- **Fetch:** about 23,000 releases, ~46,000 EDGAR requests, about two hours at the
  current pacing. No cost.
- **Extraction with v1:** about 270M input and 18M output tokens. That's roughly $130 at Gemini
  2.5 Flash list prices as last known (check current pricing first), and the daily cap
  (2M tokens) would need raising for that run.

Why go:
- Presence, item finding and values are accurate enough to build features on:
  recall 0.96 and 0.93, values 67/68.
- The free source covers 2010 and margins, which Benzinga doesn't.
- Point-in-time comes from EDGAR's acceptance time.

Why only conditionally:
- **Coverage is about half the releases**, and none in Energy, banks or Communication
  Services. Missingness follows sector.
- **Raised/lowered is readable in only about a quarter of releases,** and Gemini over-reads it.
  In the full run, a revision feature should be computed by code, not taken from the model's word:
  - the midpoint against the prior range when the release prints it;
  - or against the company's own previous release's extracted guidance, which is
    point-in-time by construction.
- **The gold set is adjudicated, not fully hand-checked.** Shared errors are bounded
  only loosely by 8 spot checks.

### What a ground-rule exception would need

`docs/ideation/llm_agentic_workflows.md` ("Ground rule") keeps LLMs out of the
backtested path. This probe doesn't change that. An exception is the owner's to write. It
would need at least the following:

1. **A frozen prompt, and frozen text going into it.** One prompt version, pinned by
   hash (v1 is: `tests/test_llm_guidance.py`). Any change is a new version, measured
   again on a gold set it hasn't seen; these 50 are now known to whoever tunes the
   prompt. The HTML-to-text conversion counts as part of that version too: Newell's
   reply changed when only the table formatting did.
2. **Cached outputs.** Every reply is stored with its prompt fingerprint and a
   hash of the text it read. The backtest reads only the cache, with no live call in its
   path, and is reproducible from it.
3. **Measured accuracy.** Per field, against a person-checked or adjudicated gold set, with N
   and intervals, and with thresholds committed before the full run. For example:
   presence recall, item recall, values, and adjusted vs GAAP.
4. **Reading, not remembering:**
   - only the release text is sent, with no ticker or date (as in v1);
   - every item must carry a quote that is checked against the text by code;
   - fields that need judgment beyond the text, like revisions, are computed by code
     from extracted numbers.

   The model can still recognise a company from its text. A test on releases from after
   the model's training cutoff would show whether accuracy depends on memory, but those
   releases fall after 2021-12-31, so that test needs the holdout opened explicitly.
5. **Timing.** A feature is available from the release's acceptance time, with the usual
   one-bar lag.

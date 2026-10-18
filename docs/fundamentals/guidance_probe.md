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

## Result

Pending (second PR): fetch, draft labels, review sheet, gold set, v1's score, coverage
by year and sector, and the paid alternatives.

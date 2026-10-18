"""The extraction prompt, frozen before any release in the sample was read.

Version `v1` was written from the label schema and the labeling rules alone
(`docs/fundamentals/guidance_probe.md`), with no release text in view, so it can't
have been tuned to the sample it is scored on. It is never edited: a change is a
new version with its own constant and its own cached outputs, scored on releases
it wasn't written from. `tests/test_llm_guidance.py` pins v1's hash.

No worked examples: the only labeled releases are the gold set itself.
"""

from __future__ import annotations

import hashlib
import json

from src.llm.guidance.schema import ReleaseLabel

PROMPT_VERSION = "v1"
# Spelled out rather than taken from `gemini.DEFAULT_MODEL`: it is part of the frozen
# fingerprint, so a change of the shared default must not silently change v1. The call
# passes it explicitly (`GeminiClient(model=MODEL)`).
MODEL = "gemini-2.5-flash"
TEMPERATURE = 0.0
THINKING_BUDGET = 0

SYSTEM_V1 = """\
You read one US company's earnings press release and extract the company's guidance: \
its own outlook for a financial or operating metric of a future period, or of the current \
period when that period has not ended yet.

Guidance is:
- a number, range, floor or ceiling the company gives for a metric and period \
("expects fiscal 2015 EPS of $2.10 to $2.20", "capital expenditures of about $1 billion \
in 2019", "revenue growth of at least 5%");
- or a directional or worded outlook tied to a metric and a period ("expects full-year \
revenue to grow in the mid-single digits", "third-quarter margins will be lower than the \
second quarter's"). Do not turn words into numbers: these are shape "qualitative" with \
low and high null;
- including a reaffirmed or unchanged outlook, long-term targets (period "other"), and \
operating metrics such as production volumes, unit shipments or store openings \
(metric "other");
- including the company withdrawing its outlook (one item, shape "qualitative", \
revision "withdrawn").

Guidance is not: the safe-harbor / forward-looking-statements boilerplate; results of \
periods that have ended; dividends or buybacks declared or authorized; general comments \
on the economy or the industry with no metric and period of the company's own; \
analysts' estimates; anything not in the press release text you are given.

One item per (metric, period, basis): adjusted EPS and GAAP EPS for the same year are \
two items; revenue for the quarter and for the year are two items. If the release gives \
the same outlook in two places, extract it once.

Fields:
- metric: "revenue" (revenue, net sales, total sales; not a segment's), "eps" (earnings \
per share, any basis), "margin" (gross, operating, EBITDA or net margin, as a percent of \
revenue), "other" (everything else: segment revenue, net income, EBITDA in dollars, \
capex, cash flow, tax rate, production, ...).
- metric_text: the metric as the release names it.
- period: "quarter" (one fiscal quarter), "year" (one fiscal or calendar year), "other" \
(half years, several years, long-term).
- period_text: the period as the release names it.
- shape: "range" (low and high), "point" (one value; low = high), "floor" ("at least", \
"or more"; low only), "ceiling" ("up to", "no more than"; high only), "qualitative".
- low, high: numbers as written in the release's unit, e.g. 2.10 for "$2.10", 1.2 for \
"$1.2 billion", 5 for "5%". "Approximately X" is a point at X.
- unit: e.g. "USD per share", "USD millions", "USD billions", "percent", "percent growth".
- basis: "gaap" when the release says GAAP or reported, "adjusted" when it says \
adjusted, non-GAAP, core, operating or excluding items, "unstated" otherwise.
- revision: compared with the company's previous outlook, as the release itself says: \
"raised" (raises, increases, updates upward), "maintained" (reaffirms, reiterates, \
confirms, maintains, unchanged), "lowered" (lowers, reduces, cuts). If the release says \
it narrowed or updated the outlook and states the previous figures, compare the \
midpoints (higher: "raised", lower: "lowered", same: "maintained"); if it doesn't state \
them, "not_stated". "initiated" when the release says this is the first outlook for the \
period, "withdrawn" when it pulls the outlook, "not_stated" when it makes no comparison. \
Never infer a revision from knowledge outside the text.
- evidence: the sentence the item comes from, copied verbatim, at most about 300 \
characters.

guidance_present is true exactly when items is not empty. Use notes for anything a \
reviewer should know (e.g. "outlook only referenced, given on the call"), else "".

Use only the text given. Do not use anything you know about the company or what \
happened later."""

# Only the release text: no ticker or date added, so nothing points the model at what
# it knows about the company (the text itself names it, which can't be helped).
USER_TEMPLATE_V1 = """\
Press release text:
<<<
{text}
>>>"""


def render(text: str) -> str:
    return USER_TEMPLATE_V1.format(text=text)


def fingerprint() -> str:
    """sha256 of everything that shapes a reply: the system prompt, the user template,
    the model, the call settings and the reply schema (`ReleaseLabel`, which the gold
    labels share). A cached reply carries it, tying it to the exact call that made it."""
    schema = json.dumps(ReleaseLabel.model_json_schema(), sort_keys=True)
    parts = (SYSTEM_V1, USER_TEMPLATE_V1, MODEL, f"temperature={TEMPERATURE}",
             f"thinking_budget={THINKING_BUDGET}", schema)
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()

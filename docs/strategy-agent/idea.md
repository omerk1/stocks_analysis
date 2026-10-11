# Natural-language → testable strategy agent — idea

Status: idea (2026-10-11). Nothing decided or built. Related brainstorm:
`docs/ideation/llm_agentic_workflows.md` (its ground rule applies here, see below).

## One-liner

An agent that takes a trading idea described in plain language and turns it into a
precise, testable spec, then into deterministic event code, then runs it through an
honest test: matched control, effective N, costs, and an explicit verdict.

## Why

Ideas start vague ("price coils near the MA, then breaks out"). Testing one needs many
decisions that usually stay implicit (what counts as "size", which bar triggers, what
invalidates it). Each unstated decision is a place to fool yourself. The agent's job is to
make every one explicit and have the user confirm it.

Two possible uses:

- **Internal:** a faster, more disciplined Track A for this repo.
- **External (possible later):** a platform where other people test their own ideas.
  The pitch is "test your trading idea honestly", not "turn your idea into a strategy".
  Tools that turn text into a strategy already exist; few of them report a matched
  control, effective N, costs, or a verdict that can say "dead" or "inconclusive". That
  rigor is the hard-to-copy part.

## What the agent must pin down

- **Visual examples**
	- Annotated charts of real instances the user agrees match the idea, plus near-misses
	  that don't
	- *e.g.* 3 positives, 3 "looks similar but isn't"
- **Timeframe**
	- Bar resolution the pattern lives on
	- *e.g.* daily bars
- **Pattern duration**
	- How many bars the pattern takes to form (min/max)
	- *e.g.* 10–40 bars
- **Pattern "size"**
	- Its magnitude, normalised so tickers are comparable (ATR, log, percentile; never
	  raw price)
	- *e.g.* range ≤ 1.5 × ATR(14)
- **Entry / trigger**
	- The exact bar the signal fires; executes at t+1, never the same bar
	- *e.g.* close above range high
- **Horizon**
	- How long after the trigger the outcome is measured
	- *e.g.* 5 / 10 / 20 bars forward
- **Invalidation**
	- What kills the setup before or after entry, each rule with a catalogue of labelled
	  historical cases where it fired
	- *e.g.* close back inside the range within 3 bars
- **Supporting signals**
	- Conditions that make the setup stronger (filters, context)
	- *e.g.* above SMA200, rising volume
- **Secondary metrics**
	- Descriptive outcomes beyond mean return (no CI, no verdict on these)
	- *e.g.* hit rate, win/loss ratio, skew, MFE/MAE, time to target
- **Control**
	- What the setup is compared against, so the result is a delta and not a bare mean
	- *e.g.* same tickers and dates without the pattern, matched on volatility and trend

## Workflow

1. **Elicit:** turn the free text into the fields above, asking about every ambiguity.
2. **Ground in examples:** find historical instances (development window only), show them
   as charts, and have the user accept or reject each one. Repeat until the definition
   matches what the user means. Examples *define* the idea; they never validate it.
3. **Formalise:** a parameterised event definition in code plus a written spec. The code
   is deterministic; the LLM writes it but never produces a signal itself.
4. **Guardrails, enforced by the platform rather than the agent:** one-bar lag,
   trailing-only statistics, delisted tickers kept, NaN-preserving comparisons, holdout
   locked. Generated code passes the same hygiene and look-ahead tests as hand-written
   code.
5. **Test:** a cheap exploratory look first. Anything worth confirming gets a
   pre-registration draft (hypothesis, kill criterion, control, cost hurdle) before it
   runs.
6. **Report:** delta vs control with CI, effective N, gross and after costs, distribution
   shape, and one of three verdicts: alive, dead (CI inside the irrelevance band),
   inconclusive.

## Risks

- **More ideas makes false discovery worse.** In the MA study, 2 of 107 cells survived
  FDR. Slow translation was never the bottleneck: most ideas die. Every idea the agent
  formalises has to be logged and counted toward the multiple-testing correction,
  including the variants a user reruns until something passes.
- **Picking examples by eye is a hidden fit.** Approved charts tend to be ones that
  worked out, so the definition leans toward winners before any test runs. Near-misses
  and randomly sampled matches reduce this but don't remove it.
- **The LLM knows history.** It can't be a signal source (see the ground rule in
  `docs/ideation/llm_agentic_workflows.md`). Here it only translates; but its
  suggestions ("add a volume filter") can still carry what it has read about which
  patterns worked. Suggestions it adds count as extra tests and are flagged as its own.
- **Generated code can hide look-ahead bugs.** Invariant 9 came from a subtle NaN bug no
  one noticed. Hygiene tests are mandatory, not optional.
- **External only:**
	- *Users want their idea to work.* An honest tool mostly delivers bad news. There will
	  be pressure to soften verdicts, which is exactly what makes other tools
	  untrustworthy. How bad news is delivered needs designing on purpose.
	- *Data licensing.* The current market-data subscription probably doesn't allow
	  showing data to other users. Check early: it can change the cost structure or kill
	  the product.
	- *Regulation.* Present it as a research and validation tool, not trade signals.

## Out of scope

- Judging whether an idea is good: the tests do that.
- Tuning parameters to fit the examples.
- Live trading or alerts.

## First step

Elicitation only, no code generation. Run it on 2–3 ideas from
`docs/features/moving-averages/EXPLORATION_LOG.md` that were already built by hand. If its
specs match what was actually built, or catch decisions that were missed, add code
generation next.

"""Step 5 of the strategy agent (`docs/strategy-agent/idea.md`, workflow steps 5-6): the
exploratory look. Once a spec is complete and grounded, ask whether the setup predicted
anything — the repo's way: a conditional forward-return delta against a matched control,
never a trading backtest (a backtest hides hundreds of silent decisions; this look has
one, the horizon, and the spec states it in `horizons_bars`).

**Track A, and said so everywhere.** The output is exploratory: wide, cheap, no
multiple-testing correction, never a finding (CLAUDE.md, "What this project is"). What an
honest look reports, per (side, horizon) cell:

- the control waterfall C0 → C1 → C2 on one common row set (`c2_eligible_mask`), so
  shrinkage means stricter control, not changed sample. C1 (same-date non-events) removes
  the market-return confound; C2 (same date + momentum tercile + vol tercile + sector)
  separates the setup from "this stock already rose". The shrinkage is the headline.
- a block-bootstrap CI on the C2 delta, with effective N = distinct dates (events
  cluster; 40,000 rows on 55 dates is 55 observations), next to raw counts.
- distribution shape (hit rate vs control, win/loss magnitude, skew), reported in the
  trade's direction — descriptive only, CLAUDE.md invariant #10: no CI, no kill criterion.
- the per-event round-trip cost printed next to the per-event gross delta, never behind
  it (invariant #8) — per-event vs per-event is the fair comparison for an event signal
  (each signal pays the cost once and earns the delta once; see `verdict`), with the
  signals-per-ticker-year turnover alongside for scale.
- a three-way verdict in Track A words: *looks alive* (CI clears the per-event cost in
  the stated direction), *looks dead* (the whole CI sits inside the ±cost band — an
  effect big enough to pay for its own trade is affirmatively ruled out), else
  *inconclusive* — a CI spanning zero but reaching past the band is underpowered, never
  dead. A CI clearing the cost *against* the stated direction is called out as inverted,
  not buried.

Events come from the same finder grounding used (`finders.py`), on the **other
alignment**: grounding un-lags so a chart's trigger date is the signal bar; the look
flags the panel row *after* each match (the exact inverse of `shift_to_signal_bar`),
restoring the central one-bar lag — the signal fires on close t, outcomes are measured
from row t+1, where every lagged feature also describes close t. A signal on a ticker's
last panel row has no next bar to trade and is excluded, with the count disclosed.

A spec stating `direction="both"` is tested one side at a time: the two sides of a setup
carry opposite expected signs, and a pooled delta would cancel them into a confident
nothing. A spec with no direction at all is refused — finish elicitation.

The search rubric discipline carries over from grounding, extended to the test itself:
every applied parameter says where it came from, and every spec field the look does NOT
act on is disclosed — after-entry invalidation rules (no path-dependent exits here), a
prose `control` section (platform tiers are used instead), `secondary_metrics` (the
standard shape set is always reported), the flat cost default.

If any cell looks alive the session writes `prereg_draft.md` — the skeleton of a Track B
pre-registration (hypothesis, kill criterion with the hurdle as the relevance band,
control tier, scope) for a human to complete, commit, and only then run. The agent never
runs Track B.

No LLM is involved: deterministic code, zero tokens. Artifacts land under
`data/llm/look_sessions/<timestamp>/` (git-ignored): `report.md` (what was printed),
`result.json`, and `prereg_draft.md` when earned. One line per side is printed
ready-to-paste into `docs/strategy-agent/EXPLORATION_LOG.md`.

CLI: `python -m src.llm.strategy_spec.look <spec-or-elicitation-transcript.json>`.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.llm.paths import llm_data_dir
from src.llm.strategy_spec.finders import (
    DEFAULT_MA, GroundingError, MA_COLUMNS, RubricLine, dispatch)
from src.llm.strategy_spec.schema import StrategySpec, find_gaps
from src.models.dataset import check_holdout
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import (
    c0_delta, c1_delta, c2_eligible_mask, cross_sectional_bucket, stratum_deltas)
from src.signals.moving_averages.stats.costs import ci_clears_cost
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas

SESSIONS_DIR_NAME = "look_sessions"
TRACK_A_BANNER = ("TRACK A — exploratory look. Nothing below is a finding; promoting any "
                  "of it requires a pre-registered Track B test.")
# The study's standard C2 strata (DESIGN §6.1 via modules/respect_history.py's
# convention): terciles, not deciles — event sets here can be small.
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")
CONTEXT_COLS = ("mom_12_1", "realized_vol_63", "sector")
ROUND_TRIP_COST_BPS = 10.0  # DESIGN §6.10 / M1's convention: 10 bps per round trip, U1
N_BOOT = 500
CI_LEVEL = 0.90
HYPOTHESISED_SIGN = {"long": 1, "short": -1}


def fwd_col(horizon: int) -> str:
    return f"fwd_ret_{horizon}"


def block_length_for(horizon: int) -> int:
    """DESIGN §6.2: block length >= 2x horizon, never below the 10-row floor for
    sparse events (same rule as the MA study's modules)."""
    return max(10, 2 * horizon)


def event_mask(panel: pd.DataFrame, matches) -> tuple[pd.Series, int]:
    """Boolean event column on `panel`: True on the row AFTER each match's signal bar,
    per ticker — the inverse of `shift_to_signal_bar`, restoring the one-bar lag the
    finder undid for display (CLAUDE.md invariant #2: a signal on close t executes at
    t+1; here every outcome is measured from the t+1 row). Also returns how many
    signals fell on a ticker's last panel row (no next bar to trade — excluded)."""
    keys = pd.MultiIndex.from_arrays([panel["ticker"], panel["date"]])
    signal = pd.Series(keys.isin([(c.ticker, c.date) for c in matches]), index=panel.index)
    event = signal.groupby(panel["ticker"], sort=False).shift(1, fill_value=False)
    return event, int(signal.sum() - event.sum())


def add_context(panel: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Forward returns at the spec's horizons plus the C2 buckets (per-date cross-
    sectional terciles — trailing/cross-sectional only, invariant #3). Returns a new,
    trimmed frame."""
    working = panel[["ticker", "date", "close", *CONTEXT_COLS]].copy()
    for h in horizons:
        working[fwd_col(h)] = forward_return(working, horizon=h)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    return working


def verdict(ci_low: float, ci_high: float, cost: float, sign: int) -> str:
    """The three-way exploratory verdict on one cell: the per-event C2 delta's CI
    against the per-event round-trip cost — the fair units for an event signal, where
    each signal pays the cost once and earns the delta once (annualizing both by
    signals-per-year cancels out; the study's ×252/horizon convention belongs to
    always-in-position state signals and would inflate the gross side ~252/(h×spy)-fold
    here). Dead means the WHOLE CI sits inside the ±cost band (an effect big enough to
    pay for its own trade is affirmatively ruled out); a CI that spans zero but reaches
    past the band is inconclusive/underpowered, never dead (the three-verdict rule,
    CLAUDE.md "Before running any analysis"). A CI that clears the cost against the
    spec's stated direction is reported as inverted, not hidden in inconclusive."""
    if pd.isna(ci_low) or pd.isna(ci_high):
        return "inconclusive (not enough distinct dates to bootstrap)"
    if ci_clears_cost(ci_low, ci_high, cost):
        if (1 if ci_low > 0 else -1) == sign:
            return "looks alive (exploratory — not a finding)"
        return "looks inverted (CI clears the per-event cost AGAINST the stated direction)"
    if max(abs(ci_low), abs(ci_high)) <= cost:
        return "looks dead (whole CI inside the per-event cost band)"
    return "inconclusive (CI neither clears the per-event cost nor fits inside it)"


def contamination_mask(working: pd.DataFrame, any_event: pd.Series, horizon: int) -> pd.Series:
    """Rows whose own `horizon`-bar forward window overlaps ANY event's outcome window
    on the same ticker — the control pool must exclude them: an other-side neighbour
    carries the opposite expected move (the pooled-cancellation confound the per-side
    split exists to avoid — the signal bar alone carries (h-1)/h of it), and a same-side
    neighbour carries the same-signed move, dragging the control mean toward the event
    mean and attenuating a real delta (events cluster, so this is common). Overlap
    exists for rows within h-1 bars either side of an event row; a centered rolling max
    flags exactly that set. Depends only on (events, horizon), so a "both" spec's two
    sides share one mask per horizon."""
    window = 2 * horizon - 1
    return (any_event.astype(float)
            .groupby(working["ticker"], sort=False)
            .transform(lambda s: s.rolling(window, center=True, min_periods=1).max())
            .gt(0))


def cell(working: pd.DataFrame, event: pd.Series, contaminated: pd.Series, side: str,
         horizon: int, cost_round_trip: float, seed: int, ticker_years: float) -> dict:
    """One (side, horizon) cell: the C0→C1→C2 waterfall on the common eligible row set,
    the bootstrap CI on C2, effective N, shape (in the trade's direction), per-event
    cost and verdict. `contaminated` rows (see `contamination_mask`) leave the control
    pool; this side's own event rows are kept — they fired, and their outcome is
    whatever it is."""
    value_col = fwd_col(horizon)
    # Turnover counts every signal taken — a trader pays the round trip even for a
    # terminal-bar signal with no measurable outcome (the delisted tickers invariant #4
    # keeps in), and regardless of whether the C2 strata can score it (momentum warmup
    # drops ~7% of fired events on real data).
    fired = int(event.sum())
    frame = working[["ticker", "date", value_col, *C2_MATCH_COLS]].copy()
    frame["__event"] = event.to_numpy()
    frame = frame.loc[frame["__event"] | ~contaminated]
    # One row population for all three tiers (DESIGN §6.1 / PREREGISTRATION's "Waterfall
    # row set"): otherwise shrinkage is confounded with sample composition.
    frame = frame[c2_eligible_mask(frame, "__event", value_col, list(C2_MATCH_COLS))]
    events = frame.loc[frame["__event"], value_col].dropna()

    row: dict = {"side": side, "horizon": horizon,
                 "n_events": int(len(events)), "n_events_fired": fired,
                 "n_dates": int(frame.loc[frame["__event"], "date"].nunique()),
                 "n_tickers": int(frame.loc[frame["__event"], "ticker"].nunique())}
    row["delta_c0"] = c0_delta(frame, "__event", value_col)
    row["delta_c1"] = c1_delta(frame, "__event", value_col)
    try:
        boot = block_bootstrap_delta(frame, "__event", value_col, list(C2_MATCH_COLS),
                                     block_length=block_length_for(horizon),
                                     n_boot=N_BOOT, ci=CI_LEVEL, seed=seed)
    except InsufficientBlocksError:
        # Too few distinct dates for a CI is not the same as no observations: report
        # the C2 point and the real distinct-date count (invariant #6), with NaN CIs.
        strata = stratum_deltas(frame, "__event", value_col, ["date", *C2_MATCH_COLS])
        boot = {"point_estimate": float(strata["delta"].mean()) if len(strata) else float("nan"),
                "ci_low": float("nan"), "ci_high": float("nan"),
                "n_dates": int(strata["date"].nunique())}
    row["delta_c2"] = boot["point_estimate"]
    row["ci_low"] = boot["ci_low"]
    row["ci_high"] = boot["ci_high"]
    row["effective_n_dates"] = int(boot["n_dates"])

    # Shape in the TRADE's direction: a short setup's hit rate is P(the stock fell),
    # and its wins are price drops — raw-return shape would print a working short as a
    # failing one right next to an alive verdict on the negative delta.
    sign = HYPOTHESISED_SIGN[side]
    shape = distribution_shape(events * sign)
    frame["_signed"] = frame[value_col] * sign
    hits = (hit_rate_deltas(frame, "__event", "_signed", match_cols=list(C2_MATCH_COLS))
            if len(events) else {})
    row["hit_rate"] = hits.get("hit_rate", float("nan"))
    row["hit_rate_delta_c2"] = hits.get("hit_rate_delta_c2", float("nan"))
    row["win_loss_ratio"] = shape["win_loss_ratio"]
    row["skew"] = float(shape["skew"]) if pd.notna(shape["skew"]) else float("nan")

    row["signals_per_ticker_year"] = fired / ticker_years if ticker_years else float("nan")
    row["cost_round_trip"] = cost_round_trip
    row["verdict"] = verdict(row["ci_low"], row["ci_high"], cost_round_trip, sign)
    return row


def look_rubric(spec: StrategySpec, horizons: list[int], cost_bps: float | None,
                dropped_last_bar: int, split_sides: bool) -> list[RubricLine]:
    """The look's own rubric lines, appended to the finder's: everything the test
    applies, and every spec field it deliberately does NOT act on, said out loud."""
    lines = [
        RubricLine("grounding", f"{len(spec.examples)} judged example(s) on the spec", "spec",
                   "example rows don't record the detector or MA they were judged under — "
                   "if this run overrides either, the confirmation may not transfer")
        if spec.examples else
        RubricLine("grounding", "NOT CONFIRMED", "default",
                   "spec.examples is empty — no grounding round's verdicts are recorded, "
                   "so this look tests a definition never confirmed on charts"),
        RubricLine("entry timing", "signal close (bar t) → outcomes from the next bar (t+1)",
                   "default", "the repo's one-bar lag — you can't trade the close that "
                   "formed the signal"),
        RubricLine("outcome", f"raw close-to-close forward return at {', '.join(map(str, horizons))} bars",
                   "spec", "from horizons_bars"),
        RubricLine("control", "C1 date-matched; C2 date + momentum tercile + vol tercile + sector",
                   "default", "the platform's standard tiers (DESIGN §6.1); the C2 delta "
                   "carries the CI and the verdict"),
    ]
    if split_sides:
        lines.append(RubricLine("direction split", "long and short tested separately", "default",
                                "your spec says both — the two sides carry opposite expected "
                                "signs, and pooling them would cancel a real effect; each "
                                "side's control pool also excludes the other side's event rows"))
    if spec.control is not None:
        lines.append(RubricLine("your stated control", "NOT APPLIED", "default",
                                f'no structured mapping yet for "{spec.control.description}" — '
                                "the platform tiers above are reported instead"))
    for rule in spec.invalidation:
        if rule.phase == "after_entry":
            lines.append(RubricLine(f"invalidation (after entry): {rule.description}",
                                    "NOT APPLIED", "default",
                                    "this is a fixed-horizon look — path-dependent exits "
                                    "aren't simulated"))
    for metric in spec.secondary_metrics:
        lines.append(RubricLine(f"secondary metric: {metric}", "NOT COMPUTED", "default",
                                "hit rate, win/loss magnitude and skew are always reported; "
                                "other metrics have no mapping yet"))
    lines.append(RubricLine(
        "cost", f"±{cost_bps if cost_bps is not None else ROUND_TRIP_COST_BPS:g} bps per "
        "round trip, compared per event",
        "run option" if cost_bps is not None else "default",
        None if cost_bps is not None else "the study's M1 cost figure (DESIGN §6.10); "
        "override with --cost-bps"))
    if dropped_last_bar:
        lines.append(RubricLine("excluded signals",
                                f"{dropped_last_bar} signal(s) on a ticker's last panel row",
                                "default", "no next bar exists to trade them"))
    return lines


def _jsonable(value):
    """Non-finite floats (NaN, ±inf) → null, recursively: `json.dumps` would otherwise
    emit bare `NaN`/`Infinity` tokens (valid Python, invalid JSON) — a cell with an
    un-bootstrappable CI, or a bad zero-close bar turning a forward return infinite,
    would make the whole session artifact refuse to parse anywhere outside Python."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _format_cell(row: dict) -> str:
    pct = lambda x: "nan" if pd.isna(x) else f"{x * 100:+.2f}%"   # signed: deltas only
    rate = lambda x: "nan" if pd.isna(x) else f"{x * 100:.0f}%"   # a probability, not an excess
    return (f"h={row['horizon']}: ΔC0 {pct(row['delta_c0'])} → ΔC1 {pct(row['delta_c1'])} → "
            f"ΔC2 {pct(row['delta_c2'])} [{pct(row['ci_low'])}, {pct(row['ci_high'])}] "
            f"({row['n_events']} of {row['n_events_fired']} fired events C2-scorable, "
            f"{row['n_dates']} dates, effective N "
            f"{row['effective_n_dates']} dates, {row['n_tickers']} tickers); "
            f"hit rate {rate(row['hit_rate'])} (ΔC2 {pct(row['hit_rate_delta_c2'])}), "
            f"win/loss {row['win_loss_ratio']:.2f}, skew {row['skew']:.2f} — all in the "
            f"trade's direction; vs per-event cost ±{row['cost_round_trip'] * 100:.2f}% "
            f"round trip ({row['signals_per_ticker_year']:.2f} signals per ticker-year) "
            f"→ {row['verdict']}")


def _log_line(spec: StrategySpec, detector: str, side: str, cells: list[dict], out_dir: Path) -> str:
    """The ready-to-paste one-liner for docs/strategy-agent/EXPLORATION_LOG.md."""
    pct = lambda x: "nan" if pd.isna(x) else f"{x * 100:+.2f}%"
    today = datetime.now(timezone.utc).date()
    summary = "; ".join(
        f"h{c['horizon']} ΔC2 {pct(c['delta_c2'])} [{pct(c['ci_low'])},{pct(c['ci_high'])}] "
        f"effN {c['effective_n_dates']}d — {c['verdict'].split(' (')[0]}" for c in cells)
    return (f"- {today} [look] {spec.name or detector} ({side}): {summary}; "
            f"session {out_dir}")


def _prereg_draft(spec: StrategySpec, detector: str, alive: list[dict], window: tuple[str, str],
                  cost_bps: float, out_dir: Path) -> str:
    cells = "\n".join(
        f"  - {c['side']}, h={c['horizon']}: ΔC2 {c['delta_c2'] * 100:+.2f}% per event "
        f"[{c['ci_low'] * 100:+.2f}%, {c['ci_high'] * 100:+.2f}%] vs ±{c['cost_round_trip'] * 100:.2f}% "
        f"round-trip cost" for c in alive)
    return f"""# Pre-registration draft — {spec.name or detector} (NOT registered)

Generated by the exploratory look at `{out_dir}`. That look is Track A: its numbers are
shown for context only and must not be treated as findings — this draft exists because
promoting them requires a pre-registered Track B test. **Fill the TODOs, commit this
entry to the relevant PREREGISTRATION file, and only then run.**

- Promoted from: `{out_dir}` (exploratory look, {window[0]} to {window[1]})
- Module/track: TODO (a module id) / Track B
- Hypothesis: the spec's setup ({detector}) predicts C2-matched excess forward return in
  the stated direction at the horizons below.
- Cells that looked alive (context, not evidence):
{cells}
- Primary cell: TODO — pick ONE (side, horizon) before running; every extra cell is an
  extra test and goes into N_tests.
- Kill criterion: dead iff the whole {CI_LEVEL:.0%} CI of the per-event C2 delta sits
  inside the economic-relevance band ±{cost_bps:g} bps (the round-trip cost each signal
  pays — per-event delta vs per-event cost is the fair comparison for an event signal).
  A CI spanning zero that reaches past the band is inconclusive/underpowered, never dead
  (the three-verdict rule).
- Control tier: C2 (date + momentum tercile + vol tercile + sector), block bootstrap with
  block length ≥ 2× horizon, effective N = distinct dates.
- Scope: development window only ({window[0]} to {window[1]}); the cached MA feature
  panel's universe. TODO: state what would change the verdict.
"""


def look(spec: StrategySpec, panel: pd.DataFrame, *, ma: str | None = None,
         detector: str | None = None, cost_bps: float | None = None, seed: int = 0,
         say=print, out_dir: Path | None = None) -> dict:
    """One exploratory look over `panel` (a `features/panel.py` panel, development window
    only — a panel reaching past the holdout boundary is refused). Returns the result
    dict that is also written as `result.json`; prints (via `say`) the report that is
    also written as `report.md`."""
    if panel.empty:
        raise GroundingError("the panel is empty — nothing to test against")
    for needed in ("ticker", "date", "close", *CONTEXT_COLS):
        if needed not in panel.columns:
            raise GroundingError(f"panel has no {needed!r} column — not a feature panel?")
    check_holdout(panel["date"].max())
    # The horizon rules live in schema.find_gaps, in one place — a horizon below 1 bar
    # would silently report a PAST return as the forward outcome (forward_return shifts
    # by -horizon), a duplicate double-counts its cell, and a missing list means the one
    # outcome decision was never made. It is the trader's decision, not a default's.
    horizon_gaps = [g for g in find_gaps(spec) if g.field == "horizons_bars"]
    if horizon_gaps:
        raise GroundingError("the spec's horizons_bars aren't ready — "
                             + "; ".join(g.reason for g in horizon_gaps)
                             + " — finish elicitation before testing")
    if spec.direction is None:
        raise GroundingError("the spec doesn't state a direction — finish elicitation before "
                             "testing (the two sides of a setup carry opposite expected "
                             "signs; a pooled delta would cancel them)")

    horizons = list(spec.horizons_bars)
    sides = ["long", "short"] if spec.direction == "both" else [spec.direction]
    cost_round_trip = (cost_bps if cost_bps is not None else ROUND_TRIP_COST_BPS) / 10_000

    lines: list[str] = []
    def out(text: str = "") -> None:
        lines.append(text)
        say(text)

    out(TRACK_A_BANNER)

    # Dispatch once per side: the finder itself applies the direction filter, and its
    # per-side rubric stays truthful. The notes a dispatch may emit (ignored --ma, an
    # off-spec --detector) are printed on the first side only — they repeat verbatim.
    results = {}
    finder_id = ""
    for n, side in enumerate(sides):
        side_spec = spec if spec.direction == side else spec.model_copy(update={"direction": side})
        finder_id, results[side] = dispatch(side_spec, panel, detector=detector, ma=ma,
                                            near_misses=False,  # the look only consumes matches
                                            note=out if n == 0 else (lambda _: None))

    # The displayed finder rubric is the first side's run. When a "both" spec is split,
    # that run's own direction line describes one side only — drop it and let the
    # "direction split" line below own direction, or the rubric contradicts itself.
    finder_rubric = [r for r in results[sides[0]].rubric
                     if not (len(sides) > 1 and r.parameter == "direction")]
    event_by_side: dict[str, pd.Series] = {}
    dropped = 0
    for side in sides:
        event_by_side[side], dropped_side = event_mask(panel, results[side].matches)
        dropped += dropped_side
    extra = look_rubric(spec, horizons, cost_bps, dropped, split_sides=len(sides) > 1)

    out("Search rubric — what was actually applied:")
    for line in (*finder_rubric, *extra):
        detail = f" — {line.detail}" if line.detail else ""
        out(f"  - {line.parameter}: {line.value}  [{line.source}]{detail}")

    window = (str(panel["date"].min().date()), str(panel["date"].max().date()))
    # Ticker-years of actual coverage: panel rows / 252. Unlike window-years × ticker
    # count, this doesn't book a delisted or late-listed ticker's missing years as live
    # (invariant #4 keeps those tickers in). It still includes each ticker's indicator
    # warmup bars, where no finder could fire — which finder-specific columns warm up is
    # not knowable generically here — so the printed turnover is slightly understated
    # (~7% on the real panel); it is context next to the per-event verdict, not a gate.
    ticker_years = len(panel) / 252
    panel_tickers = int(panel["ticker"].nunique())
    for side in sides:
        matches = results[side].matches
        out(f"Population ({side}): the definition fires {len(matches)} times on "
            f"{len({c.date for c in matches})} distinct signal dates, {window[0]} to "
            f"{window[1]} (cells below count their next-bar event rows, one bar later).")

    working = add_context(panel, horizons)
    any_event = pd.Series(False, index=panel.index)
    for mask in event_by_side.values():
        any_event |= mask
    # One contamination pass per horizon — the mask is side-independent (see
    # contamination_mask), and it's the heaviest per-cell operation on a real panel.
    contaminated = {h: contamination_mask(working, any_event, h) for h in horizons}
    cells = [cell(working, event_by_side[side], contaminated[h], side, h,
                  cost_round_trip, seed, ticker_years)
             for side in sides for h in horizons]

    out()
    for side in sides:
        out(f"{side}:")
        for row in (c for c in cells if c["side"] == side):
            out(f"  {_format_cell(row)}")

    out_dir = out_dir or sessions_dir() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    out_dir.mkdir(parents=True, exist_ok=True)

    alive = [c for c in cells if c["verdict"].startswith("looks alive")]
    draft_name = None
    if alive:
        draft_name = "prereg_draft.md"
        (out_dir / draft_name).write_text(
            _prereg_draft(spec, finder_id, alive, window,
                          cost_bps if cost_bps is not None else ROUND_TRIP_COST_BPS, out_dir))
        out(f"\n{len(alive)} cell(s) look alive — a Track B pre-registration draft was "
            f"written to {out_dir / draft_name}; fill its TODOs and commit it before any "
            "confirmatory run.")
    out("\nPaste into docs/strategy-agent/EXPLORATION_LOG.md:")
    for side in sides:
        out(_log_line(spec, finder_id, side, [c for c in cells if c["side"] == side], out_dir))

    result = {
        "track": "A (exploratory — not a finding)",
        "detector": finder_id,
        "spec_name": spec.name,
        "window": list(window),
        "panel": {"tickers": panel_tickers, "ticker_years": ticker_years},
        "seed": seed,
        "cost_round_trip_bps": cost_bps if cost_bps is not None else ROUND_TRIP_COST_BPS,
        "rubric": [{"parameter": r.parameter, "value": r.value, "source": r.source,
                    "detail": r.detail} for r in (*finder_rubric, *extra)],
        "population": {side: {"matches": len(results[side].matches),
                              "distinct_dates": len({c.date for c in results[side].matches})}
                       for side in sides},
        "cells": cells,
        "prereg_draft": draft_name,
    }
    out(f"Session: {out_dir}")
    # Written last, so report.md really is "what was printed", session line included.
    (out_dir / "result.json").write_text(json.dumps(_jsonable(result), indent=1, default=str) + "\n")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
    return result


def sessions_dir() -> Path:
    return llm_data_dir() / SESSIONS_DIR_NAME


def main(argv: list[str] | None = None) -> None:
    from src.foundation.utils.config_loader import load_config
    from src.llm.strategy_spec.ground import load_spec
    from src.models.dataset import HOLDOUT_END, HoldoutError
    from src.signals.moving_averages.features.panel import read_panel

    parser = argparse.ArgumentParser(prog="python -m src.llm.strategy_spec.look")
    parser.add_argument("spec", type=Path, help="a spec JSON, or an elicitation transcript")
    parser.add_argument("--panel-dir", type=Path, default=None,
                        help="feature panel cache (default: the configured features dir)")
    parser.add_argument("--ma", default=None, choices=list(MA_COLUMNS),
                        help="which moving average to test against (the spec has no structured "
                             f"slot; an MA finder defaults to {DEFAULT_MA})")
    parser.add_argument("--detector", default=None, help="finder to use (default: from the spec's `uses`)")
    parser.add_argument("--seed", type=int, default=0, help="bootstrap seed (recorded)")
    parser.add_argument("--cost-bps", type=float, default=None,
                        help=f"round-trip cost in bps (default {ROUND_TRIP_COST_BPS:g}, DESIGN §6.10)")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD (default: the whole cached window)")
    parser.add_argument("--end", default=None, help=f"YYYY-MM-DD, at most {HOLDOUT_END.date()} (the default)")
    args = parser.parse_args(argv)

    end = args.end or str(HOLDOUT_END.date())
    try:
        check_holdout(end)
    except HoldoutError as e:  # the carefully worded refusal, not a stack dump
        raise SystemExit(str(e))
    panel_dir = args.panel_dir or (
        Path(load_config().data_paths.features) / "moving_averages" / "ma_panel")
    panel = read_panel(panel_dir, start=args.start, end=end)
    if panel.empty:
        if not any(panel_dir.glob("year=*")):
            raise SystemExit(f"no panel at {panel_dir} — run the moving_averages build-panel command first")
        raise SystemExit(f"the cached panel at {panel_dir} has no rows between "
                         f"{args.start or 'its start'} and {end} — check --start/--end")

    try:
        look(load_spec(args.spec), panel, ma=args.ma, detector=args.detector,
             cost_bps=args.cost_bps, seed=args.seed)
    except (GroundingError, HoldoutError) as e:  # refusals are one-liners, not tracebacks
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()

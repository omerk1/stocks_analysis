"""M15 -- Synthesis (DESIGN.md lines ~1026-1027; PREREGISTRATION.md,
2026-09-25).

Track A diagnostic. DESIGN's own literal text: "take the surviving
Tier-1/Tier-2 claims and answer: do they combine additively, or are they
the same signal wearing different hats? Correlation matrix of the
surviving signals." This study has exactly one Tier-2 claim (M6.3's own
`slope_pctile_21_sma_50` extreme-tail finding) and zero Tier-1 -- a
literal reading makes this a degenerate 1x1 matrix, reported as the
primary honest finding (see `PREREGISTRATION.md`'s M15 entry). A
2026-09-25 addendum there (this study's own established porous-scope-
extension convention, e.g. M14's own VCP-only addendum) broadens the
comparison to also include M14's Tier-3 `pattern_context_reclaim_sma50_
vcp_only` cell -- the only other cell in the study with a comparably
strong profile (largest point estimate in this study's history, clears
whole-grid FDR at q=0.05 same as M6.3's cell).

Not a Pearson correlation -- these are two differently-shaped signals: a
continuous per-date decile rank (M6.3) vs. a rare binary event (M14's
VCP-only in-context reclaim). The check below asks the same underlying
question DESIGN poses ("same signal wearing different hats?") in the form
that actually applies to this pair: do M14's VCP reclaim events
disproportionately co-occur with M6.3's own extreme-slope tail, more than
the general reclaim population or the panel at large does?
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.modules import pattern_context
from src.signals.moving_averages.modules.slope_magnitude import (
    TAIL_DECILES,
    prepare as slope_magnitude_prepare,
    slope_pctile_column,
)

SLOPE_LOOKBACK = 50  # M6.3's own Tier-2 cell's lookback


def attach_slope_tail_flag(panel: pd.DataFrame) -> pd.DataFrame:
    """Runs M6.3's own `prepare()` unchanged and returns a (ticker, date,
    `in_slope_tail_50`) frame -- True/False/NA (NaN-preserving, CLAUDE.md
    invariant #9) for whether `slope_pctile_21_sma_50` falls in M6.3's own
    both-extremes-pooled `TAIL_DECILES`. Reuses M6.3's own code rather
    than reimplementing the decile transform, so there is no risk of a
    subtly different bucketing.
    """
    working = slope_magnitude_prepare(panel)
    decile_col = slope_pctile_column(SLOPE_LOOKBACK)
    working["in_slope_tail_50"] = working[decile_col].isin(TAIL_DECILES).where(working[decile_col].notna())
    return working[["ticker", "date", "in_slope_tail_50"]]


def build_reclaim_populations(panel: pd.DataFrame, patterns_all: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Reproduces M14's own populations unchanged, via its own
    `prepare()`/event-construction code:
    - `all_reclaims`: every eligible `above_sma_50` reclaim, in or out of
      any pattern context (39,452 events in this study's panel) --
      `in_pattern_context` is patterns-input-dependent, but this
      population only needs `is_reclaim_50` and the C2 match columns, so
      which `patterns` frame produced it doesn't matter here.
    - `any_pattern_reclaims`: the subset of those with `in_pattern_context`
      True against the pooled, all-7-types `patterns_all` input -- M14's
      own pooled decisive-test population (10,858 events per
      `FINDINGS.md`).
    - `vcp_reclaims`: the subset of `all_reclaims` with `in_pattern_context`
      True against a VCP-only `patterns` input (505 events per
      `FINDINGS.md`'s VCP addendum).
    """
    patterns_vcp = patterns_all[patterns_all["pattern_type"] == "vcp"]

    working_pooled = pattern_context.prepare(panel, patterns_all)
    events_pooled = working_pooled[working_pooled["is_reclaim_50"]]
    all_reclaims = events_pooled.dropna(subset=["fwd_ret_21", *pattern_context.C2_MATCH_COLS])
    any_pattern_reclaims = all_reclaims[all_reclaims["in_pattern_context"]]

    working_vcp = pattern_context.prepare(panel, patterns_vcp)
    events_vcp = working_vcp[working_vcp["is_reclaim_50"]]
    subset_vcp = events_vcp.dropna(subset=["fwd_ret_21", *pattern_context.C2_MATCH_COLS])
    vcp_reclaims = subset_vcp[subset_vcp["in_pattern_context"]]

    return {
        "all_reclaims": all_reclaims,
        "any_pattern_reclaims": any_pattern_reclaims,
        "vcp_reclaims": vcp_reclaims,
    }


def _tail_rate(events: pd.DataFrame, slope_flags: pd.DataFrame) -> tuple[float, int]:
    merged = events.merge(slope_flags, on=["ticker", "date"], how="left")
    tail = merged["in_slope_tail_50"].dropna()
    rate = float(tail.mean()) if len(tail) else float("nan")
    return rate, int(len(tail))


def overlap_enrichment(panel: pd.DataFrame, patterns_all: pd.DataFrame) -> dict:
    """The module's one diagnostic: does M14's VCP-reclaim population
    disproportionately co-occur with M6.3's own extreme-slope tail? Four
    rates are reported for honesty -- a naive read could look either
    enriched or not depending on which base rate one compares against:
    - `unconditional_rate`: tail-membership rate across the whole panel
      (should be close to 4/10 = 0.40 by construction, confirmed rather
      than assumed).
    - `all_reclaims_rate`: tail-membership rate across every eligible
      `above_sma_50` reclaim, in or out of any pattern context -- a
      reclaim in general could already skew toward one slope tail (e.g.
      an improving/rising slope), independent of any pattern involvement.
    - `any_pattern_reclaims_rate`: tail-membership rate restricted to
      reclaims inside *any* of the 7 pattern types (M14's own pooled
      population) -- isolates whether "near a confirmed pattern breakout"
      in general already explains any tail-rate shift, before asking
      whether VCP specifically adds anything beyond that.
    - `vcp_overlap_rate`: tail-membership rate specifically among VCP
      reclaim events.
    Three enrichment ratios (`vcp_overlap_rate` divided by each of the
    other three) answer the same question against three different, all
    honestly-reported baselines.
    """
    slope_flags = attach_slope_tail_flag(panel)
    populations = build_reclaim_populations(panel, patterns_all)

    unconditional = slope_flags["in_slope_tail_50"].dropna()
    unconditional_rate = float(unconditional.mean())

    all_reclaims_rate, n_all = _tail_rate(populations["all_reclaims"], slope_flags)
    any_pattern_rate, n_any_pattern = _tail_rate(populations["any_pattern_reclaims"], slope_flags)
    vcp_overlap_rate, n_vcp = _tail_rate(populations["vcp_reclaims"], slope_flags)

    def _ratio(base: float) -> float:
        return vcp_overlap_rate / base if base else float("nan")

    return {
        "n_panel_rows_with_slope_pctile": int(len(unconditional)),
        "unconditional_rate": unconditional_rate,
        "n_all_reclaims": int(len(populations["all_reclaims"])),
        "n_all_reclaims_with_slope_pctile": n_all,
        "all_reclaims_rate": all_reclaims_rate,
        "n_any_pattern_reclaims": int(len(populations["any_pattern_reclaims"])),
        "n_any_pattern_reclaims_with_slope_pctile": n_any_pattern,
        "any_pattern_reclaims_rate": any_pattern_rate,
        "n_vcp_reclaims": int(len(populations["vcp_reclaims"])),
        "n_vcp_reclaims_with_slope_pctile": n_vcp,
        "vcp_overlap_rate": vcp_overlap_rate,
        "enrichment_vs_unconditional": _ratio(unconditional_rate),
        "enrichment_vs_all_reclaims": _ratio(all_reclaims_rate),
        "enrichment_vs_any_pattern_reclaims": _ratio(any_pattern_rate),
    }

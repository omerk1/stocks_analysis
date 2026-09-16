"""Distribution-shape descriptive stats (DESIGN.md §6.11.1; CLAUDE.md
invariant #10).

Three additions to a module's standard result object, alongside the
existing mean/CI/cost numbers: hit rate (vs. the matched control already
in use), win/loss magnitude ratio, and skew. **Descriptive only** -- no
CI, no kill criterion, no `N_tests` contribution of their own (DESIGN
§6.11.1: turning these into three new hypothesis tests per cell would
multiply the FDR burden the whole-grid pass already struggles with).

Forward-only (invariant #10, added 2026-09-10): applies to modules run
from that date on. M1/M4/M11 predate it and are explicitly not
backfilled -- computing a new statistic on already-tiered weak results,
after the fact, is indistinguishable from statistic-shopping to rescue
them (DESIGN §6.11.1's own reasoning). §7.5 and M2 both ran after
2026-09-10 and should have reported this at the time; this module fills
that gap for both, not a backfill of anything pre-dating the invariant.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.stats.controls import c1_delta, c2_delta


def hit_rate_deltas(
    panel: pd.DataFrame,
    group_col: str,
    value_col: str,
    match_cols: list[str] | None = None,
    date_col: str = "date",
) -> dict:
    """P(value_col > 0 | event) vs. the matched control (DESIGN §6.11.1),
    reusing `c1_delta`/`c2_delta` unchanged on a boolean-cast column
    instead of the raw return -- no new inference machinery, same
    date-stratified matching the mean already uses (a naive proportion
    comparison would reintroduce the date-clustering problem the mean
    delta already solves). Also returns the event group's own raw hit
    rate (not a delta), the more directly interpretable number.

    `group_col` must already be a boolean column on `panel` (already
    lagged/eligible -- this function does no eligibility filtering of its
    own, same convention as `c1_delta`/`c2_delta`).
    """
    working = panel.copy()
    working["_is_positive"] = (working[value_col] > 0).astype(float)

    event_rows = working[working[group_col].astype(bool)]
    raw_hit_rate = event_rows["_is_positive"].mean() if len(event_rows) else float("nan")

    result = {
        "hit_rate": raw_hit_rate,
        "hit_rate_delta_c1": c1_delta(working, group_col, "_is_positive", date_col=date_col),
    }
    if match_cols:
        result["hit_rate_delta_c2"] = c2_delta(
            working, group_col, "_is_positive", match_cols=match_cols, date_col=date_col
        )
    return result


def distribution_shape(event_returns: pd.Series) -> dict:
    """Win/loss magnitude ratio and skew on an event group's own raw
    forward-return distribution (DESIGN §6.11.1: "one groupby-by-sign on
    data every module already computes" plus `.skew()`). Purely
    descriptive -- the event group's own distribution, no control needed
    (unlike hit rate, which is explicitly defined relative to a control).
    """
    values = event_returns.dropna()
    wins = values[values > 0]
    losses = values[values < 0]
    mean_win = wins.mean() if len(wins) else float("nan")
    mean_loss = losses.mean() if len(losses) else float("nan")
    win_loss_ratio = (
        mean_win / abs(mean_loss) if len(wins) and len(losses) and mean_loss != 0 else float("nan")
    )
    return {
        "win_loss_ratio": win_loss_ratio,
        "skew": values.skew() if len(values) >= 3 else float("nan"),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "mean_win": mean_win,
        "mean_loss": mean_loss,
    }

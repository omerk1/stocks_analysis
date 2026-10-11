"""Shared pieces of the divergence-context study's analysis scripts
(step 0, the hidden-forms prep looks): the dev-window event loader, the
descriptive shape-bucket edges, and small formatting helpers. One home so
a revision of the outcome buffer or the bucket edges cannot leave a stale
copy behind in a sibling script (the step-0 vs prep-look cross-checks rely
on the definitions being the same object)."""

from __future__ import annotations

import pandas as pd

from src.signals.divergences.study_universe import DEV_END

OUTCOME_END = "2021-11-30"  # 20-bar outcome window must not cross the holdout
# "Pullback + rebuild" shape: the counter-move gave back at least this
# fraction of the reference leg, over at least this many bars. Descriptive
# bucket edges, not pre-registered thresholds.
SHAPE_RETRACE_FRAC = 0.33
SHAPE_LEG2_BARS = 5


def load_dev_events(derived_conn) -> pd.DataFrame:
    """Every stored daily divergence confirmed inside the dev window, with
    its context scalars LEFT JOINed on (so rows the context builder
    skipped keep NaN scalars rather than disappearing)."""
    q = """
    SELECT d.*, c.impulse_gain_pct, c.interpeak_retrace_pct, c.interpeak_retrace_frac,
           c.leg2_gain_pct, c.leg2_bars, c.atr_contraction
    FROM divergences d LEFT JOIN divergence_context c ON c.divergence_id = d.id
    WHERE d.timeframe = 'daily' AND d.confirmed_at <= ?
    """
    events = pd.read_sql_query(q, derived_conn, params=[DEV_END + "T23:59:59"])
    events["p1_ts"] = pd.to_datetime(events["p1_date"])
    events["p2_ts"] = pd.to_datetime(events["p2_date"])
    events["year"] = events["p2_ts"].dt.year
    events["cell"] = events["form"] + "/" + events["direction"]
    return events


def fmt_quantiles(s: pd.Series, probs: tuple[float, ...] = (0.25, 0.5, 0.75, 0.9)) -> str:
    s = s.dropna()
    if s.empty:
        return "n=0"
    q = s.quantile(list(probs))
    parts = "  ".join(f"p{int(p * 100)}={v:.2f}" for p, v in zip(probs, q))
    return f"n={len(s)}  {parts}"

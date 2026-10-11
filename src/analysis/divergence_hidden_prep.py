"""Hidden-forms prep looks (Track A, exploratory) — the two looks that
PREREGISTRATION.md's "Hidden forms" section gates DC-B3/B4 on. Definitions
and gates pre-committed in EXPLORATION_LOG.md (2026-10-11) before anything
was computed.

(a) Co-occurrence: does a hidden event mark the same structure as a
    regular event of the opposite direction (the interleaving is
    structural: an uptrend pullback's hidden-bullish LOW pair brackets the
    regular-bearish second high), or is it independent information?
(b) Scalar fit: a pivot-to-pivot retrace fraction derived from the stored
    context scalars, as the hidden-geometry replacement for the v0 63-bar
    impulse normalization that step 0 showed mismeasures hidden structure
    (retrace_frac medians > 1).

Everything printed here is a bare rate on exploratory data: input for
deciding whether DC-B3/B4 get drafted, never a finding. Read-only over
`divergences` + `divergence_context`; no DB writes, no caches.

Co-occurrence flags are STRUCTURE-level descriptors, not point-in-time
features: `counterpart_any`/`counterpart_same_ind` can reflect a regular
confirmation that lands after the hidden event's own `confirmed_at`, and
the dev-window load truncates counterparts confirming after DEV_END (a
small undercount at the window margin — rows past the holdout boundary are
not read). `counterpart_confirmed_first` is the
as-of-the-hidden-confirmation variant; any DC-B3/B4 covariate use must
build on that ordering, not the structure-level flags.

Usage: python -m src.analysis.divergence_hidden_prep
"""

from __future__ import annotations

import pandas as pd

import numpy as np

from src.analysis.divergence_study_common import (
    OUTCOME_END,
    SHAPE_LEG2_BARS,
    SHAPE_RETRACE_FRAC,
    classify_shape,
    fmt_quantiles,
    load_dev_events,
)
from src.foundation.market_common import derived_db
from src.signals.divergences.study_universe import (
    DEV_END,
    DEV_START,
    membership_intervals,
    pit_member_mask,
)

# A hidden event and the regular event marking the other side of the same
# swing run in opposite directions: the uptrend that prints hidden-bullish
# LOW pairs prints regular-bearish HIGH pairs, and mirrored.
MIRROR = {"bullish": "bearish", "bearish": "bullish"}

COOCCURRENCE_FLAGS = (
    "counterpart_any", "counterpart_same_ind", "counterpart_confirmed_first",
    "inside_hidden_any", "inside_hidden_same_ind",
)

# A trend leg this small (as a fraction of p1's close) is a data glitch,
# not structure: the ratio would be defined but astronomically large,
# escaping both the NaN rate and any sane quantile.
TREND_LEG_EPS = 1e-6

HIDDEN_SHAPE_LABELS = (
    "shallow (extension-analogue)",
    "deep+slow (pullback-analogue)",
    "deep-fast",
)


def hidden_fit_retrace_frac(events: pd.DataFrame) -> pd.Series:
    """Pivot-to-pivot retrace fraction: counter-move / trend-leg, derived
    from the stored scalars (DESIGN's ratios-at-analysis-time rule).

    For a LOW pair (direction bullish) the trend leg is the advance p1 ->
    interpeak high (stored as interpeak_retrace_pct of p1) and the
    counter-move is the decline interpeak high -> p2 (leg2_gain_pct of the
    high), so the ratio is leg2 * (1 + retrace_pct) / retrace_pct. HIGH
    pairs (bearish) mirror with (1 - retrace_pct).

    NaN wherever an input is NaN, the trend leg is near zero
    (TREND_LEG_EPS), or the row is not a hidden event — the decomposition
    only means "retracement depth of the trend leg" for hidden geometry;
    on regular rows it would be defined garbage, so it is masked out
    rather than left for a mixed-frame consumer to ingest (invariant #9's
    where/mask discipline, applied to the feature's domain too).
    """
    retrace = events["interpeak_retrace_pct"]
    leg2 = events["leg2_gain_pct"]
    level_factor = (1.0 - retrace).where(events["direction"] == "bearish", 1.0 + retrace)
    frac = leg2 * level_factor / retrace
    defined = (
        retrace.notna() & leg2.notna() & (retrace > TREND_LEG_EPS)
        & (events["form"] == "hidden")
    )
    return frac.where(defined)


def classify_hidden_shape(frac: pd.Series, leg2_bars: pd.Series) -> pd.Series:
    """Three-way shape bucket on the hidden-fit fraction (step 0's edges,
    descriptive only); NA discipline lives in the shared classifier."""
    return classify_shape(frac, leg2_bars, HIDDEN_SHAPE_LABELS)


def attach_cooccurrence(events: pd.DataFrame, max_batch_tickers: int = 200) -> pd.DataFrame:
    """Adds the five boolean columns in COOCCURRENCE_FLAGS.

    Hidden rows: `counterpart_any` / `counterpart_same_ind` — a regular
    event of the mirrored direction (any indicator / this row's indicator)
    has its p2 strictly inside this row's (p1, p2) interval;
    `counterpart_confirmed_first` — such a counterpart (any indicator) was
    already confirmed by this row's own `confirmed_at`.
    Regular rows: `inside_hidden_any` / `inside_hidden_same_ind` — this
    row's p2 lies strictly inside some mirrored-direction hidden row's
    interval. Boundaries are exclusive: a shared pivot date is not
    "between the pivots".

    Vectorized merges over (ticker, mirrored direction) do all five flags
    — no per-ticker loop, only the needed columns carried, and the merge
    runs over ticker batches so the intermediate per-ticker hidden ×
    regular cross product (which the interval filter then prunes) stays
    bounded as the event base grows.
    """
    events = events.copy()
    for col in COOCCURRENCE_FLAGS:
        events[col] = False

    conf_ts = pd.to_datetime(events["confirmed_at"])
    hidden_mask = events["form"] == "hidden"
    hidden = pd.DataFrame(
        {
            "h_idx": events.index[hidden_mask],
            "ticker": events.loc[hidden_mask, "ticker"].to_numpy(),
            "direction": events.loc[hidden_mask, "direction"].to_numpy(),
            "h_ind": events.loc[hidden_mask, "indicator"].to_numpy(),
            "h_p1": events.loc[hidden_mask, "p1_ts"].to_numpy(),
            "h_p2": events.loc[hidden_mask, "p2_ts"].to_numpy(),
            "h_conf": conf_ts[hidden_mask].to_numpy(),
        }
    )
    regular_mask = events["form"] == "regular"
    regular = pd.DataFrame(
        {
            "r_idx": events.index[regular_mask],
            "ticker": events.loc[regular_mask, "ticker"].to_numpy(),
            # keyed by the hidden direction it mirrors
            "direction": events.loc[regular_mask, "direction"].map(MIRROR).to_numpy(),
            "r_ind": events.loc[regular_mask, "indicator"].to_numpy(),
            "r_p2": events.loc[regular_mask, "p2_ts"].to_numpy(),
            "r_conf": conf_ts[regular_mask].to_numpy(),
        }
    )

    tickers = hidden["ticker"].unique()
    n_batches = max(1, -(-len(tickers) // max_batch_tickers))
    for batch in np.array_split(tickers, n_batches):
        batch_set = set(batch)
        h = hidden[hidden["ticker"].isin(batch_set)]
        r = regular[regular["ticker"].isin(batch_set)]
        pairs = h.merge(r, on=["ticker", "direction"])
        pairs = pairs[(pairs["r_p2"] > pairs["h_p1"]) & (pairs["r_p2"] < pairs["h_p2"])]
        same_ind = pairs[pairs["h_ind"] == pairs["r_ind"]]

        events.loc[pairs["h_idx"].unique(), "counterpart_any"] = True
        events.loc[same_ind["h_idx"].unique(), "counterpart_same_ind"] = True
        events.loc[
            pairs.loc[pairs["r_conf"] <= pairs["h_conf"], "h_idx"].unique(),
            "counterpart_confirmed_first",
        ] = True
        events.loc[pairs["r_idx"].unique(), "inside_hidden_any"] = True
        events.loc[same_ind["r_idx"].unique(), "inside_hidden_same_ind"] = True
    return events


def _rate_line(label: str, frame: pd.DataFrame, flag: str) -> str:
    n = len(frame)
    k = int(frame[flag].sum())
    dates_with = set(frame.loc[frame[flag], "p2_date"])
    dates_without = set(frame.loc[~frame[flag], "p2_date"])
    rate = k / n if n else float("nan")
    # "only without": dates hosting no flagged row at all — the
    # conservative disagreement-cell N (events cluster; a date carrying
    # both kinds of rows is not evidence unique to either).
    return (f"  {label:52s} {k}/{n} = {rate:.1%}  "
            f"(p2 dates with: {len(dates_with)}, without: {len(dates_without)}, "
            f"only without: {len(dates_without - dates_with)})")


def _scopes(frame: pd.DataFrame):
    """The two reporting scopes: everything in the dev-window load, and
    PIT index members with p2 inside the dev window proper."""
    dev = frame["p2_ts"] >= DEV_START
    return (
        ("raw, <= DEV_END", frame),
        (f"PIT index members, {DEV_START}..{DEV_END}", frame[frame["pit_member"] & dev]),
    )


def report_cooccurrence(events: pd.DataFrame) -> None:
    print("\n== Look (a): hidden/regular co-occurrence on the same structure ==")
    for scope, frame in _scopes(events):
        print(f"  -- {scope} --")
        hidden = frame[frame["form"] == "hidden"]
        regular = frame[frame["form"] == "regular"]
        for direction, grp in hidden.groupby("direction"):
            mirrored = MIRROR[direction]
            print(_rate_line(f"hidden/{direction} w/ regular/{mirrored} p2 inside (any ind)",
                             grp, "counterpart_any"))
            print(_rate_line(f"hidden/{direction} w/ regular/{mirrored} p2 inside (same ind)",
                             grp, "counterpart_same_ind"))
            print(_rate_line(f"hidden/{direction} w/ counterpart conf-ordered (confirmed first)",
                             grp, "counterpart_confirmed_first"))
        for direction, grp in regular.groupby("direction"):
            mirrored = MIRROR[direction]
            print(_rate_line(f"regular/{direction} inside a hidden/{mirrored} window (any ind)",
                             grp, "inside_hidden_any"))
            print(_rate_line(f"regular/{direction} inside a hidden/{mirrored} window (same ind)",
                             grp, "inside_hidden_same_ind"))


def report_disagreement_outcomes(events: pd.DataFrame) -> None:
    print(f"\n== Look (a) outcome peek (confirmed <= {OUTCOME_END}; BARE RATES, not findings;"
          " within-form comparisons only) ==")
    sub = events[(events["form"] == "hidden")
                 & (events["confirmed_at"] <= OUTCOME_END + "T23:59:59")].copy()
    sub = sub[sub["outcome_computed_through"].notna() & sub["invalidated"].notna()]
    for flag in ("counterpart_any", "counterpart_confirmed_first"):
        print(f"  -- split by {flag} --")
        for (direction, has), grp in sub.groupby(["direction", flag]):
            label = "with counterpart" if has else "hidden alone"
            print(f"  hidden/{direction:8s} {label:18s} n={len(grp):6d} "
                  f"dates={grp['p2_date'].nunique():5d} "
                  f"invalidated={grp['invalidated'].mean():.1%} "
                  f"medMFE={grp['max_favorable_move_atr'].median():.2f} ATR")


_PROBS = (0.1, 0.25, 0.5, 0.75, 0.9)


def report_scalar_fit(events: pd.DataFrame) -> None:
    print("\n== Look (b): impulse-scalar fit for hidden geometry ==")
    print("  -- v0 misfit: interpeak_retrace_frac (63-bar impulse normalization) --")
    for cell, grp in events.groupby("cell"):
        v0 = grp["interpeak_retrace_frac"]
        defined = v0.notna()
        over1 = (v0 > 1).where(defined).mean()
        print(f"  {cell:18s} {fmt_quantiles(v0, _PROBS)}  frac>1: {over1:.1%}  "
              f"NaN: {(~defined).mean():.1%}")

    print("\n  -- candidate: pivot-to-pivot retrace fraction (counter-move / trend-leg) --")
    hidden = events[events["form"] == "hidden"]
    for direction, grp in hidden.groupby("direction"):
        cand = grp["hidden_fit_frac"]
        inputs_nan = grp["interpeak_retrace_pct"].isna() | grp["leg2_gain_pct"].isna()
        degenerate = (
            grp["interpeak_retrace_pct"].notna()
            & ~(grp["interpeak_retrace_pct"] > TREND_LEG_EPS)
        )
        print(f"  hidden/{direction:8s} {fmt_quantiles(cand, _PROBS)}")
        print(f"  {'':18s} NaN: {cand.isna().mean():.1%} "
              f"(inputs NaN: {inputs_nan.mean():.1%}, "
              f"trend-leg <= {TREND_LEG_EPS:g}: {degenerate.mean():.1%})")

    print(f"\n  -- shape split on the candidate (frac >= {SHAPE_RETRACE_FRAC},"
          f" counter-move bars >= {SHAPE_LEG2_BARS}; descriptive edges) --")
    for scope, frame in _scopes(hidden):
        print(f"  -- {scope} --")
        shape = classify_hidden_shape(frame["hidden_fit_frac"], frame["leg2_bars"])
        n_defined = shape.notna().groupby(frame["direction"]).sum()
        for (direction, cls), grp in frame.groupby(["direction", shape], dropna=True):
            print(f"  hidden/{direction:8s} {cls:30s} n={len(grp):6d} "
                  f"({len(grp) / n_defined[direction]:5.1%} of defined) "
                  f"dates={grp['p2_date'].nunique():5d}")


def main() -> None:
    raw_conn, derived_conn = derived_db.bootstrap_cli(lambda conn: None)
    events = load_dev_events(derived_conn)
    events["pit_member"] = pit_member_mask(events, membership_intervals(raw_conn))
    events["hidden_fit_frac"] = hidden_fit_retrace_frac(events)
    events = attach_cooccurrence(events)

    print(f"dev-window events (confirmed <= {DEV_END}): {len(events)}; "
          f"per cell:\n{events.groupby('cell').size().to_string()}")
    report_cooccurrence(events)
    report_disagreement_outcomes(events)
    report_scalar_fit(events)

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

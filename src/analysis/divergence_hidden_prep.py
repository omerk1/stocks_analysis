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
as-of-the-hidden-confirmation variant (with a strict-< companion,
`counterpart_confirmed_strictly_first`, keeping same-bar ties visible);
any DC-B3/B4 covariate use must build on that ordering, not the
structure-level flags.

Usage: python -m src.analysis.divergence_hidden_prep
"""

from __future__ import annotations

import pandas as pd

import numpy as np

from src.analysis.divergence_study_common import (
    OUTCOME_END,
    SHAPE_LEG2_BARS,
    SHAPE_RETRACE_FRAC,
    attach_pit_membership,
    classify_shape,
    fmt_quantiles,
    load_dev_events,
)
from src.foundation.market_common import derived_db
from src.signals.divergences.study_universe import DEV_END, DEV_START

# A hidden event and the regular event marking the other side of the same
# swing run in opposite directions: the uptrend that prints hidden-bullish
# LOW pairs prints regular-bearish HIGH pairs, and mirrored.
MIRROR = {"bullish": "bearish", "bearish": "bullish"}

COOCCURRENCE_FLAGS = (
    "counterpart_any", "counterpart_same_ind",
    "counterpart_confirmed_first", "counterpart_confirmed_strictly_first",
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
    undefined = hidden_fit_undefined_reasons(events)
    return frac.where(~undefined.any(axis=1))


def hidden_fit_undefined_reasons(events: pd.DataFrame) -> pd.DataFrame:
    """The component masks behind hidden_fit_retrace_frac's NaNs, one
    boolean column per reason. The single source of truth for both the
    scalar's mask and the report's NaN decomposition, so the printed
    breakdown cannot desynchronize from the actual NaN rate."""
    retrace = events["interpeak_retrace_pct"]
    inputs_nan = retrace.isna() | events["leg2_gain_pct"].isna()
    return pd.DataFrame(
        {
            # The first two are mutually exclusive (degenerate requires
            # non-NaN inputs), so the printed decomposition can't sum past
            # the total NaN rate. `not_hidden_form` is the domain mask and
            # may overlap either.
            "inputs_nan": inputs_nan,
            "trend_leg_degenerate": ~inputs_nan & ~(retrace > TREND_LEG_EPS),
            "not_hidden_form": events["form"] != "hidden",
        },
        index=events.index,
    )


def classify_hidden_shape(frac: pd.Series, leg2_bars: pd.Series) -> pd.Series:
    """Three-way shape bucket on the hidden-fit fraction (step 0's edges,
    descriptive only); NA discipline lives in the shared classifier."""
    return classify_shape(frac, leg2_bars, HIDDEN_SHAPE_LABELS)


def attach_cooccurrence(events: pd.DataFrame, max_batch_tickers: int = 200) -> pd.DataFrame:
    """Adds the six boolean columns in COOCCURRENCE_FLAGS.

    Hidden rows: `counterpart_any` / `counterpart_same_ind` — a regular
    event of the mirrored direction (any indicator / this row's indicator)
    has its p2 strictly inside this row's (p1, p2) interval;
    `counterpart_confirmed_first` — such a counterpart (any indicator) was
    already confirmed by this row's own `confirmed_at` (<=, matching the
    study's `confirmed_at <= as_of` knowability convention: a counterpart
    confirming on the same bar is knowable at that close);
    `counterpart_confirmed_strictly_first` — the same with strict <, so
    the share of same-bar ties is visible rather than folded in.
    Regular rows: `inside_hidden_any` / `inside_hidden_same_ind` — this
    row's p2 lies strictly inside some mirrored-direction hidden row's
    interval. Boundaries are exclusive: a shared pivot date is not
    "between the pivots".

    Vectorized merges over (ticker, mirrored direction) do all six flags
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

    # Sort both sides by ticker once; each batch is then a contiguous
    # slice (no repeated full-frame isin scans).
    hidden = hidden.sort_values("ticker", kind="stable", ignore_index=True)
    regular = regular.sort_values("ticker", kind="stable", ignore_index=True)
    h_tickers = hidden["ticker"].to_numpy()
    r_tickers = regular["ticker"].to_numpy()
    tickers = np.unique(h_tickers)
    n_batches = max(1, -(-len(tickers) // max_batch_tickers))
    for batch in np.array_split(tickers, n_batches):
        if len(batch) == 0:
            continue
        h = hidden.iloc[
            np.searchsorted(h_tickers, batch[0]) : np.searchsorted(h_tickers, batch[-1], side="right")
        ]
        r = regular.iloc[
            np.searchsorted(r_tickers, batch[0]) : np.searchsorted(r_tickers, batch[-1], side="right")
        ]
        pairs = h.merge(r, on=["ticker", "direction"])
        pairs = pairs[(pairs["r_p2"] > pairs["h_p1"]) & (pairs["r_p2"] < pairs["h_p2"])]
        same_ind = pairs[pairs["h_ind"] == pairs["r_ind"]]

        events.loc[pairs["h_idx"].unique(), "counterpart_any"] = True
        events.loc[same_ind["h_idx"].unique(), "counterpart_same_ind"] = True
        events.loc[
            pairs.loc[pairs["r_conf"] <= pairs["h_conf"], "h_idx"].unique(),
            "counterpart_confirmed_first",
        ] = True
        events.loc[
            pairs.loc[pairs["r_conf"] < pairs["h_conf"], "h_idx"].unique(),
            "counterpart_confirmed_strictly_first",
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
            n_first = int(grp["counterpart_confirmed_first"].sum())
            # Per-event, not per-pair: counts events whose conf-ordering
            # rests ONLY on a same-bar tie (no strictly-earlier
            # counterpart exists) — the case where <= vs < would matter.
            n_tie_only = n_first - int(grp["counterpart_confirmed_strictly_first"].sum())
            tie_share = n_tie_only / n_first if n_first else float("nan")
            print(f"  {'':52s} (conf-ordered only via a same-bar tie: "
                  f"{n_tie_only}/{n_first} = {tie_share:.1%})")
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
    # The False bucket means different things per flag: no counterpart
    # structure at all vs none CONFIRMED YET at the hidden event's own
    # confirmation — same label for both would invite comparing
    # differently-composed buckets.
    labels = {
        "counterpart_any": ("hidden alone", "with counterpart"),
        "counterpart_confirmed_first": ("none confirmed yet", "w/ conf-ordered cpart"),
    }
    for flag, (label_without, label_with) in labels.items():
        print(f"  -- split by {flag} --")
        for (direction, has), grp in sub.groupby(["direction", flag]):
            label = label_with if has else label_without
            print(f"  hidden/{direction:8s} {label:21s} n={len(grp):6d} "
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
        dates = grp.loc[defined, "p2_date"].nunique()
        print(f"  {cell:18s} {fmt_quantiles(v0, _PROBS)}  dates={dates}  "
              f"frac>1: {over1:.1%}  NaN: {(~defined).mean():.1%}")

    print("\n  -- candidate: pivot-to-pivot retrace fraction (counter-move / trend-leg) --")
    hidden = events[events["form"] == "hidden"]
    for direction, grp in hidden.groupby("direction"):
        cand = grp["hidden_fit_frac"]
        reasons = hidden_fit_undefined_reasons(grp)
        dates = grp.loc[cand.notna(), "p2_date"].nunique()
        print(f"  hidden/{direction:8s} {fmt_quantiles(cand, _PROBS)}  dates={dates}")
        print(f"  {'':18s} NaN: {cand.isna().mean():.1%} "
              f"(inputs NaN: {reasons['inputs_nan'].mean():.1%}, "
              f"trend-leg <= {TREND_LEG_EPS:g}: {reasons['trend_leg_degenerate'].mean():.1%})")

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
    events = attach_pit_membership(events, raw_conn)
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

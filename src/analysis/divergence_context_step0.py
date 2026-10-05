"""Step 0 of the divergence-context study (Track A, exploratory):
prevalence, entanglement, and cell-count feasibility. DESIGN:
docs/features/divergence-context/DESIGN.md ("Step 0 -- prevalence").

Three questions, all inside the development window (every event filter is
confirmed_at <= 2021-12-31; outcome tabulations use a 2021-11-30 buffer so
the 20-bar outcome window cannot cross the holdout; the entanglement pass
loads bars as_of 2021-12-31):

1. Does the "pullback + rebuild between the pivots" shape occur at
   meaningful frequency among divergences? (kill criterion: < ~5% of
   regular rows => the context study stops)
2. Among price-only pivot pairs WITH that shape, how often does a
   divergence print at all? (if ~always, a binary divergence x context
   design is untestable -- go continuous from the start)
3. Do the form x direction cells reach workable effective N (distinct p2
   dates), raw and PIT-index-filtered?

Everything printed here is a bare conditional rate on exploratory data:
input for designing the real test, never a finding.

Usage: python -m src.analysis.divergence_context_step0 [--entanglement-tickers N]
"""

from __future__ import annotations

import argparse
import random

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db, indicators
from src.foundation.market_common.models import PivotKind, Timeframe
from src.foundation.market_common.pivots import detect_pivots
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.context import IMPULSE_LOOKBACK_BARS

INDEX_NAMES = ["sp500", "nasdaq100"]

DEV_END = "2021-12-31"
OUTCOME_END = "2021-11-30"  # 20-bar outcome window must not cross the holdout
# "Pullback + rebuild" shape: the move between the pivots gave back at
# least this fraction of the impulse, over at least this many bars of
# rebuild. Descriptive bucket edges for step 0, not pre-registered
# thresholds.
SHAPE_RETRACE_FRAC = 0.33
SHAPE_LEG2_BARS = 5


def _load_dev_events(derived_conn) -> pd.DataFrame:
    q = """
    SELECT d.*, c.impulse_gain_pct, c.interpeak_retrace_pct, c.interpeak_retrace_frac,
           c.leg2_gain_pct, c.leg2_bars, c.atr_contraction
    FROM divergences d LEFT JOIN divergence_context c ON c.divergence_id = d.id
    WHERE d.timeframe = 'daily' AND d.confirmed_at <= ?
    """
    events = pd.read_sql_query(q, derived_conn, params=[DEV_END + "T23:59:59"])
    events["p2_ts"] = pd.to_datetime(events["p2_date"])
    events["year"] = events["p2_ts"].dt.year
    events["cell"] = events["form"] + "/" + events["direction"]
    return events


def _apply_renames_local(conn, membership: pd.DataFrame) -> pd.DataFrame:
    """Line-for-line mirror of ticker_renames.apply_renames (see
    _attach_pit_membership's docstring for why it isn't imported): each
    renamed symbol becomes its price symbol, only on rows whose interval
    overlaps the rename's verified [valid_from, valid_to] window."""
    renames = db.read_ticker_renames(conn)
    out = membership.copy()
    if renames.empty or out.empty:
        return out
    start = pd.to_datetime(out["start_date"])
    end = pd.to_datetime(out["end_date"]).fillna(pd.Timestamp.max)
    for r in renames.itertuples(index=False):
        if pd.isna(r.valid_from) or pd.isna(r.valid_to):
            continue
        hit = (
            (out["ticker"] == r.old_ticker)
            & (start <= pd.Timestamp(r.valid_to))
            & (end >= pd.Timestamp(r.valid_from))
        )
        out.loc[hit, "ticker"] = r.new_ticker
    return out


def _attach_pit_membership(events: pd.DataFrame, raw_conn) -> pd.DataFrame:
    """True where the event's ticker was an S&P 500 or Nasdaq-100 member on
    its own p2 date (point-in-time intervals, delisted members included).

    Intervals go through the rename mapping FIRST, same as every
    established membership consumer (src/models/dataset.py's
    membership_rows, relative_strength, breadth): divergences store
    events under the current price symbol (META), membership holds the
    historical one (FB) -- without the mapping, every renamed member's
    events silently read as non-members.

    `_apply_renames_local` mirrors ticker_renames.apply_renames exactly;
    importing the real one drags polygon_client in at module import,
    which not every environment's `polygon` package satisfies (flagged
    as a discussion item: that import should be lazy in ticker_renames).
    """
    intervals = pd.concat(
        [
            _apply_renames_local(raw_conn, db.read_index_membership(raw_conn, name))
            for name in INDEX_NAMES
        ],
        ignore_index=True,
    )
    intervals["start"] = pd.to_datetime(intervals["start_date"])
    intervals["end"] = pd.to_datetime(intervals["end_date"]).fillna(pd.Timestamp.max)
    by_ticker: dict[str, list[tuple]] = {}
    for row in intervals.itertuples(index=False):
        by_ticker.setdefault(row.ticker, []).append((row.start, row.end))

    def member(ev) -> bool:
        return any(s <= ev.p2_ts <= e for s, e in by_ticker.get(ev.ticker, ()))

    events = events.copy()
    events["pit_member"] = [member(ev) for ev in events.itertuples(index=False)]
    return events


def _fmt_quantiles(s: pd.Series) -> str:
    s = s.dropna()
    if s.empty:
        return "n=0"
    q = s.quantile([0.25, 0.5, 0.75, 0.9])
    return (
        f"n={len(s)}  p25={q.iloc[0]:.2f}  p50={q.iloc[1]:.2f}  "
        f"p75={q.iloc[2]:.2f}  p90={q.iloc[3]:.2f}"
    )


def report_prevalence(events: pd.DataFrame) -> None:
    print("\n== Q1: shape prevalence (interpeak_retrace_frac; events with context scalars) ==")
    has_ctx = events[events["interpeak_retrace_frac"].notna()]
    print(f"events in dev window: {len(events)}; with retrace_frac: {len(has_ctx)}")
    for cell, grp in has_ctx.groupby("cell"):
        shaped = grp[
            (grp["interpeak_retrace_frac"] >= SHAPE_RETRACE_FRAC)
            & (grp["leg2_bars"] >= SHAPE_LEG2_BARS)
        ]
        frac = len(shaped) / len(grp) if len(grp) else float("nan")
        print(f"  {cell:18s} retrace_frac: {_fmt_quantiles(grp['interpeak_retrace_frac'])}")
        print(
            f"  {'':18s} shape (frac>={SHAPE_RETRACE_FRAC}, leg2_bars>={SHAPE_LEG2_BARS}): "
            f"{len(shaped)}/{len(grp)} = {frac:.1%}  (distinct p2 dates: {shaped['p2_date'].nunique()})"
        )
        print(f"  {'':18s} atr_contraction: {_fmt_quantiles(grp['atr_contraction'])}")


def report_cells(events: pd.DataFrame) -> None:
    print("\n== Q3: cell counts and effective N (dev window) ==")
    for label, frame in (("raw", events), ("PIT index members", events[events["pit_member"]])):
        print(f"  -- {label} --")
        summary = frame.groupby("cell").agg(
            rows=("id", "count"), dates=("p2_date", "nunique"), tickers=("ticker", "nunique")
        )
        print(summary.to_string())
    print("\n  rows per year x cell (raw):")
    per_year = events.pivot_table(index="year", columns="cell", values="id", aggfunc="count").fillna(0).astype(int)
    print(per_year.to_string())


def report_outcomes(events: pd.DataFrame) -> None:
    print(f"\n== descriptive outcome tabulation (confirmed <= {OUTCOME_END}; BARE RATES, not findings) ==")
    sub = events[events["confirmed_at"] <= OUTCOME_END + "T23:59:59"].copy()
    # Rate and n must share one denominator: rows with a walked outcome
    # window AND a non-null invalidated flag.
    sub = sub[sub["outcome_computed_through"].notna() & sub["invalidated"].notna()]
    # Three-way split, not two: a deep retrace with a fast (< SHAPE_LEG2_BARS)
    # rebuild is NOT "extension/no reset" -- lumping it there contaminated
    # the contrast this tabulation previews.
    defined = sub["interpeak_retrace_frac"].notna()
    deep = sub["interpeak_retrace_frac"] >= SHAPE_RETRACE_FRAC
    rebuilt = sub["leg2_bars"] >= SHAPE_LEG2_BARS
    sub["shape"] = pd.Series(pd.NA, index=sub.index, dtype="object")
    sub.loc[defined & ~deep, "shape"] = "extension"
    sub.loc[defined & deep & rebuilt, "shape"] = "pullback+rebuild"
    sub.loc[defined & deep & ~rebuilt, "shape"] = "deep-fast"
    for (cell, shape), grp in sub.groupby(["cell", "shape"], dropna=True):
        inval = grp["invalidated"].mean()
        mfe = grp["max_favorable_move_atr"].median()
        print(
            f"  {cell:18s} {shape:17s} n={len(grp):6d} dates={grp['p2_date'].nunique():5d} "
            f"invalidated={inval:.1%} medMFE={mfe:.2f} ATR"
        )


def report_entanglement(raw_conn, derived_conn, n_tickers: int, seed: int = 42) -> None:
    print(f"\n== Q2: entanglement sample ({n_tickers} tickers, as_of {DEV_END}) ==")
    config = DivergenceConfig()
    tickers = [
        r[0] for r in derived_conn.execute(
            "SELECT DISTINCT ticker FROM divergences WHERE timeframe='daily'"
        )
    ]
    random.seed(seed)
    sample = random.sample(tickers, min(n_tickers, len(tickers)))

    # Filter on p2_date, NOT confirmed_at: the question is whether a
    # divergence exists off this swing at all, and a pair near DEV_END
    # whose divergence only confirms weeks later would otherwise count as
    # shaped-without-divergence, biasing the rate down at the boundary.
    stored = pd.read_sql_query(
        "SELECT ticker, p2_date, direction, form FROM divergences "
        "WHERE timeframe='daily' AND direction='bearish' AND form='regular' AND p2_date <= ?",
        derived_conn, params=[DEV_END + "T23:59:59"],
    )
    stored_by_ticker = {t: set(pd.to_datetime(g["p2_date"])) for t, g in stored.groupby("ticker")}

    shaped_pairs = 0
    shaped_with_div = 0
    for ticker in sample:
        try:
            bars, _ = data_mod.load_and_validate(
                raw_conn, ticker, Timeframe.DAILY, as_of=DEV_END, basis=config.price_basis
            )
        except Exception:
            continue
        if len(bars) < config.min_bars:
            continue
        atr = indicators.atr(bars, config.atr_period)
        warm = min(config.warmup_bars, max(len(bars) - 2, 0))
        close_s = bars["close"].iloc[warm:]
        atr_s = atr.iloc[warm:]
        pivots = detect_pivots(
            close_s, threshold_fn=lambda i: config.price_pivot_atr_mult * atr_s.iloc[i]
        )
        highs = [p for p in pivots if p.kind == PivotKind.HIGH]
        div_dates = stored_by_ticker.get(ticker, set())
        close_full = bars["close"]
        for k in range(len(highs) - 1):
            p1, p2 = highs[k], highs[k + 1]
            if p2.bar_index - p1.bar_index < config.min_pivot_span_bars:
                continue
            if p2.value <= p1.value:  # regular-bearish price geometry only
                continue
            # Positions in the FULL bars frame (pivot bar_index is in the
            # warmup-sliced space), so the impulse window and the
            # insufficient-lookback rule match context.py's exactly: with
            # fewer than IMPULSE_LOOKBACK_BARS before p1 the shape is
            # UNDEFINED and the pair is excluded -- never a quietly
            # shorter window, same NaN discipline as the stored scalars
            # (which Q1's denominator relies on).
            full1 = p1.bar_index + warm
            full2 = p2.bar_index + warm
            if full1 < IMPULSE_LOOKBACK_BARS:
                continue
            between = close_full.iloc[full1 : full2 + 1]
            impulse = p1.value - close_full.iloc[full1 - IMPULSE_LOOKBACK_BARS : full1 + 1].min()
            if impulse <= 0:
                continue
            retrace_frac = (p1.value - between.min()) / impulse
            leg2_bars = (full2 - full1) - int(between.to_numpy().argmin())
            if retrace_frac < SHAPE_RETRACE_FRAC or leg2_bars < SHAPE_LEG2_BARS:
                continue
            shaped_pairs += 1
            p2_ts = pd.Timestamp(p2.timestamp)
            if any(abs((p2_ts - d).days) <= 5 for d in div_dates):
                shaped_with_div += 1

    rate = shaped_with_div / shaped_pairs if shaped_pairs else float("nan")
    print(
        f"  higher-high pairs with pullback+rebuild shape: {shaped_pairs}; "
        f"with a regular-bearish divergence within 5 days: {shaped_with_div} ({rate:.1%})"
    )
    print("  (if this is ~100%, the binary divergence x context interaction is untestable)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--entanglement-tickers", type=int, default=300)
    args = parser.parse_args()

    raw_conn, derived_conn = derived_db.bootstrap_cli(lambda conn: None)

    events = _load_dev_events(derived_conn)
    events = _attach_pit_membership(events, raw_conn)
    report_prevalence(events)
    report_cells(events)
    report_outcomes(events)
    report_entanglement(raw_conn, derived_conn, args.entanglement_tickers)

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()

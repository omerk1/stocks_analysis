"""Track-A R/R sweep over the divergence event base — strategy-form payoffs.

Registration-lite: the grid, strategy form, controls, metrics and kill
criterion are pre-committed in docs/features/divergence-context/
EXPLORATION_LOG.md (entry dated 2026-10-10) BEFORE any payoff was
computed. Everything here is Track A exploration: no multiple-testing
correction, nothing a finding, no tradeable claim. The only promotion
path for a surviving region is a DRAFT DC-B5 pre-registration presented
to the user.

The question (different from DC-B1/B2's means): a stop at the event's own
invalidation level transforms the payoff distribution — a rule can have
positive expectancy where unconditional-return means showed nothing.

Payoffs are recomputed from bars (loaded as_of DEV_END, fail-closed
`data_end`), never from the stored 20-bar lifecycle fields. Walk
semantics follow `src/models/labels/barriers.py`: gap-through fills at
the open, same-bar target+stop tie resolves to the stop, incomplete
windows censor unless the ticker delisted (then the terminal return is
kept and flagged — invariant #4).

Usage:
  python -m src.analysis.divergence_rr_sweep build    # walk bars, cache per-trade parquet
  python -m src.analysis.divergence_rr_sweep report   # aggregate + kill-criterion readout
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common import indicators
from src.foundation.market_common.price_disputes import DISPUTED_DAYS, DisputedDay
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.matching import classify_context
from src.signals.divergences.study_universe import membership_intervals, pit_member_mask

DEV_START = "2010-01-01"
DEV_END = "2021-12-31"
DEV_YEARS = 12.0

ATR_PERIOD = 14
MAX_HOLD = 63
HOLDS = (21, 63)
TARGET_MULTS = (1.0, 2.0, 3.0, None)  # None = time exit only
EPS_PRIMARY = 0.25  # stop epsilon, in ATRs beyond the pair extreme
EPS_SENSITIVITY = (0.10, 0.50)  # primary variant only
DEGENERATE_R_ATR = 0.1  # R below this many ATRs -> R-multiples are noise

COST_RT_PRIMARY = 0.0020  # 20 bps round trip (invariant #8), the kill-criterion cost
COST_RT_LIQUID = 0.0010   # annotated liquid-core variant

DUR_EDGES = (25, 45)  # pre-committed fixed bins: <=25 / 26-45 / >=46
MIN_CONTROL_CELL = 3  # control (dur_bin, month) cells thinner than this are uncovered
MIN_NEIGHBOR_DATES = 100  # sub-cells below this effective N don't vote on neighbor agreement
KILL_MIN_DATES = 500  # pre-committed effective-N floor for a surviving region

# Primary variant for the pre-committed kill criterion.
PRIMARY = "t2_h63"

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "derived" / "divergence_rr_sweep"

RESOLVED = {"target", "stop", "time", "delisted"}


def variant_names() -> list[str]:
    names = [f"t{int(m) if m else 'X'}_h{h}" for m in TARGET_MULTS for h in HOLDS]
    names += [f"e{int(e * 100)}_{PRIMARY}" for e in EPS_SENSITIVITY]
    return names


def variant_spec(name: str) -> tuple[float | None, int, float]:
    """(target_mult, hold, epsilon) for a variant name."""
    eps = EPS_PRIMARY
    if name.startswith("e"):
        eps_s, name = name.split("_", 1)
        eps = int(eps_s[1:]) / 100
    t_s, h_s = name.split("_")
    mult = None if t_s == "tX" else float(t_s[1:])
    return mult, int(h_s[1:]), eps


def classify3(retrace_frac, leg2_bars) -> str | None:
    """The sweep's three context buckets: the two frozen poles via the ONE
    canonical classifier, everything else with a defined retrace (buffer
    band + deep-fast) as 'other'. NaN retrace stays None (excluded,
    counted)."""
    if retrace_frac is None or pd.isna(retrace_frac):
        return None
    return classify_context(retrace_frac, leg2_bars) or "other"


# ---- loading ----


def load_events(derived_conn, by_ticker: dict) -> pd.DataFrame:
    q = """
    SELECT d.id, d.ticker, d.direction, d.form, d.indicator,
           d.p1_price, d.p2_price, d.p2_date, d.confirmed_at,
           d.strength, d.duration_bars,
           c.interpeak_retrace_frac, c.leg2_bars
    FROM divergences d JOIN divergence_context c ON c.divergence_id = d.id
    WHERE d.timeframe = 'daily' AND d.p2_date >= ? AND d.p2_date <= ?
    """
    ev = pd.read_sql_query(q, derived_conn, params=[DEV_START, DEV_END + "T23:59:59"])
    ev = ev[pit_member_mask(ev, by_ticker)].copy()
    ev["context_class3"] = [
        classify3(r, b) for r, b in zip(ev["interpeak_retrace_frac"], ev["leg2_bars"])
    ]
    ev["is_divergence"] = True
    ev = ev.rename(columns={"duration_bars": "dur"})
    return ev


def load_controls(derived_conn, by_ticker: dict) -> pd.DataFrame:
    q = """
    SELECT id, ticker, direction, regular_geometry,
           p1_price, p2_price, p2_date, confirmed_at, span_bars,
           interpeak_retrace_frac, leg2_bars
    FROM divergence_control_pairs
    WHERE timeframe = 'daily' AND has_divergence = 0
      AND p2_date >= ? AND p2_date <= ?
    """
    ct = pd.read_sql_query(q, derived_conn, params=[DEV_START, DEV_END + "T23:59:59"])
    ct = ct[pit_member_mask(ct, by_ticker)].copy()
    ct["context_class3"] = [
        classify3(r, b) for r, b in zip(ct["interpeak_retrace_frac"], ct["leg2_bars"])
    ]
    # Hidden-shaped controls are the regular_geometry=0 pairs.
    ct["form"] = np.where(ct["regular_geometry"] == 1, "regular", "hidden")
    ct["indicator"] = ""
    ct["strength"] = np.nan
    ct["is_divergence"] = False
    ct = ct.rename(columns={"span_bars": "dur"})
    return ct


def add_bins(frame: pd.DataFrame) -> pd.DataFrame:
    """dur_bin (fixed edges, both sides) and strength terciles per
    (form, indicator, direction) over the loaded PIT EVENTS — a dev-window
    full-sample statistic, used only to DEFINE cells (the sanctioned
    cell-defining-bin exception pre-committed in the log entry; same
    pattern as the frozen PREREGISTRATION's matching bins). Controls get
    no strength tercile (no indicator)."""
    frame = frame.copy()
    frame["dur_bin"] = np.where(
        frame["dur"] <= DUR_EDGES[0], 1, np.where(frame["dur"] <= DUR_EDGES[1], 2, 3)
    )
    frame["strength_t"] = np.nan
    ev = frame["is_divergence"]
    for (_f, _i, _d), grp in frame[ev].groupby(["form", "indicator", "direction"]):
        s = grp["strength"]
        q1, q2 = s.quantile(1 / 3), s.quantile(2 / 3)
        t = pd.Series(np.where(s <= q1, 1, np.where(s <= q2, 2, 3)), index=grp.index, dtype=float)
        t[s.isna()] = np.nan
        frame.loc[grp.index, "strength_t"] = t
    return frame


def delisted_flags(raw_conn) -> dict[str, bool | None]:
    """Per-ticker delisted-at-DEV_END flag, the DC-B1/B2 run's logic: a
    post-DEV_END delisting means the ticker was ALIVE at the boundary (its
    series end there is censoring); active=0 with unknown timing stays
    None so the walker's tolerance inference applies."""
    out: dict[str, bool | None] = {}
    for t, act, dl in raw_conn.execute("SELECT ticker, active, delisted_utc FROM tickers"):
        if act == 0 and dl is not None and str(dl)[:10] <= DEV_END:
            out[t] = True
        elif act == 0 and dl is None:
            out[t] = None
        else:
            out[t] = False
    return out


# ---- the walker ----


def walk_ticker(
    bars: pd.DataFrame,
    trades: pd.DataFrame,
    delisted: bool | None,
    data_end: str = DEV_END,
) -> pd.DataFrame:
    """Per-trade payoffs for one ticker, every variant from one set of
    sliding windows. `bars`: DatetimeIndex, open/high/low/close. Returns
    one row per input trade (index preserved): entry fields plus, per
    variant v: ret_R_{v} (gross R multiple), res_{v}, bars_{v}; and
    mfe_atr / mae_atr over the legal 63-bar window.

    Semantics (mirroring barriers.py): entry at the open of the first bar
    after confirmed_at (invariant #2); stop/target hits intrabar with
    gap-through fills at the open; same-bar target+stop tie -> stop; an
    incomplete window censors (no payoff, even if a barrier was hit early
    — keeping early hits biases hit rates near the boundary) unless the
    ticker delisted, in which case the walk resolves on the ticker's own
    last bar and a no-hit exit is the terminal close, kept and flagged."""
    end_ts = pd.Timestamp(data_end)
    if len(bars) and bars.index[-1] > end_ts:  # fail-closed, like forward_returns
        bars = bars[bars.index <= end_ts]
    n = len(bars)
    variants = variant_names()

    def empty_out() -> pd.DataFrame:
        out = pd.DataFrame(index=trades.index)
        out["entry_date"] = pd.NaT
        for c in ("entry", "atr_c", "stop", "R", "risk_frac", "mfe_atr", "mae_atr"):
            out[c] = np.nan
        for v in variants:
            out[f"ret_R_{v}"] = np.nan
            out[f"res_{v}"] = "never_entered"
            out[f"bars_{v}"] = np.nan
        return out

    if n == 0 or trades.empty:
        return empty_out()

    o = bars["open"].to_numpy(dtype=float)
    hi = bars["high"].to_numpy(dtype=float)
    lo = bars["low"].to_numpy(dtype=float)
    cl = bars["close"].to_numpy(dtype=float)
    atr = indicators.atr(bars, ATR_PERIOD).to_numpy(dtype=float)

    if delisted is None:  # no tickers-table information: tolerance inference
        delisted = bool(bars.index[-1] < end_ts - pd.Timedelta(days=7))

    pad = np.full(MAX_HOLD - 1, np.nan)
    wo = sliding_window_view(np.concatenate([o, pad]), MAX_HOLD)[:n]
    wh = sliding_window_view(np.concatenate([hi, pad]), MAX_HOLD)[:n]
    wl = sliding_window_view(np.concatenate([lo, pad]), MAX_HOLD)[:n]
    wc = sliding_window_view(np.concatenate([cl, pad]), MAX_HOLD)[:n]

    conf_ts = pd.to_datetime(trades["confirmed_at"]).to_numpy()
    entry_pos = bars.index.searchsorted(conf_ts, side="right")
    ok = (entry_pos >= 1) & (entry_pos < n)
    e = np.clip(entry_pos, 1, n - 1)  # placeholder positions for ~ok rows, masked below

    m = len(trades)
    entry = o[e]
    atr_c = atr[e - 1]  # ATR as known at the confirmation close
    avail = n - e  # bars from entry inclusive
    is_short = (trades["direction"] == "bearish").to_numpy()
    extreme = np.where(
        is_short,
        np.maximum(trades["p1_price"].to_numpy(float), trades["p2_price"].to_numpy(float)),
        np.minimum(trades["p1_price"].to_numpy(float), trades["p2_price"].to_numpy(float)),
    )

    two = wo[e], wh[e], wl[e], wc[e]  # (m, 63) windows at the entry rows
    to_, th_, tl_, tc_ = two
    rows = np.arange(m)
    sign = np.where(is_short, -1.0, 1.0)

    out = pd.DataFrame(index=trades.index)
    out["entry_date"] = pd.Series(bars.index.to_numpy()[e], index=trades.index).where(pd.Series(ok, index=trades.index))
    out["entry"] = np.where(ok, entry, np.nan)
    out["atr_c"] = np.where(ok, atr_c, np.nan)

    for v in variants:
        mult, hold, eps = variant_spec(v)
        stop = extreme + np.where(is_short, 1.0, -1.0) * eps * atr_c
        R = sign * (entry - stop)
        base_bad = ~ok
        no_atr = ok & ~(np.isfinite(atr_c) & (atr_c > 0) & np.isfinite(entry) & (entry > 0))
        invalid = ok & ~no_atr & ~(R > 0)
        degen = ok & ~no_atr & (R > 0) & (R < DEGENERATE_R_ATR * atr_c)
        live = ok & ~no_atr & ~invalid & ~degen

        # Hits inside the hold window; NaN padding compares False.
        W = slice(0, hold)
        if mult is None:
            reach_t = np.zeros((m, hold), dtype=bool)
            gap_t = reach_t
            target = np.full(m, np.nan)
        else:
            target = entry + sign * mult * R
            reach_t = np.where(is_short[:, None], tl_[:, W] <= target[:, None], th_[:, W] >= target[:, None])
            gap_t = np.where(is_short[:, None], to_[:, W] <= target[:, None], to_[:, W] >= target[:, None])
        reach_s = np.where(is_short[:, None], th_[:, W] >= stop[:, None], tl_[:, W] <= stop[:, None])
        gap_s = np.where(is_short[:, None], to_[:, W] >= stop[:, None], to_[:, W] <= stop[:, None])

        first_t = np.where(reach_t.any(axis=1), reach_t.argmax(axis=1), hold)
        first_s = np.where(reach_s.any(axis=1), reach_s.argmax(axis=1), hold)
        idx_t = np.minimum(first_t, hold - 1)
        idx_s = np.minimum(first_s, hold - 1)
        same_bar = (first_t == first_s) & (first_t < hold)
        t_by_gap = same_bar & gap_t[rows, idx_t]
        target_first = (first_t < first_s) | t_by_gap
        stop_first = (first_s < first_t) | (same_bar & ~t_by_gap)
        hit_col = np.where(target_first, first_t, np.where(stop_first, first_s, hold))

        complete = avail >= hold
        # Hits past the ticker's own last bar can't happen (padding is NaN),
        # so for a delisted, incomplete window the walk resolves naturally;
        # an incomplete window on a LIVE ticker is right-censored outright.
        censored = live & ~complete & (not delisted)
        resolves = live & ~censored
        hit_valid = resolves & (hit_col < hold)

        t_open = to_[rows, idx_t]
        s_open = to_[rows, idx_s]
        t_fill = np.where(is_short, np.minimum(t_open, target), np.maximum(t_open, target))
        s_fill = np.where(is_short, np.maximum(s_open, stop), np.minimum(s_open, stop))
        last_col = np.clip(np.minimum(avail, hold) - 1, 0, hold - 1)
        time_fill = tc_[rows, last_col]

        exit_price = np.where(
            hit_valid & target_first, t_fill, np.where(hit_valid & stop_first, s_fill, time_fill)
        )
        held = np.where(hit_valid, hit_col + 1, np.minimum(avail, hold))

        ret_R = np.where(resolves, sign * (exit_price - entry) / R, np.nan)
        # A corrupt exit fill (NaN bar inside the ticker's own data) stays
        # NaN in ret_R: a data hole, distinct from censoring (res says how
        # it ended; the aggregation drops NaN returns and counts them).
        res = np.select(
            [base_bad, no_atr, invalid, degen, censored,
             hit_valid & target_first, hit_valid & stop_first, resolves & ~complete],
            ["never_entered", "no_atr", "invalid", "degenerate", "censored",
             "target", "stop", "delisted"],
            default="time",
        )
        out[f"ret_R_{v}"] = ret_R
        out[f"res_{v}"] = res
        out[f"bars_{v}"] = np.where(resolves, held, np.nan)
        if v.startswith("e"):
            # The eps-sensitivity variants have their own R, so the
            # cost-in-R conversion needs their own risk fraction.
            out[f"risk_frac_{v.split('_', 1)[0]}"] = np.where(live, R / entry, np.nan)
        if v == PRIMARY:
            out["stop"] = np.where(live, stop, np.nan)
            out["R"] = np.where(live, R, np.nan)
            out["risk_frac"] = np.where(live, R / entry, np.nan)
            # MFE/MAE in ATR over the (legal) 63-bar window, where it resolves.
            with np.errstate(invalid="ignore"):
                mfe_px = np.where(is_short, np.nanmin(tl_, axis=1), np.nanmax(th_, axis=1))
                mae_px = np.where(is_short, np.nanmax(th_, axis=1), np.nanmin(tl_, axis=1))
            out["mfe_atr"] = np.where(resolves, sign * (mfe_px - entry) / atr_c, np.nan)
            out["mae_atr"] = np.where(resolves, sign * (entry - mae_px) / atr_c, np.nan)

    return out


# ---- build ----


def build(args) -> None:
    raw_conn, derived_conn = derived_db.bootstrap_cli(lambda conn: None)
    config = DivergenceConfig()
    by_ticker = membership_intervals(raw_conn)

    ev = load_events(derived_conn, by_ticker)
    ct = load_controls(derived_conn, by_ticker)
    frame = add_bins(pd.concat([ev, ct], ignore_index=True))
    frame["p2_month"] = pd.to_datetime(frame["p2_date"]).dt.strftime("%Y-%m")
    frame["p2_year"] = pd.to_datetime(frame["p2_date"]).dt.year
    n_nan_ctx = int(frame["context_class3"].isna().sum())
    n_nan_conf = int(frame["confirmed_at"].isna().sum())
    frame = frame[frame["context_class3"].notna() & frame["confirmed_at"].notna()]
    print(f"PIT events {int(frame['is_divergence'].sum())}, controls {int((~frame['is_divergence']).sum())} "
          f"(excluded: {n_nan_ctx} NaN-retrace context, {n_nan_conf} missing confirmed_at)")

    flags = delisted_flags(raw_conn)
    walked, done = [], 0
    tickers = frame["ticker"].unique()
    for ticker, grp in frame.groupby("ticker"):
        bars, _report = data_mod.load_and_validate(
            raw_conn, ticker, Timeframe.DAILY, as_of=DEV_END, basis=config.price_basis
        )
        walked.append(grp.join(walk_ticker(bars, grp, flags.get(ticker), DEV_END)))
        done += 1
        if done % 200 == 0:
            print(f"  walked {done}/{len(tickers)} tickers")

    trades = pd.concat(walked, ignore_index=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "trades.parquet"
    trades.to_parquet(path, index=False)
    res = trades[f"res_{PRIMARY}"].value_counts()
    print(f"cached {len(trades)} trades -> {path}\nprimary-variant resolution mix:\n{res.to_string()}")
    raw_conn.close()
    derived_conn.close()


# ---- aggregation / report ----


def net_returns(trades: pd.DataFrame, variant: str, cost_rt: float) -> pd.Series:
    """Per-trade net R: gross R multiple minus the round-trip cost
    expressed in R (cost fraction / per-trade risk fraction, invariant #8).
    NaN wherever the trade didn't resolve. The eps-sensitivity variants
    carry their own risk fraction (their R differs from the primary's)."""
    rf_col = f"risk_frac_{variant.split('_', 1)[0]}" if variant.startswith("e") else "risk_frac"
    return trades[f"ret_R_{variant}"] - cost_rt / trades[rf_col]


def control_means(ct: pd.DataFrame, variant: str, cost_rt: float) -> pd.Series:
    """Mean net R per (direction, form, context_class3, dur_bin, p2_month)
    control cell, cells thinner than MIN_CONTROL_CELL dropped (uncovered)."""
    ct = ct[ct[f"res_{variant}"].isin(RESOLVED) & ct[f"ret_R_{variant}"].notna()]
    net = net_returns(ct, variant, cost_rt)
    g = net.groupby([ct["direction"], ct["form"], ct["context_class3"], ct["dur_bin"], ct["p2_month"]])
    means = g.mean()
    return means[g.size() >= MIN_CONTROL_CELL]


def adjusted(ev: pd.DataFrame, ctrl_mean: pd.Series, variant: str, cost_rt: float) -> pd.DataFrame:
    """Event trades with `net` (own net R) and `adj` (net R minus the
    matched control cell's mean — the invariant-#5 delta). Trades in an
    uncovered control cell get NaN adj; coverage is reported, and every
    aggregate over `adj` is implicitly month+duration reweighted by the
    event cell's own composition."""
    ev = ev[ev[f"res_{variant}"].isin(RESOLVED) & ev[f"ret_R_{variant}"].notna()].copy()
    ev["net"] = net_returns(ev, variant, cost_rt)
    key = pd.MultiIndex.from_frame(ev[["direction", "form", "context_class3", "dur_bin", "p2_month"]])
    ev["ctrl"] = pd.Series(ctrl_mean.reindex(key).to_numpy(), index=ev.index)
    ev["adj"] = ev["net"] - ev["ctrl"]
    return ev


def shape_trio(x: pd.Series) -> dict:
    """Invariant #10: hit rate, win/loss magnitude ratio, skew —
    descriptive only, no CI, no N_tests contribution."""
    x = x.dropna()
    if x.empty:
        return {"hit": np.nan, "wl": np.nan, "skew": np.nan}
    w, l = x[x > 0], x[x < 0]
    wl = float(w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
    return {"hit": float((x > 0).mean()), "wl": wl, "skew": float(x.skew())}


def cell_table(ev_adj: pd.DataFrame, variant: str) -> pd.DataFrame:
    rows = []
    group_cols = ["direction", "form", "indicator", "context_class3", "strength_t", "dur_bin"]
    for key, g in ev_adj.groupby(group_cols, dropna=False):
        covered = g[g["adj"].notna()]
        trio = shape_trio(g["net"])
        rows.append({
            **dict(zip(group_cols, key)),
            "n": len(g),
            "n_dates": g["p2_date"].nunique(),
            "trades_per_year": round(len(g) / DEV_YEARS, 1),
            "gross_R": g[f"ret_R_{variant}"].mean(),
            "net_R": g["net"].mean(),
            "adj_R": covered["adj"].mean(),
            "coverage": len(covered) / len(g) if len(g) else np.nan,
            "exp_atr": (g[f"ret_R_{variant}"] * g["R"] / g["atr_c"]).mean(),
            **trio,
            "med_R": g["net"].median(),
            "p10_R": g["net"].quantile(0.10),
            "p90_R": g["net"].quantile(0.90),
            "mfe_mae": g["mfe_atr"].median() / g["mae_atr"].median() if g["mae_atr"].median() else np.nan,
        })
    return pd.DataFrame(rows)


def region_readout(ev_adj: pd.DataFrame) -> pd.DataFrame:
    """Kill-criterion evaluation per (direction x form x context) region at
    the primary variant: control-adjusted net expectancy, effective N,
    era-split signs (2010-15 vs 2016-21, and excluding 2020), and 3x3
    strength x duration neighbor agreement (sub-cells with >=
    MIN_NEIGHBOR_DATES distinct dates must share the headline's sign)."""
    rows = []
    for (d, f, c), g in ev_adj.groupby(["direction", "form", "context_class3"]):
        cov = g[g["adj"].notna()]
        head = cov["adj"].mean()
        n_dates = cov["p2_date"].nunique()
        era = {
            "2010_15": cov.loc[cov["p2_year"] <= 2015, "adj"].mean(),
            "2016_21": cov.loc[cov["p2_year"] >= 2016, "adj"].mean(),
            "ex2020": cov.loc[cov["p2_year"] != 2020, "adj"].mean(),
        }
        era_ok = all(np.isfinite(v) and np.sign(v) == np.sign(head) for v in era.values()) if np.isfinite(head) and head != 0 else False
        sub = cov.groupby(["strength_t", "dur_bin"])["adj"].agg(["mean"]).join(
            cov.groupby(["strength_t", "dur_bin"])["p2_date"].nunique().rename("nd")
        )
        voters = sub[sub["nd"] >= MIN_NEIGHBOR_DATES]
        neigh_ok = bool(len(voters)) and all(np.sign(voters["mean"]) == np.sign(head))
        survives = (
            np.isfinite(head) and head > 0 and n_dates >= KILL_MIN_DATES and era_ok and neigh_ok
        )
        rows.append({
            "direction": d, "form": f, "context": c,
            "adj_R": head, "net_R": cov["net"].mean(), "ctrl_R": cov["ctrl"].mean(),
            "n": len(g), "n_covered": len(cov), "n_dates": n_dates,
            **{f"adj_{k}": v for k, v in era.items()},
            "era_ok": era_ok, "neighbors": f"{int((np.sign(voters['mean']) == np.sign(head)).sum() if len(voters) else 0)}/{len(voters)}",
            "neigh_ok": neigh_ok, "survives": bool(survives),
        })
    return pd.DataFrame(rows).sort_values("adj_R", ascending=False)


def drop_disputed(
    trades: pd.DataFrame, disputes: tuple[DisputedDay, ...] = DISPUTED_DAYS
) -> tuple[pd.DataFrame, int, int]:
    """Exclude trades the price-disputes file says can't be trusted: every
    trade on a whole-history-disputed ticker (the vendors' series are
    different securities — a corrupt close would print as a monster
    R-multiple), and any trade whose walk window could overlap a per-day
    disputed bar (entry within [d-100, d+25] calendar days of disputed day
    d: 63 held bars ahead, ATR window behind). Vendor-blind, so slightly
    over-broad — fine for exploration, counted either way. (The DC-B1/B2
    run predates this filter; the repo's full per-window treatment is
    dataset.build_labels', logged as backlog for the signals modules.)"""
    whole = {d.ticker for d in disputes if d.date is None}
    keep = ~trades["ticker"].isin(whole)
    n_whole = int((~keep).sum())
    trades = trades[keep]
    per_day: dict[str, list[pd.Timestamp]] = {}
    for d in disputes:
        if d.date is not None:
            per_day.setdefault(d.ticker, []).append(pd.Timestamp(d.date))
    entry = pd.to_datetime(trades["entry_date"])
    hit = pd.Series(False, index=trades.index)
    for ticker, days in per_day.items():
        sel = trades["ticker"] == ticker
        if not sel.any():
            continue
        e = entry[sel]
        for ts in days:
            hit.loc[sel] |= (e >= ts - pd.Timedelta(days=100)) & (e <= ts + pd.Timedelta(days=25))
    n_window = int(hit.sum())
    return trades[~hit], n_whole, n_window


def report(args) -> None:
    trades = pd.read_parquet(CACHE_DIR / "trades.parquet")
    trades, n_whole, n_window = drop_disputed(trades)
    print(f"price-dispute exclusions: {n_whole} trades on whole-history-disputed tickers, "
          f"{n_window} with a walk window near a disputed day")
    ev = trades[trades["is_divergence"]]
    ct = trades[~trades["is_divergence"]]

    # Exclusion accounting at the primary variant.
    print("primary-variant resolution mix (events / controls):")
    mix = pd.concat([
        ev[f"res_{PRIMARY}"].value_counts().rename("events"),
        ct[f"res_{PRIMARY}"].value_counts().rename("controls"),
    ], axis=1)
    print(mix.fillna(0).astype(int).to_string())

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    readouts = {}
    for variant in variant_names():
        for cost, tag in ((COST_RT_PRIMARY, "20bps"), (COST_RT_LIQUID, "10bps")):
            cm = control_means(ct, variant, cost)
            ev_adj = adjusted(ev, cm, variant, cost)
            readouts[(variant, tag)] = ev_adj
            if variant == PRIMARY and cost == COST_RT_PRIMARY:
                cells = cell_table(ev_adj, variant)
                cells.to_csv(CACHE_DIR / "cells_primary.csv", index=False)

    print(f"\n== KILL-CRITERION READOUT — primary variant {PRIMARY}, eps {EPS_PRIMARY}, 20 bps ==")
    primary_adj = readouts[(PRIMARY, "20bps")]
    regions = region_readout(primary_adj)
    pd.set_option("display.width", 220)
    print(regions.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))
    regions.to_csv(CACHE_DIR / "regions_primary.csv", index=False)

    print("\n== region adj_R across variants (20 bps) ==")
    grid = {}
    for variant in variant_names():
        r = region_readout(readouts[(variant, "20bps")]).set_index(["direction", "form", "context"])
        grid[variant] = r["adj_R"]
    grid_df = pd.DataFrame(grid)
    print(grid_df.to_string(float_format=lambda x: f"{x:+.3f}"))
    grid_df.to_csv(CACHE_DIR / "regions_by_variant.csv")

    print("\n== region adj_R at 10 bps (annotated, primary variant) ==")
    r10 = region_readout(readouts[(PRIMARY, "10bps")]).set_index(["direction", "form", "context"])
    print(r10["adj_R"].to_string(float_format=lambda x: f"{x:+.4f}"))

    survivors = regions[regions["survives"]]
    if survivors.empty:
        print("\nVERDICT: the sweep is DEAD per the pre-committed criterion — no "
              "(direction x form x context) region clears all four rails.")
    else:
        print(f"\nVERDICT: {len(survivors)} region(s) clear the pre-committed rails — the ONLY next "
              "step is a DRAFT DC-B5 pre-registration presented to the user. Track A numbers stay here.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="walk bars and cache the per-trade parquet")
    sub.add_parser("report", help="aggregate the cache and print the kill-criterion readout")
    args = parser.parse_args()
    {"build": build, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()

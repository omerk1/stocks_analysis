"""Post-earnings drift beyond momentum: `docs/fundamentals/PREREGISTRATION.md` F1
(Track B, pre-registered 2026-10-16). Read the entry first; this module only
executes it.

    python -m src.analysis.earnings_drift --db data/raw/market_data.sqlite \
        --features data/models/features/sp500_fund

- **Events:** the session on which a quarter's own-history surprise
  (`sue_net_income`) first counts, i.e. its `known_at` (`fundamentals.quarter_features`),
  kept only if the ticker is an eligible cache row that day carrying that value.
- **Large:** at or above the 90th (at or below the 10th) percentile of every
  event's SUE over the previous 365 calendar days -- trailing, never
  full-sample (CLAUDE.md invariant 3) -- with at least `MIN_TRAILING_EVENTS`.
- **Outcome:** log total return from the open of t+1 to the close of t+H; a
  ticker that stops trading inside the window keeps its return to its last
  close (invariant 4); a live ticker whose window passes the data's end is
  dropped, never truncated. Rows whose window a disputed price day reaches are
  dropped (`dataset.drop_disputed`), event and control alike.
- **Control:** same-date eligible rows that aren't events within +/-5 sessions
  and whose current SUE isn't large, bucketed by `mom_12_1_rank` quintile x
  `mom_1_0_rank` tercile (robustness: x size or x volatility tercile). Delta =
  the event's return minus its bucket's mean control return (>= 5 controls).
- **S_H:** the date-weighted mean over event dates of each date's mean signed
  delta (+ positive surprises, - negative), with the date-block bootstrap's 99%
  interval (block 2H event dates) and the three verdicts against +/-10 bps.

Reads the databases read-only and the feature cache; writes nothing but its
printed report and, with `--out`, a JSON copy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.data_processing import db
from src.models import dataset
from src.models.features import cache, fundamentals
from src.models.inference import bootstrap_ratio
from src.models.metrics import block_length
from src.models.trading import three_verdict
from src.signals.moving_averages.stats.inference import InsufficientBlocksError

HORIZONS = (63, 21)          # primary first
CUTS = {"primary": 0.90, "wider": 0.80, "narrower": 0.95}   # upper cut; the lower is 1 - it
TRAILING_DAYS = 365
MIN_TRAILING_EVENTS = 200
EVENT_EXCLUSION_SESSIONS = 5
MIN_CONTROLS = 5
BAND = 0.001
CI = 0.99
N_BOOT = 1000              # registered
PRECISION_N_BOOT = 10_000  # a Monte Carlo check of the 99% ends (F2's addendum), not the verdict
COST_BPS = 10
FIRST_EVENT = "2011-01-01"
END = "2021-12-31"
ERAS = ((2011, 2016), (2017, 2021))
MATCH = {"primary": ("mom_12_1_rank", "mom_1_0_rank"),
         "size": ("mom_12_1_rank", "mom_1_0_rank", "log_dollar_volume_20d_rank"),
         "volatility": ("mom_12_1_rank", "mom_1_0_rank", "realized_vol_63_rank")}
BINS = {"mom_12_1_rank": 5, "mom_1_0_rank": 3, "log_dollar_volume_20d_rank": 3, "realized_vol_63_rank": 3}
KNOWN_AT_SLACK = 2       # business days from known_at to the event row (after-hours filings, holidays)
DELISTED_GAP = 5         # bars ending more than this many business days before the data's end: delisted


# ---------------------------------------------------------------- events

def sue_events(features: pd.DataFrame, fund: pd.DataFrame) -> pd.DataFrame:
    """(ticker, date, sue): one event per quarter, on the first cache row at
    most `KNOWN_AT_SLACK` business days after the quarter's `known_at` (the
    session its SUE first counts), if that row carries the quarter's value.
    A ticker that isn't an eligible row then (e.g. joins the index months
    later) has no event for that quarter, and a quarter superseded before
    its row (two filings days apart) leaves only the later one."""
    rows = features[["ticker", "date", "sue_net_income"]].dropna(subset=["sue_net_income"])
    rows = fundamentals._ns(rows, ["date"]).sort_values("date")
    known = fundamentals.quarter_features(fund)["sue_net_income"].dropna(subset=["known_at", "value"])
    known = fundamentals._ns(known[["ticker", "known_at", "value"]], ["known_at"]).sort_values("known_at")
    m = pd.merge_asof(known, rows, left_on="known_at", right_on="date", by="ticker", direction="forward")
    m = m[m["date"].notna()]
    day = lambda s: s.to_numpy().astype("datetime64[D]")
    prompt = np.busday_count(day(m["known_at"]), day(m["date"])) <= KNOWN_AT_SLACK
    same = np.isclose(m["value"], m["sue_net_income"], rtol=1e-4)
    out = m[prompt & same][["ticker", "date", "value"]].rename(columns={"value": "sue"})
    out = out.drop_duplicates(["ticker", "date"], keep="last")
    return out[out["date"] >= FIRST_EVENT].sort_values(["date", "ticker"], ignore_index=True)


def near_events(rows: pd.DataFrame, events: pd.DataFrame, sessions: int = EVENT_EXCLUSION_SESSIONS) -> pd.Series:
    """Whether each row is within `sessions` business days of one of its
    ticker's events (either side), aligned to `rows`: the controls'
    exclusion, counted on the calendar, not on the rows that happen to be
    eligible or event dates."""
    left = fundamentals._ns(rows[["ticker", "date"]], ["date"]).reset_index(names="_row").sort_values("date")
    ev = fundamentals._ns(events[["ticker", "date"]], ["date"]).rename(columns={"date": "ev"}).sort_values("ev")
    day = lambda s: s.to_numpy().astype("datetime64[D]")
    near = np.zeros(len(left), bool)
    for direction in ("backward", "forward"):
        m = pd.merge_asof(left, ev, left_on="date", right_on="ev", by="ticker", direction=direction)
        has = m["ev"].notna().to_numpy()
        gap = np.full(len(m), sessions + 1)
        gap[has] = np.abs(np.busday_count(day(m.loc[has, "date"]), day(m.loc[has, "ev"])))
        near |= gap <= sessions
    return pd.Series(near, index=left["_row"].to_numpy()).reindex(rows.index)


def trailing_cuts(events: pd.DataFrame, upper: float) -> pd.DataFrame:
    """Per event date: the `upper` and `1 - upper` quantiles of every event's
    SUE over the previous TRAILING_DAYS (strictly before the date); NaN with
    fewer than MIN_TRAILING_EVENTS."""
    ev = events.sort_values("date")
    dates, values = ev["date"].to_numpy(), ev["sue"].to_numpy(float)
    rows = []
    for d in np.unique(dates):
        lo = np.searchsorted(dates, d - np.timedelta64(TRAILING_DAYS, "D"), side="left")
        hi = np.searchsorted(dates, d, side="left")
        w = values[lo:hi]
        w = w[np.isfinite(w)]
        ok = len(w) >= MIN_TRAILING_EVENTS
        rows.append({"date": d, "hi": np.quantile(w, upper) if ok else np.nan,
                     "lo": np.quantile(w, 1 - upper) if ok else np.nan, "n_trailing": len(w)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- returns

def forward_returns(bars: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """(ticker, date, fwd): log(close at t+H / open at t+1) on each ticker's
    own bars. A ticker whose bars end more than DELISTED_GAP business days
    before the data's last date (delisted) and whose window runs past its
    last bar gets its last close (terminal return); any other window past
    its bars is NaN (a series that merely misses the last few days isn't a
    delisting)."""
    b = bars.sort_values(["ticker", "date"], ignore_index=True)
    g = b.groupby("ticker")
    entry = g["open"].shift(-1)
    exit_ = g["close"].shift(-horizon)
    day = lambda s: s.to_numpy().astype("datetime64[D]")
    last = g["date"].transform("max")
    delisted = pd.Series(np.busday_count(day(last), day(pd.Series(b["date"].max(), index=b.index)))
                         > DELISTED_GAP, index=b.index)
    exit_ = exit_.where(exit_.notna(), g["close"].transform("last").where(delisted))
    return b[["ticker", "date"]].assign(fwd=np.log(exit_ / entry))


# ---------------------------------------------------------------- the test

def _buckets(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    """One label per row: its per-date rank's bin in each column (ranks are
    in (0, 1]); NaN if any rank is."""
    parts = [np.ceil(frame[c] * BINS[c]).clip(1, BINS[c]) for c in columns]
    key = parts[0].astype("Int64").astype(str)
    for p in parts[1:]:
        key = key + "_" + p.astype("Int64").astype(str)
    return key.where(pd.concat(parts, axis=1).notna().all(axis=1))


def deltas(rows: pd.DataFrame, events: pd.DataFrame, cuts: pd.DataFrame, match: tuple[str, ...]) -> pd.DataFrame:
    """Large events with their matched delta. `rows`: every eligible cache row
    with `fwd`, the match ranks, `sue` and `near` (`near_events`: within the
    exclusion window of an event); `events`: (ticker, date, sue)."""
    ev = events.merge(cuts, on="date")
    ev["side"] = np.where(ev["sue"] >= ev["hi"], 1, np.where(ev["sue"] <= ev["lo"], -1, 0))
    large = ev[(ev["side"] != 0) & ev["hi"].notna()]
    # controls: not near an event of their own ticker, current SUE not large
    r = rows.merge(cuts[["date", "hi", "lo"]], on="date", how="inner")
    sue_large = (r["sue"] >= r["hi"]) | (r["sue"] <= r["lo"])
    r["bucket"] = _buckets(r, match)
    ctrl = r[~r["near"] & ~sue_large & r["fwd"].notna() & r["bucket"].notna()]
    stats = ctrl.groupby(["date", "bucket"])["fwd"].agg(["mean", "size"]).reset_index()
    out = large.merge(r[["ticker", "date", "fwd", "bucket"]], on=["ticker", "date"])
    out = out.merge(stats, on=["date", "bucket"], how="left")
    out = out[out["fwd"].notna() & (out["size"] >= MIN_CONTROLS)]
    out["delta"] = out["fwd"] - out["mean"]
    out["signed"] = out["side"] * out["delta"]
    day_mean = r.groupby("date")["fwd"].mean()
    out["raw_signed"] = out["side"] * (out["fwd"] - out["date"].map(day_mean))
    return out


def summarize(d: pd.DataFrame, value: str, horizon: int, precision: bool = False) -> dict:
    """The date-weighted mean of `value` over event dates, its 99% interval
    and verdict, plus the descriptive shape (never judged); with `precision`,
    the interval again at PRECISION_N_BOOT draws. Its own bootstrap call,
    not `trading.per_date_diff`: the eras here are the drift study's own."""
    if d.empty:
        return {"n_events": 0, "verdict": "inconclusive"}
    by_date = d.groupby("date")[value].mean()
    try:
        b = bootstrap_ratio(by_date, pd.Series(1.0, index=by_date.index), block_length(horizon), True,
                            n_rows=len(d), n_boot=N_BOOT, ci=CI)
        precise = bootstrap_ratio(by_date, pd.Series(1.0, index=by_date.index), block_length(horizon), True,
                                  n_rows=len(d), n_boot=PRECISION_N_BOOT, ci=CI) if precision else None
    except InsufficientBlocksError:  # too few event dates for 3 blocks: no interval, no verdict
        return {"n_events": int(len(d)), "n_dates": int(len(by_date)), "point": float(by_date.mean()),
                "verdict": "inconclusive", "too_few_dates": True}
    x = d[value]
    wins, losses = x[x > 0], x[x <= 0]
    years = (d["date"].max() - d["date"].min()).days / 365.25
    year = by_date.index.year
    return {
        "point": b.point_estimate, "ci_low": b.ci_low, "ci_high": b.ci_high, "verdict":
            three_verdict(b.ci_low, b.ci_high, BAND), "n_events": int(len(d)), "n_dates": int(b.n_dates),
        **({"precision_check": {"n_boot": PRECISION_N_BOOT, "ci_low": precise.ci_low, "ci_high": precise.ci_high,
                                "verdict": three_verdict(precise.ci_low, precise.ci_high, BAND)}} if precise else {}),
        "events_per_year": float(len(d) / years) if years > 0 else np.nan,
        "cost_per_year": float(len(d) / years * COST_BPS / 1e4) if years > 0 else np.nan,
        "hit_rate": float((x > 0).mean()),
        "win_loss_ratio": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0
        else np.nan,
        "skew": float(x.skew()),
        "by_era": {f"{a}-{z}": float(by_date[(year >= a) & (year <= z)].mean()) for a, z in ERAS},
        "by_year": {int(y): float(v) for y, v in by_date.groupby(year).mean().items()},
    }


def run(features: pd.DataFrame, fund: pd.DataFrame, bars: pd.DataFrame, sources: dict[str, str]) -> dict:
    events = sue_events(features, fund)
    base = features[["ticker", "date", "sue_net_income", *BINS]].rename(columns={"sue_net_income": "sue"})
    base = fundamentals._ns(base, ["date"])
    base["near"] = near_events(base, events)
    cuts = {name: trailing_cuts(events, upper) for name, upper in CUTS.items()}
    report = {"n_events_all": int(len(events)), "horizons": {}}
    for h in HORIZONS:
        fwd = fundamentals._ns(forward_returns(bars, h), ["date"])
        kept, n_dropped = dataset.drop_disputed(fwd, sources, bars, h)
        rows = base.merge(kept, on=["ticker", "date"], how="left")
        per_h = {"n_disputed_dropped": int(n_dropped)}
        for cut_name in CUTS:
            for match_name, match in MATCH.items():
                if cut_name != "primary" and match_name != "primary":
                    continue
                d = deltas(rows, events, cuts[cut_name], match)
                key = f"{cut_name}/{match_name}"
                # the precision check on the judged readout only
                per_h[key] = {"signed": summarize(d, "signed", h, precision=True),
                              "positive": summarize(d[d["side"] == 1], "delta", h),
                              "negative": summarize(d[d["side"] == -1], "delta", h),
                              "raw_signed": summarize(d, "raw_signed", h)}
        report["horizons"][h] = per_h
    return report


def _line(name: str, s: dict) -> str:
    if not s.get("n_events"):
        return f"    {name:11s} no events"
    if s.get("too_few_dates"):
        return (f"    {name:11s} {s['point']:+.3%}, {s['n_events']} events on {s['n_dates']} dates: too few for "
                "3 date blocks -> inconclusive (no interval)")
    return (f"    {name:11s} {s['point']:+.3%} [{s['ci_low']:+.3%}, {s['ci_high']:+.3%}] -> {s['verdict']}; "
            f"{s['n_events']} events on {s['n_dates']} dates ({s['events_per_year']:.0f}/yr, cost "
            f"{s['cost_per_year']:.1%}/yr at {COST_BPS} bps); hit {s['hit_rate']:.1%}, win/loss "
            f"{s['win_loss_ratio']:.2f}, skew {s['skew']:+.2f}; eras "
            + ", ".join(f"{e} {v:+.3%}" for e, v in s["by_era"].items())
            + (f"; at {s['precision_check']['n_boot']} draws [{s['precision_check']['ci_low']:+.3%}, "
               f"{s['precision_check']['ci_high']:+.3%}] -> {s['precision_check']['verdict']}"
               if "precision_check" in s else ""))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.analysis.earnings_drift")
    p.add_argument("--db", type=Path, required=True, help="market-data SQLite (opened read-only)")
    p.add_argument("--features", type=Path, required=True, help="a build-features output directory")
    p.add_argument("--out", type=Path, default=None, help="also write the report as JSON")
    args = p.parse_args(argv)
    dataset.check_holdout(END)
    features = cache.read_feature_cache(args.features)
    tickers = sorted(features["ticker"].unique())
    conn = db.get_connection(f"file:{args.db}?mode=ro", uri=True)
    try:
        fund, _ = fundamentals.load_tables(conn, tickers, END)
        bars = dataset.read_bars_bulk(conn, tickers, dataset.LABEL_BASIS, "2010-01-01", END,
                                      fallback=dataset.LABEL_FALLBACK)
    finally:
        conn.close()
    report = run(features, fund, bars, bars.attrs["ticker_sources"])
    print(f"F1 post-earnings drift beyond momentum (Track B): {report['n_events_all']:,} SUE events from "
          f"{FIRST_EVENT}; {CI:.0%} interval, band +/-{BAND:.2%} per event")
    for h, per_h in report["horizons"].items():
        print(f"H{h}{' (primary)' if h == HORIZONS[0] else ''}: {per_h['n_disputed_dropped']} rows dropped for "
              "disputed days")
        for key, r in per_h.items():
            if key == "n_disputed_dropped":
                continue
            print(f"  {key}")
            for name in ("signed", "positive", "negative", "raw_signed"):
                print(_line(name, r[name]))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())

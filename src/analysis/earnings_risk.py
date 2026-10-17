"""Earnings as risk: `docs/fundamentals/PREREGISTRATION.md` F3 (Track B,
pre-registered 2026-10-16). Read the entry first; this module only executes it.

    python -m src.analysis.earnings_risk --db data/raw/market_data.sqlite \
        --features data/models/features/sp500_fund

No new fit: it re-reads F2's archived predictions (`trading.PREREGISTERED["F2"]`,
the trials `close-scorecard F2` judges). For each H = 21 cell, the reference
model's (the combined model without the company-financials group) daily
top-20 by EV in ATR units, two ways:

- **unrestricted:** the top 20 of every row (the control);
- **excluding:** the top 20 of the rows whose *expected* next earnings date
  (`days_to_earnings_expected`) is not inside the window (<= 21 sessions,
  0 = overdue counts as inside). Unknown (NaN) rows stay pickable. The
  next-best rows fill the basket.

D = excluding minus unrestricted, per date averaged over the 9 cells
(`trading.pooled_difference`), with the date-block bootstrap's 99% interval
and the three verdicts against +/-10 bps. Descriptive: the unrestricted picks
split by the flag (inside / outside / unknown: barrier rates, expectancy net
of 10 bps, R/R, win rate, skew), the flag's accuracy against the realized
reaction date (a label diagnostic only), the 16- and 26-session window
neighbours, per era and year, the F2 model's picks (secondary), and H = 63's
flag rates and split.

Reads the market-data DB read-only, the caches and the trial artifacts;
writes nothing but its printed report and, with `--out`, a JSON copy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.data_processing import db
from src.models import dataset, trading, trial_log
from src.models.ablation import cell_frame
from src.models.features import cache, fundamentals

EXPERIMENT = "F2"
SIDES = ("reference", "model")  # the reference is the registered one
VERDICT_HORIZON = 21
WINDOWS = (21, 16, 26)  # the registered window first, then its neighbours
K = 20
COST_BPS = 10
END = "2021-12-31"
PRECISION_N_BOOT = 10_000  # F2's addendum: a 99% end at 1,000 draws rests on ~5 tail draws
FLAGS = ("inside", "outside", "unknown")


def flag(days_to: pd.Series, window: int) -> pd.Series:
    """'inside' / 'outside' / 'unknown' from the expected sessions to the next
    earnings reaction (0 = overdue, inside; NaN = no history, unknown)."""
    return pd.Series(np.where(days_to.isna(), "unknown", np.where(days_to <= window, "inside", "outside")),
                     index=days_to.index)


def reactions(earnings: pd.DataFrame) -> pd.DataFrame:
    """(ticker, reaction_date) sorted for `realized_inside`, dates in ns."""
    react = fundamentals._ns(earnings.dropna(subset=["reaction_date"]), ["reaction_date"])
    return react[["ticker", "reaction_date"]].sort_values("reaction_date", ignore_index=True)


def realized_inside(rows: pd.DataFrame, react: pd.DataFrame, window: int) -> pd.Series:
    """Whether the realized next reaction date after t is 1 .. `window`
    business days out, counted as the flag counts the expected one
    (`np.busday_count`, so 1 = the entry session, as a flag of 1 is inside).
    `react` from `reactions`. Uses the realized date, so it is future
    information on day t: a label diagnostic of the flag only."""
    left = fundamentals._ns(rows[["ticker", "date"]], ["date"]).reset_index(names="_row").sort_values("date")
    m = pd.merge_asof(left, react, left_on="date", right_on="reaction_date", by="ticker",
                      direction="forward", allow_exact_matches=False)
    known = m["reaction_date"].notna().to_numpy()
    gap = np.full(len(m), -1)
    day = lambda s: s.to_numpy().astype("datetime64[D]")
    gap[known] = np.busday_count(day(m.loc[known, "date"]), day(m.loc[known, "reaction_date"]))
    inside = pd.Series(known & (gap >= 1) & (gap <= window), index=m["_row"].to_numpy())
    return inside.reindex(rows.index)


def exclusion_verdict(baskets: dict, sc) -> dict:
    """D = excluding minus unrestricted, pooled over the cells per date, with
    its CI at the registered draws, its three-way verdict, per era / year /
    cell means (on D's dates), and the interval again at `PRECISION_N_BOOT`
    draws (a Monte Carlo precision check of the 99% ends, not the verdict)."""
    _, readout = trading.pooled_readout(baskets, "excluding", "unrestricted", VERDICT_HORIZON, sc, sc.n_boot)
    precise, _ = trading.pooled_readout(baskets, "excluding", "unrestricted", VERDICT_HORIZON, sc, PRECISION_N_BOOT)
    return {**readout,
            "precision_check": {"n_boot": PRECISION_N_BOOT, "ci_low": precise.ci_low, "ci_high": precise.ci_high,
                                "verdict": trading.three_verdict(precise.ci_low, precise.ci_high, sc.band)}}


def split_readout(picked: pd.DataFrame) -> dict:
    """The unrestricted picks by flag: share, trade stats net of `COST_BPS`
    pooled over the cells and per cell, and the flag's accuracy against the
    realized date. `trades_per_year` is per cell (one cell's daily top-k is
    one strategy), so the pooled count is divided by the number of cells."""
    n_years = picked["date"].nunique() / trading.TRADING_DAYS
    n_cells = picked["cell"].nunique()
    out = {"flag_share": {f: float((picked["flag"] == f).mean()) for f in FLAGS},
           "by_flag": {f: trading.trade_stats(g, COST_BPS, n_years * n_cells) for f, g in picked.groupby("flag")},
           "by_cell": {c: {f: trading.trade_stats(x, COST_BPS, n_years) for f, x in g.groupby("flag")}
                       for c, g in picked.groupby("cell")}}
    inside, outside = picked["flag"] == "inside", picked["flag"] == "outside"
    out["flag_accuracy"] = {"inside_realized_inside": float(picked.loc[inside, "realized_inside"].mean()),
                            "outside_realized_outside": float(1 - picked.loc[outside, "realized_inside"].mean())}
    return out


def run(features: pd.DataFrame, earnings: pd.DataFrame, labels_dir, trials: pd.DataFrame, sc=None,
        artifacts_root=trial_log.ARTIFACTS_ROOT, require_clean: bool = True) -> dict:
    """The F3 readout for both of F2's models (`SIDES`), at every horizon of
    `sc`; the exclusion and its verdict at H = 21 only. One cell's
    predictions are in memory at a time."""
    sc = sc or trading.PREREGISTERED[EXPERIMENT]
    trading.check_features(sc, features)
    if pd.Timestamp(features["date"].max()) > pd.Timestamp(END):  # the holdout stays locked
        raise ValueError(f"the feature cache runs to {features['date'].max()}, past {END}")
    react = reactions(earnings[pd.to_datetime(earnings["reaction_date"]) <= pd.Timestamp(END)])
    d2e = features.set_index(["ticker", "date"])["days_to_earnings_expected"]
    report = {}
    for horizon in sc.horizons:
        windows = WINDOWS if horizon == VERDICT_HORIZON else ()
        baskets = {side: {w: {} for w in windows} for side in SIDES}
        split, all_rows = {side: [] for side in SIDES}, None
        for cell in sc.cells(horizon):
            labels = dataset.read_labels(labels_dir, horizon, cell=(cell.upper, cell.lower))
            tid = trading.registered_trial(sc, trials, cell, trading.trial_spec(sc, cell, features, labels),
                                           require_clean)
            if tid is None:
                raise ValueError(f"{sc.experiment_id} has no registered trial for H{horizon} "
                                 f"{cell.upper:g}/{cell.lower:g}")
            frame = cell_frame(features, labels)
            preds = pd.read_parquet(Path(artifacts_root) / tid / "predictions.parquet")
            preds["d2e"] = d2e.reindex(pd.MultiIndex.from_frame(preds[["ticker", "date"]])).to_numpy()
            if all_rows is None:  # the flag among every scored row (one cell's rows stand for all)
                all_rows = {side: flag(preds.loc[preds["model"] == name, "d2e"], horizon)
                            for side, name in (("model", "model"), ("reference", sc.reference))}
            name = f"{cell.upper:g}/{cell.lower:g}"
            every = trading.cell_picks(sc, cell, preds, frame, K)
            for side, p in every.items():
                p = p.merge(preds.loc[preds["model"] == (sc.reference if side == "reference" else "model"),
                                      ["ticker", "date", "d2e"]], on=["ticker", "date"])
                p["flag"] = flag(p["d2e"], horizon)
                p["realized_inside"] = realized_inside(p, react, horizon)
                split[side].append(p.assign(cell=name))
            for w in windows:
                excl = trading.cell_picks(sc, cell, preds, frame, K, keep=lambda p, w=w: ~(p["d2e"] <= w))
                for side in SIDES:
                    baskets[side][w][(cell.upper, cell.lower)] = {"excluding": trading.basket(excl[side]),
                                                                 "unrestricted": trading.basket(every[side])}
        per_side = {}
        for side in SIDES:
            out = split_readout(pd.concat(split[side], ignore_index=True))
            out["flag_share_all_rows"] = all_rows[side].value_counts(normalize=True).to_dict()
            if windows:
                out["windows"] = {w: exclusion_verdict(baskets[side][w], sc) for w in windows}
            per_side[side] = out
        report[horizon] = per_side
    return report


def report_lines(report: dict, band: float) -> list[str]:
    """The printed summary: the verdicts first, then the descriptive split."""
    pct = lambda x: f"{x:+.3%}"
    lines = [f"F3: top-{K} excluding an expected earnings date inside the window minus unrestricted, "
             f"99% CI, band +/-{band:.2%} per trade"]
    for horizon, sides in report.items():
        for side, out in sides.items():
            lines.append(f"H{horizon} {side}:")
            for w, v in out.get("windows", {}).items():
                tag = " (registered)" if w == WINDOWS[0] else " (neighbour)"
                lines.append(f"  window <= {w}{tag}: {pct(v['point_estimate'])} [{pct(v['ci_low'])}, "
                             f"{pct(v['ci_high'])}], n_dates {v['n_dates']} -> {v['verdict']}; "
                             f"cells positive {v['cells_positive']}/{len(v['by_cell'])}; by era "
                             + ", ".join(f"{e} {pct(x)}" for e, x in v["by_era"].items()))
                c = v["precision_check"]
                lines.append(f"    at {c['n_boot']} draws (precision check): [{pct(c['ci_low'])}, "
                             f"{pct(c['ci_high'])}] -> {c['verdict']}")
            share = ", ".join(f"{f} {out['flag_share'][f]:.1%}" for f in FLAGS)
            every = ", ".join(f"{f} {out['flag_share_all_rows'].get(f, 0):.1%}" for f in FLAGS)
            lines.append(f"  picks flagged: {share} (all rows: {every})")
            for f, s in out["by_flag"].items():
                lines.append(f"  {f:8s} n {s['n_trades']:6d}, dates {s['n_dates']:5d}: net {pct(s['expectancy'])}, "
                             f"win {s['win_rate']:.1%}, R/R {s['payoff_ratio']:.2f}, skew {s['skew']:+.2f}, "
                             f"target/stop/timeout {s['target_rate']:.0%}/{s['stop_rate']:.0%}/"
                             f"{s['timeout_rate']:.0%}")
            a = out["flag_accuracy"]
            lines.append(f"  flag accuracy (realized date): inside {a['inside_realized_inside']:.1%}, "
                         f"outside {a['outside_realized_outside']:.1%}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.analysis.earnings_risk")
    p.add_argument("--db", type=Path, required=True, help="market-data SQLite (opened read-only)")
    p.add_argument("--features", type=Path, required=True, help="the feature cache F2 was fitted on")
    p.add_argument("--labels", type=Path, default=Path("data/models/labels/sp500"))
    p.add_argument("--out", type=Path, default=None, help="also write the full report as JSON")
    args = p.parse_args(argv)
    dataset.check_holdout(END)
    features = cache.read_feature_cache(args.features)
    conn = db.get_connection(f"file:{args.db}?mode=ro", uri=True)
    try:
        _, earnings = fundamentals.load_tables(conn, sorted(features["ticker"].unique()), END)
    finally:
        conn.close()
    sc = trading.PREREGISTERED[EXPERIMENT]
    report = run(features, earnings, args.labels, trial_log.read_trials(), sc)
    print("\n".join(report_lines(report, sc.band)))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())

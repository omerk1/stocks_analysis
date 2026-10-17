"""Compare two run-scorecard experiments cell by cell (Track A, descriptive).

For every (horizon, upper, lower) cell both experiments logged, it rebuilds
each run's top-k picks (rank ev_atr) from the archived predictions on one
frame, puts a date-block CI on the per-date difference of their baskets
(new - old, gross), and reports the pick overlap next to each run's logged
readouts (vs market, vs B4, Sharpe, drawdown, ATR, eras, random-k). The
numbers behind docs/modeling/VALIDATION_HARNESS.md §9 step 2b:

    python3 scripts/compare_scorecard_runs.py S2 S1r --features data/models/features/sp500_s2
    python3 scripts/compare_scorecard_runs.py S1r S1b --features data/models/features/sp500_s2

Run from the repo root (it imports src.models); writes the per-readout table
to --out and prints the counts.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import dataset, trading, trial_log  # noqa: E402
from src.models.ablation import cell_frame, neither_returns  # noqa: E402
from src.models.features import cache  # noqa: E402
from src.models.inference import per_date_diff  # noqa: E402
from src.models.labels.barriers import REFERENCE_HORIZON, BarrierCell  # noqa: E402
from src.models.splits import walk_forward_folds  # noqa: E402

RANK = "ev_atr"
CI = 0.90
N_BOOT = 1000


def logged(trials: pd.DataFrame, experiment_id: str) -> dict[tuple, pd.Series]:
    """One ok row per cell, keyed (horizon, upper, lower); the first logged wins."""
    rows = trials[(trials["experiment_id"] == experiment_id) & (trials["status"] == "ok")]
    if rows.empty:
        raise SystemExit(f"no ok rows for {experiment_id!r}")
    rank = {json.loads(g).get("rank") for g in rows["feature_groups"]}
    if rank != {RANK}:
        raise SystemExit(f"{experiment_id!r} is ranked by {sorted(map(str, rank))}; this compares {RANK} runs only")
    out = {}
    for _, row in rows.iterrows():
        c = json.loads(row["cells"])[0]
        out.setdefault((c["horizon"], c["upper"], c["lower"]), row)
    return out


def predictions(row: pd.Series, artifacts_root: Path) -> pd.DataFrame:
    """The model's archived predictions; a rescore row points at the trial it rescored."""
    source = json.loads(row["feature_groups"]).get("rescored_from") or row["trial_id"]
    p = pd.read_parquet(artifacts_root / source / "predictions.parquet")
    return p[p["model"] == "model"].drop(columns="model")


def readouts(metrics: dict, k: int, tag: str, eras: tuple[str, str]) -> dict:
    x = metrics["by_k"][str(k)]
    model, market = x["model"], x["market"]
    early, late = eras
    return {
        f"{tag}_vs_mkt": x["vs_market"]["point_estimate"], f"{tag}_vs_mkt_lo": x["vs_market"]["ci_low"],
        f"{tag}_vs_mkt_hi": x["vs_market"]["ci_high"],
        f"{tag}_vs_b4": x["vs_reference"]["point_estimate"], f"{tag}_vs_b4_lo": x["vs_reference"]["ci_low"],
        f"{tag}_vs_b4_hi": x["vs_reference"]["ci_high"],
        f"{tag}_sharpe": model["portfolio"]["sharpe"], f"{tag}_dd": model["portfolio"]["max_drawdown"],
        f"{tag}_ann": model["portfolio"]["annual_return"], f"{tag}_atr": model["atr_pct"],
        f"{tag}_b4_exp": x["reference"]["costs"]["0"]["expectancy"],
        f"{tag}_era1": model["by_era"][early]["expectancy"] - market["by_era"][early]["expectancy"],
        f"{tag}_era2": model["by_era"][late]["expectancy"] - market["by_era"][late]["expectancy"],
        f"{tag}_random_sharpe": x["random"]["portfolio"]["sharpe"],
        "mkt_sharpe": market["portfolio"]["sharpe"], "mkt_dd": market["portfolio"]["max_drawdown"],
    }


def compare(new_id: str, old_id: str, features_dir: Path, labels_dir: Path, artifacts_root: Path) -> pd.DataFrame:
    trials = trial_log.read_trials()
    new, old = logged(trials, new_id), logged(trials, old_id)
    features = cache.read_feature_cache(features_dir)
    sc = trading.Scorecard()
    folds = walk_forward_folds(sc.test_years, sc.first_train_start)
    eras = tuple(f"{e[0]}-{e[-1]}" for e in sc.eras)     # trading.score_cell's by_era keys
    out = []
    for key in sorted(set(new) & set(old)):
        h, upper, lower = key
        cell = BarrierCell(h, upper, lower, REFERENCE_HORIZON)
        frame = cell_frame(features, dataset.read_labels(labels_dir, h, cell=(upper, lower)))
        neither, neither_atr = neither_returns(frame, folds), trading.neither_atr_returns(frame, folds)
        pn, po = predictions(new[key], artifacts_root), predictions(old[key], artifacts_root)
        mn, mo = json.loads(new[key]["metrics"]), json.loads(old[key]["metrics"])
        for k in sc.ks:
            a = trading.picks(pn, frame, cell, neither, k, RANK, neither_atr)
            b = trading.picks(po, frame, cell, neither, k, RANK, neither_atr)
            ba, bb = trading.basket(a).dropna(), trading.basket(b).dropna()
            dates = ba.index.intersection(bb.index)          # runs from different caches can differ on a few
            diff = per_date_diff(ba[dates], bb[dates], h, True, N_BOOT, CI, 0).summary()
            shared = len(a.merge(b, on=["date", "ticker"]))
            row = {"H": h, "cell": f"{upper:g}/{lower:g}", "k": k, "new_minus_old": diff["point_estimate"],
                   "lo": diff["ci_low"], "hi": diff["ci_high"], "dates_dropped": len(ba) + len(bb) - 2 * len(dates),
                   "pick_overlap": shared / max(len(a), len(b), 1)}
            row.update(readouts(mn, k, "new", eras))
            row.update(readouts(mo, k, "old", eras))
            out.append(row)
            print(f"H{h} {upper:g}/{lower:g} top-{k}: {diff['point_estimate']:+.3%} "
                  f"[{diff['ci_low']:+.3%}, {diff['ci_high']:+.3%}], overlap {row['pick_overlap']:.2f}", flush=True)
    return pd.DataFrame(out)


def summary(d: pd.DataFrame, new_id: str, old_id: str) -> None:
    pct = lambda v: f"{100 * v:+.2f}%"  # noqa: E731
    print(f"\n{new_id} - {old_id}: negative at {(d.new_minus_old < 0).sum()} of {len(d)}, "
          f"CI below zero at {(d.hi < 0).sum()}, above at {(d.lo > 0).sum()}; median {pct(d.new_minus_old.median())}, "
          f"mean size {pct(d.new_minus_old.abs().mean())}; overlap {d.pick_overlap.min():.2f}-{d.pick_overlap.max():.2f}")
    for tag, name in (("new", new_id), ("old", old_id)):
        print(f"{name}: vs market >0 at {(d[f'{tag}_vs_mkt'] > 0).sum()} (CI clears {(d[f'{tag}_vs_mkt_lo'] > 0).sum()}); "
              f"vs B4 >0 at {(d[f'{tag}_vs_b4'] > 0).sum()} (CI clears {(d[f'{tag}_vs_b4_lo'] > 0).sum()}); "
              f"Sharpe {d[f'{tag}_sharpe'].min():.2f}-{d[f'{tag}_sharpe'].max():.2f}, "
              f"above random-k at {(d[f'{tag}_sharpe'] > d[f'{tag}_random_sharpe']).sum()}, "
              f"above market at {(d[f'{tag}_sharpe'] > d.mkt_sharpe).sum()}; "
              f"ATR {100 * d[f'{tag}_atr'].min():.2f}-{100 * d[f'{tag}_atr'].max():.2f}%; "
              f"eras {pct(d[f'{tag}_era1'].mean())} / {pct(d[f'{tag}_era2'].mean())}")
    print(f"B4 expectancy gap, largest: {pct(np.abs(d.new_b4_exp - d.old_b4_exp).max())}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("new", help="experiment id, e.g. S2")
    parser.add_argument("old", help="experiment id to compare against, e.g. S1r")
    parser.add_argument("--features", type=Path, default=Path("data/models/features/sp500"))
    parser.add_argument("--labels", type=Path, default=Path("data/models/labels/sp500"))
    parser.add_argument("--artifacts", type=Path, default=trial_log.ARTIFACTS_ROOT)
    parser.add_argument("--out", type=Path, default=None, help="CSV of every readout (default: none)")
    args = parser.parse_args()
    d = compare(args.new, args.old, args.features, args.labels, args.artifacts)
    if args.out:
        d.to_csv(args.out, index=False)
    summary(d, args.new, args.old)
    return 0


if __name__ == "__main__":
    sys.exit(main())

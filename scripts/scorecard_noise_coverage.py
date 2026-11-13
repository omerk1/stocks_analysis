"""How often the scorecard's verdict interval leaves out zero on pure noise, at
the holdout trading test's block count (docs/modeling/PREREGISTRATION.md HT1,
"Before the holdout is opened", prerequisite 4; the rule it is judged by is
that entry's "Noise check" addendum, committed before the run).

Each run is one seed of the synthetic panel (`synthetic.planted_panel`) with
its outcomes shuffled within each date (`shuffle_within_date`), so no feature
can predict them: an interval that leaves out zero is a false positive. On it
the scorecard runs as HT1 judges: the model's columns and B4's as reference
(uniform noise values, `sector` two random labels), ranked by EV in ATR
units, walk-forward over 5 yearly test folds trained from the panel's start
(2017-2021: about 9-10 date blocks of 2H at H = 63, ~28 at H = 21), the
daily top 20 against the market basket, one date-block bootstrap of `n_boot`
draws (`trading.pooled_difference`). Every interval level is read from the
same draws (they are percentile intervals).

Gross, not HT1's model-net-of-10-bps: on noise the net difference is -10 bps,
not zero, so "leaves out zero" would count the cost as an effect. The cost
shifts the statistic and its true value by the same constant, so the
interval covers the truth exactly as often either way; gross, the truth is
zero and "leaves out zero" is a miss. (Seed 0 at H = 63, net: z = -5.3.)

Synthetic, so nothing here reads the market database or the holdout. Run
from the repo root in the project venv (the main checkout's `venv/`):

    venv/bin/python scripts/scorecard_noise_coverage.py --seeds 200 --workers 4

Each finished run is appended to --out at once (resumable: a rerun skips the
(horizon, seed) pairs already there); the summary is printed from --out, and
`--summary-only` prints it without running anything.
"""

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import trading  # noqa: E402
from src.models.ablation import LABEL_COLS, cell_frame, oos_predictions, seed_mean  # noqa: E402
from src.models.learners import BoostingConfig  # noqa: E402
from src.models.splits import walk_forward_folds  # noqa: E402
from src.models.synthetic import PANEL_START, PlantedSpec, planted_panel, shuffle_within_date  # noqa: E402

HT1 = trading.PREREGISTERED["HT1"]
TEST_YEARS = (2017, 2018, 2019, 2020, 2021)
CELL = (2.0, 1.5)               # one v1 cell; the pooled statistic over one cell is that cell's
LEVELS = (0.90, 0.95, 0.99, 0.995, 0.999)
# The rule (PREREGISTRATION.md HT1, "Noise check" addendum): the registered 99%
# stays if it leaves out zero on at most this share of the H = 63 runs; else
# the smallest of the larger CANDIDATES that does replaces it at H = 63.
MAX_EXCLUSION = 0.02
CANDIDATES = (0.99, 0.995, 0.999)
CONFIG = BoostingConfig(max_iter=50, min_samples_leaf=50)   # the scorecard noise test's (tests/test_models_trading.py)
OUT = Path("data/models/noise_coverage/runs.csv")


def scorecard(horizon: int) -> trading.Scorecard:
    return trading.Scorecard(experiment_id="noise_coverage", model_columns=HT1.model_columns,
                             reference_columns=HT1.reference_columns, horizons=(horizon,), seeds=(0,),
                             test_years=TEST_YEARS, first_train_start=PANEL_START, eras=(TEST_YEARS,),
                             grid=(CELL,), rank=HT1.rank, config=CONFIG, verdict_against=HT1.verdict_against,
                             verdict_cost_bps=0)   # gross: see the module docstring


def one_run(horizon: int, seed: int, n_tickers: int, n_boot: int) -> dict:
    """One shuffled panel, scored as HT1 judges: model top 20 (net of the
    registered cost) minus the market basket (no cost), pooled bootstrap."""
    sc = scorecard(horizon)
    [cell] = sc.cells(horizon)
    panel = planted_panel(PlantedSpec(n_tickers=n_tickers, horizon=horizon, upper=cell.upper_atr,
                                      lower=cell.lower_atr, seed=seed))
    panel = shuffle_within_date(panel, seed=seed)
    rng = np.random.default_rng(seed)
    features = panel[["ticker", "date"]].copy()
    for c in HT1.model_columns:
        features[c] = (pd.Categorical(rng.choice(["A", "B"], len(panel))) if c == "sector"
                       else rng.uniform(size=len(panel)).astype("float32"))
    frame = cell_frame(features, panel[["ticker", "date", *LABEL_COLS]])
    folds = walk_forward_folds(sc.test_years, sc.first_train_start)
    model = seed_mean(oos_predictions(frame, sc.model_columns, folds, sc.seeds, sc.config))
    ref = seed_mean(oos_predictions(frame, sc.reference_columns, folds, sc.seeds, sc.config))
    preds = pd.concat([model.assign(model="model"), ref.assign(model=sc.reference)], ignore_index=True)
    sides = {**trading.cell_picks(sc, cell, preds, frame, HT1.verdict_k),
             **trading.benchmark_picks(preds, frame, HT1.verdict_k)}
    baskets = {CELL: {side: trading.basket(p, trading.side_cost(sc, side)) for side, p in sides.items()}}
    result, _, missing = trading.pooled_difference(baskets, "model", sc.verdict_against, horizon, n_boot, HT1.ci)
    row = {"horizon": horizon, "seed": seed, "n_tickers": n_tickers, "n_boot": n_boot,
           "point": result.point_estimate, "boot_std": result.boot_std,
           "z": result.point_estimate / result.boot_std, "p_positive": trading.one_sided_p(result),
           "n_dates": result.n_dates, "n_blocks": result.n_dates / result.block_length,
           "dates_missing_a_cell": missing}
    for level in LEVELS:
        tail = (1 - level) / 2
        lo, hi = np.quantile(result.draws, tail), np.quantile(result.draws, 1 - tail)
        row[f"excludes_{level:g}"] = bool(lo > 0 or hi < 0)
    return row


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval of a share k / n."""
    if n == 0:
        return float("nan"), float("nan")
    p, d = k / n, 1 + z * z / n
    centre, half = (p + z * z / (2 * n)) / d, z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return centre - half, centre + half


def summary(runs: pd.DataFrame) -> dict:
    out = {}
    for h, g in runs.groupby("horizon"):
        rates = {}
        for level in LEVELS:
            k, n = int(g[f"excludes_{level:g}"].sum()), len(g)
            rates[level] = {"k": k, "n": n, "rate": k / n, "wilson95": wilson(k, n)}
        out[int(h)] = {"runs": len(g), "blocks": float(g["n_blocks"].mean()), "mean_z": float(g["z"].mean()),
                       "sd_z": float(g["z"].std()), "p_le_0.0025": float((g["p_positive"] <= 0.0025).mean()),
                       "exclusion": rates}
    return out


def verdict(s: dict) -> str:
    """The pre-committed rule, applied to the H = 63 runs."""
    if 63 not in s:
        return "no H = 63 runs: the rule isn't applied"
    rates = s[63]["exclusion"]
    for level in CANDIDATES:
        if rates[level]["rate"] <= MAX_EXCLUSION:
            return (f"HT1 keeps its registered 99% interval at H = 63" if level == 0.99 else
                    f"HT1's H = 63 interval becomes {level:.1%} (99% left out zero on "
                    f"{rates[0.99]['rate']:.1%} > {MAX_EXCLUSION:.0%}); a dated addendum before opening")
    return (f"even {CANDIDATES[-1]:.1%} leaves out zero on {rates[CANDIDATES[-1]]['rate']:.1%} > "
            f"{MAX_EXCLUSION:.0%}: stop, no fix is chosen here")


def print_summary(runs: pd.DataFrame) -> None:
    s = summary(runs)
    for h, r in s.items():
        print(f"H{h}: {r['runs']} runs, {r['blocks']:.1f} blocks, z mean {r['mean_z']:+.3f} sd {r['sd_z']:.3f}, "
              f"one-sided p <= 0.0025 in {r['p_le_0.0025']:.1%}")
        for level, e in r["exclusion"].items():
            lo, hi = e["wilson95"]
            print(f"  nominal {level:.1%}: left out zero {e['k']}/{e['n']} = {e['rate']:.1%} "
                  f"[{lo:.1%}, {hi:.1%}] (should be {1 - level:.1%})")
    print("Rule: " + verdict(s))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--horizons", nargs="+", type=int, default=[63, 21])
    ap.add_argument("--seeds", type=int, default=200, help="seeds 0 .. n-1 per horizon")
    ap.add_argument("--n-tickers", type=int, default=60, help="the scorecard noise test's panel size")
    ap.add_argument("--n-boot", type=int, default=HT1.n_boot)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()
    done = pd.read_csv(args.out) if args.out.exists() else pd.DataFrame(columns=["horizon", "seed"])
    if not args.summary_only:
        have = set(zip(done["horizon"].astype(int), done["seed"].astype(int)))
        todo = [(h, s) for h in args.horizons for s in range(args.seeds) if (h, s) not in have]
        print(f"{len(todo)} runs to do ({len(have)} already in {args.out})", flush=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(one_run, h, s, args.n_tickers, args.n_boot) for h, s in todo]
            for i, f in enumerate(as_completed(futures), 1):
                row = pd.DataFrame([f.result()])
                row.to_csv(args.out, mode="a", header=not args.out.exists(), index=False)
                print(f"[{i}/{len(todo)}] H{row['horizon'][0]} seed {row['seed'][0]}: z {row['z'][0]:+.2f}", flush=True)
        done = pd.read_csv(args.out)
    if done.empty:
        print("no runs yet")
        return 0
    print_summary(done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

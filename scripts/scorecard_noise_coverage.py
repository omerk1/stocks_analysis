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
(2017-2021: about 9.4 date blocks of 2H at H = 63, ~29 at H = 21), the
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

    venv/bin/python scripts/scorecard_noise_coverage.py --workers 4

(the registered runs: 1,000 seeds at H = 63, 200 at H = 21, `SEEDS`).

Each finished run is appended to --out at once (resumable: a rerun skips the
(horizon, seed) pairs already there); the summary is printed from --out, and
`--summary-only` prints it without running anything.
"""

import argparse
import os
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
SEEDS = {63: 1000, 21: 200}     # the registered runs per horizon; the rule needs all of H = 63's
WIDER_N_BOOT = {0.995: 20_000, 0.999: 100_000}   # draws for a widened level: its Holm cut still ~25 draws
N_TICKERS = 60                  # the scorecard noise test's panel size
OUT = Path("data/models/noise_coverage/runs.csv")


def scorecard(horizon: int) -> trading.Scorecard:
    return trading.Scorecard(experiment_id="noise_coverage", model_columns=HT1.model_columns,
                             reference_columns=HT1.reference_columns, horizons=(horizon,), seeds=(0,),
                             test_years=TEST_YEARS, first_train_start=PANEL_START, eras=(TEST_YEARS,),
                             grid=(CELL,), rank=HT1.rank, config=CONFIG, verdict_against=HT1.verdict_against,
                             verdict_cost_bps=0)   # gross: see the module docstring


def streams(seed: int) -> tuple[int, int, int]:
    """Independent seeds for the panel, the shuffle and the feature values: one
    seed reused would make a feature column the very uniforms the shuffle
    sorts on (as the scorecard noise test keeps them apart, 3 / 1 / 0)."""
    return tuple(int(s.generate_state(1)[0]) for s in np.random.SeedSequence(seed).spawn(3))


def one_run(horizon: int, seed: int, n_tickers: int, n_boot: int) -> dict:
    """One shuffled panel, scored as HT1 judges but gross (verdict_cost_bps=0):
    model top 20 minus the market basket, pooled bootstrap."""
    sc = scorecard(horizon)
    [cell] = sc.cells(horizon)
    panel_seed, shuffle_seed, feature_seed = streams(seed)
    panel = planted_panel(PlantedSpec(n_tickers=n_tickers, horizon=horizon, upper=cell.upper_atr,
                                      lower=cell.lower_atr, seed=panel_seed))
    panel = shuffle_within_date(panel, seed=shuffle_seed)
    rng = np.random.default_rng(feature_seed)
    features = panel[["ticker", "date"]].copy()
    for c in HT1.model_columns:
        features[c] = (pd.Categorical(rng.choice(["A", "B"], len(panel))) if c == "sector"
                       else rng.uniform(size=len(panel)).astype("float32"))
    frame = cell_frame(features, panel[["ticker", "date", *LABEL_COLS]])
    folds = walk_forward_folds(sc.test_years, sc.first_train_start)
    model = seed_mean(oos_predictions(frame, sc.model_columns, folds, sc.seeds, sc.config))
    ref = seed_mean(oos_predictions(frame, sc.reference_columns, folds, sc.seeds, sc.config))
    preds = pd.concat([model.assign(model="model"), ref.assign(model=sc.reference)], ignore_index=True)
    baskets = {CELL: trading.cell_baskets(sc, cell, preds, frame)[1]}   # close_scorecard's own step
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


def registered(runs: pd.DataFrame) -> pd.DataFrame:
    """The runs at the registered settings and seeds only: a smoke run into the
    same file (fewer draws, a smaller panel, seeds past the count) never
    counts toward the rule."""
    keep = (runs["n_tickers"] == N_TICKERS) & (runs["n_boot"] == HT1.n_boot)
    keep &= runs["seed"] < runs["horizon"].map(SEEDS).fillna(0)
    return runs[keep]


def summary(runs: pd.DataFrame) -> dict:
    out = {}
    for h, g in registered(runs).groupby("horizon"):
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
    if s.get(63, {}).get("runs", 0) < SEEDS[63]:
        return f"incomplete: {s.get(63, {}).get('runs', 0)} of {SEEDS[63]} H = 63 runs; the rule isn't applied"
    rates = s[63]["exclusion"]
    for level in CANDIDATES:
        if rates[level]["rate"] <= MAX_EXCLUSION:
            return ("HT1 keeps its registered 99% interval" if level == 0.99 else
                    f"HT1's interval becomes {level:.1%} at both horizons, with {WIDER_N_BOOT[level]:,} draws "
                    f"(99% left out zero on {rates[0.99]['rate']:.1%} > {MAX_EXCLUSION:.0%} of the H = 63 runs); "
                    "a dated addendum before opening")
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


_limits = None


def _one_thread_each(threads: int) -> None:
    """Worker initializer: each process's OpenMP/BLAS pools sized to its share
    of the cores, not all of them (N workers x all cores oversubscribes)."""
    global _limits
    from threadpoolctl import threadpool_limits
    _limits = threadpool_limits(threads)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--horizons", nargs="+", type=int, default=sorted(SEEDS, reverse=True))
    ap.add_argument("--seeds", type=int, default=None,
                    help="seeds 0 .. n-1 per horizon (default: the registered count, SEEDS)")
    ap.add_argument("--n-tickers", type=int, default=N_TICKERS)
    ap.add_argument("--n-boot", type=int, default=HT1.n_boot)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()
    keys = ["horizon", "seed", "n_tickers", "n_boot"]
    done = pd.read_csv(args.out) if args.out.exists() else pd.DataFrame(columns=keys)
    failed = []
    if not args.summary_only:
        have = set(map(tuple, done[keys].astype(int).to_numpy()))
        todo = [(h, s) for h in args.horizons for s in range(args.seeds or SEEDS.get(h, 0))
                if (h, s, args.n_tickers, args.n_boot) not in have]
        print(f"{len(todo)} runs to do ({len(have)} rows already in {args.out})", flush=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        threads = max(1, (os.cpu_count() or 1) // args.workers)
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_one_thread_each,
                                 initargs=(threads,)) as pool:
            futures = {pool.submit(one_run, h, s, args.n_tickers, args.n_boot): (h, s) for h, s in todo}
            for i, f in enumerate(as_completed(futures), 1):
                h, s = futures[f]
                try:
                    row = pd.DataFrame([f.result()])
                except Exception as e:   # one bad seed doesn't cost the others' finished work
                    failed.append((h, s, repr(e)))
                    print(f"[{i}/{len(todo)}] H{h} seed {s}: FAILED {e!r}", flush=True)
                    continue
                row.to_csv(args.out, mode="a", header=not args.out.exists(), index=False)
                print(f"[{i}/{len(todo)}] H{h} seed {s}: z {row['z'][0]:+.2f}", flush=True)
        done = pd.read_csv(args.out) if args.out.exists() else done
    if done.empty:
        print("no runs yet")
    else:
        ignored = len(done) - len(registered(done))
        if ignored:
            print(f"({ignored} rows at other settings or past the registered seeds: not counted)")
        print_summary(done)
    if failed:
        print(f"{len(failed)} runs FAILED (rerun to retry them): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

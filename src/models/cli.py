"""python -m src.models.cli <command>

Commands:
  run-gates       The four gates of `docs/modeling/VALIDATION_HARNESS.md` §8 on
                  synthetic data. Exits 1 if any check fails: no harness result
                  is trusted until they pass. `--quick` runs the tests' size;
                  `--smoke-db` also runs the leakage gate on real bars (read-only).
  build-features  The model-feature cache (`features/cache.py`) for a
                  point-in-time universe, 2010-2021 by default. Reads the
                  database; writes only the parquet cache under `--out`.
  vendor-check    Can a model tell Tiingo rows (later-delisted members) from
                  yfinance rows? Same-ticker gate always; delisted-vs-live
                  read-outs with --features (`vendor_check.py`). Read-only.
  build-labels    The barrier-label cache (`dataset.build_labels`), one file
                  per horizon, for the same universe. Reads the database;
                  writes only under `--out`.
  run-experiment  A pre-registered ablation (`ablation.PREREGISTERED`) on the
                  feature and label caches: one TRIALS.csv row per trial.
  close-experiment  BH and the three verdicts over an experiment's logged
                  trials. Read-only.

Only run-experiment is a trial: the other commands write nothing to TRIALS.csv.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common.vendor_overrides import PREFER_TIINGO
from src.models import gates

SMOKE_START, SMOKE_CUT, SMOKE_END = "2015-01-02", "2019-06-28", "2021-12-31"


def _fmt(result) -> str:
    return f"{result.point_estimate:+.5f}  CI [{result.ci_low:+.5f}, {result.ci_high:+.5f}]  n_dates={result.n_dates}"


def _print_verdict(name: str, verdict: dict[str, bool]) -> bool:
    ok = all(verdict.values())
    print(f"  -> {name}: {'PASS' if ok else 'FAIL'}")
    for check, passed in verdict.items():
        print(f"       {'ok  ' if passed else 'FAIL'} {check}")
    return ok


def _planted_report(r: dict) -> None:
    print(f"Gates 1-2: planted effect and label shuffle "
          f"({r['n_rows']:,} test rows, {r['n_dates']} dates, {gates.GATE_CI:.0%} CIs)")
    print(f"  oracle Brier gain {r['oracle_gain']:+.5f}, one bar late {r['oracle_stale_gain']:+.5f}")
    for name, res in r["brier_vs_b0"].items():
        print(f"  Brier vs B0, {name:8s} {_fmt(res)}")
    for name, res in r["uplift"].items():
        print(f"  uplift, {name:8s} {_fmt(res)}  (expected {r['expected_uplift'][name]:+.4f})")
    for name, res in r["skill"].items():
        print(f"  unshuffled {name:13s} {_fmt(res)}")
    print(f"  shuffled Brier vs B0  {_fmt(r['shuffled_brier_vs_b0'])}")
    for name, res in r["shuffled_skill"].items():
        print(f"  shuffled {name:15s} {_fmt(res)}")


def _leakage_report(title: str, r: dict) -> None:
    print(f"{title}: {r['n_tickers']} tickers, {r['n_rows_checked']:,} rows <= {r['cut'].date()}, "
          f"columns {', '.join(r['columns'])}")
    print(f"  not bar-derived (not covered): {', '.join(r['not_bar_derived']) or '-'}")
    for name, leaks in r["leaks"].items():
        print(f"  {name:16s} leaks: {leaks or 'none'}; canaries caught: {r['canaries_caught'][name]}")


def _smoke_tickers(conn, n_live: int = 16, n_delisted: int = 4) -> list[str]:
    """S&P 500 members on the cut date: `n_live` with yfinance bars and
    `n_delisted` read from Tiingo (delisted members), so the smoke run
    covers both vendors' bars and splits."""
    from src.models import dataset
    members = sorted(dataset.apply_renames(conn, db.read_index_membership(conn, "sp500", as_of=SMOKE_CUT))["ticker"])
    sources = dataset.resolve_sources(conn, members, dataset.LABEL_BASIS, dataset.LABEL_FALLBACK)
    live = [t for t in members if sources.get(t) == db.YFINANCE]
    # Tiingo-read because yfinance can't serve them -- not the PREFER_TIINGO
    # tickers, which are live and read from Tiingo by choice.
    delisted = [t for t in members if sources.get(t) == db.TIINGO and t not in PREFER_TIINGO]
    step = max(len(live) // n_live, 1)
    return live[::step][:n_live] + delisted[:n_delisted]


def run_gates(quick: bool, smoke_db: Path | None, seed: int) -> int:
    warnings.filterwarnings("ignore")
    size = gates.QUICK if quick else gates.FULL
    passed = []

    r = gates.planted_and_shuffle_gates(size, seed=seed)
    _planted_report(r)
    passed.append(_print_verdict("gate 1, planted effect", gates.planted_verdict(r, check_stale_amount=not quick)))
    if quick:
        print("       (stale_matches_expected not checked at the quick size; see gates.planted_verdict)")
    passed.append(_print_verdict("gate 2, label shuffle", gates.shuffle_verdict(r)))

    bars, splits, cut = gates.synthetic_leakage_inputs(seed=seed)
    r = gates.leakage_gate(bars, splits, cut, seed=seed)
    _leakage_report("Gate 3: leakage (synthetic bars)", r)
    passed.append(_print_verdict("gate 3, leakage", gates.leakage_verdict(r)))

    r = gates.purge_gate(seed=seed, test_years=size.test_years, first_train_start=size.first_train_start)
    print(f"Gate 4: purge, horizons {r['horizons']}, checked {r['checked']}")
    print(f"  violations: {r['violations']}")
    passed.append(_print_verdict("gate 4, purge", gates.purge_verdict(r)))

    if smoke_db is not None:
        conn = db.get_connection(f"file:{smoke_db}?mode=ro", uri=True)  # read-only
        try:
            tickers = _smoke_tickers(conn)
            bars, splits, sources = gates.real_leakage_inputs(conn, tickers, SMOKE_START, SMOKE_END)
        finally:
            conn.close()
        print(f"Smoke: real bars for {', '.join(tickers)}")
        print(f"  sources: {pd.Series(sources).value_counts().to_dict()}; tickers with splits: {sorted(splits)}")
        r = gates.leakage_gate(bars, splits, SMOKE_CUT, seed=seed)
        _leakage_report("Gate 3 smoke: leakage (real bars)", r)
        verdict = gates.leakage_verdict(r)
        # Real histories start mid-series and have gaps; the warmup check is for synthetic bars only.
        verdict.pop("warmups_as_declared")
        passed.append(_print_verdict("gate 3 smoke, leakage on real bars", verdict))

    ok = all(passed)
    print(f"\nALL GATES {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _read_only(db_path: Path):
    return db.get_connection(f"file:{db_path}?mode=ro", uri=True)


def build_features(db_path: Path, out: Path, start: str, end: str, indices: tuple[str, ...]) -> int:
    from src.models import dataset
    from src.models.features import cache
    conn = _read_only(db_path)
    try:
        universe = dataset.universe_mask(conn, start, end, indices=indices)
        path = cache.build_feature_cache(conn, universe, out)
    finally:
        conn.close()
    features = cache.read_feature_cache(out)
    m = features.attrs["manifest"]
    print(f"{path}: {m['n_rows']:,} eligible rows, {m['n_tickers']} tickers, {m['start']}..{m['end']}")
    print(f"  price sources: {m['price_sources']}")
    worst = sorted(m["missing_share"].items(), key=lambda kv: -kv[1])[:6]
    print("  most-missing columns: " + ", ".join(f"{c} {v:.1%}" for c, v in worst))
    return 0


def vendor_check(db_path: Path, features_dir: Path | None, start: str, end: str) -> int:
    """With `features_dir`: the delisted-vs-live read-outs on that feature
    cache (descriptive). Always: the same-ticker gate over [start, end] -- the
    exit code is the gate's, with or without `features_dir`."""
    from src.models import dataset, vendor_check as vc
    from src.models.features import cache
    warnings.filterwarnings("ignore")
    dataset.check_holdout(end)
    conn = _read_only(db_path)
    try:
        if features_dir is not None:
            features = cache.read_feature_cache(features_dir)
            m = features.attrs["manifest"]
            tickers = sorted(features["ticker"].unique())
            sources = dataset.resolve_sources(conn, tickers, dataset.LABEL_BASIS, dataset.LABEL_FALLBACK)
            bars = dataset.read_bars_bulk(conn, tickers, dataset.LABEL_BASIS, m["start"], m["end"],
                                          fallback=dataset.LABEL_FALLBACK)
            # Listing metadata, not prices: no holdout bar is read.
            listings = db.read_tiingo_listings(conn).set_index("ticker")["tiingo_end"]
            calendar = pd.DatetimeIndex(sorted(bars["date"].unique()))
            tiingo = [t for t in tickers if sources.get(t) in vc.TIINGO_SOURCES]
            delisted = pd.to_datetime(listings.reindex(tiingo))
            if delisted.isna().any():
                raise ValueError(f"no Tiingo listing end for {sorted(delisted[delisted.isna()].index)}")
            r = vc.run(features, bars, sources, calendar, delisted)
            print(f"Vendor check: {r['n_rows']:,} rows, {r['n_tiingo_rows']:,} from Tiingo ({r['n_tiingo_tickers']} tickers), "
                  f"{r['n_tiingo_far_rows']:,} of them >= {vc.FAR_DAYS} days before delisting")
            print("Fingerprints:\n" + r["fingerprints"].to_string(float_format=lambda v: f"{v:.4f}"))
            print("Feature shift (Tiingo far rows vs yfinance, same dates):\n"
                  + r["feature_shift"].to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
            print("Vendor AUC (ticker-grouped CV, within date): " + ", ".join(f"{k} {v:.3f}" for k, v in r["auc"].items()))
        else:
            members = pd.concat([dataset.apply_renames(conn, db.read_index_membership(conn, n)) for n in dataset.INDEX_FLAGS])
            members = members[members["end_date"].isna() | (members["end_date"] >= start)]
            tickers = sorted(members["ticker"].unique())
        same = vc.both_vendor_tickers(conn, tickers)
        if not same:
            print("Same ticker: no tickers stored on both vendors (bulk_tiingo_ingest --store-tickers)")
            return 1
        s = vc.same_ticker(conn, same, start, end)
    finally:
        conn.close()
    print(f"Same ticker ({s['n_tickers']} tickers, {start}..{end}; rows {s['n_rows']}):")
    print(s["gaps"].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print(f"  vendor AUC (within date, ticker-grouped): {s['auc']:.3f}  [pass: AUC <= {vc.SAME_TICKER_MAX_AUC}; "
          f"per column median gap < {vc.SAME_TICKER_MAX_GAP_SD} SD, <= {vc.SAME_TICKER_MAX_SHARE_OFF:.0%} of rows "
          f"off by > 0.1 SD, <= {vc.SAME_TICKER_MAX_NAN_MISMATCH:.0%} one-vendor NaN]")
    spread = s["gaps"].loc[s["gaps"]["no_spread"], "column"].tolist()
    if spread:
        print(f"  no spread in the window (gap = share of rows that differ): {spread}")
    print("  PASS" if s["passed"] else "  FAIL:\n    " + "\n    ".join(s["failures"]))
    return 0 if s["passed"] else 1


def build_labels(db_path: Path, out: Path, start: str, end: str, indices: tuple[str, ...],
                 horizons: tuple[int, ...]) -> int:
    from src.models import dataset
    warnings.filterwarnings("ignore")
    conn = _read_only(db_path)
    try:
        universe = dataset.universe_mask(conn, start, end, indices=indices)
        rows = universe.loc[universe["has_bars"], ["ticker", "date"]]
        for h in horizons:
            path = dataset.build_labels(conn, rows, h, out)
            m = dataset.read_labels(out, h).attrs["manifest"]
            print(f"{path}: {m['n_rows']:,} rows, {m['n_tickers']} tickers, {m['n_disputed_dropped']:,} dropped "
                  f"for disputed days (disputes {m['disputes']})")
    finally:
        conn.close()
    return 0


def run_experiment(experiment_id: str, features_dir: Path, labels_dir: Path, horizons: tuple[int, ...] | None,
                   n_boot: int) -> int:
    from src.models import ablation
    from src.models.features import cache
    warnings.filterwarnings("ignore")
    exp = ablation.PREREGISTERED[experiment_id]
    unknown = set(horizons or ()) - set(exp.horizons)
    if unknown:
        raise SystemExit(f"{experiment_id} has no horizon {sorted(unknown)}; registered: {exp.horizons}")
    features = cache.read_feature_cache(features_dir)
    for h in horizons or exp.horizons:
        for r in ablation.run_horizon(exp, h, features, labels_dir, n_boot):
            b = r["brier"]
            print(f"{experiment_id} {r['step']} H={h}: Brier {b['point_estimate']:+.6f} "
                  f"[{b['ci_low']:+.6f}, {b['ci_high']:+.6f}], {r['folds_improving']}/{r['n_folds']} years better, "
                  f"band {r['band']:.6f}  ({r['trial_id']})")
    return 0


def close_experiment(experiment_id: str) -> int:
    from src.models import ablation, trial_log
    exp = ablation.PREREGISTERED[experiment_id]
    table, groups = ablation.close_experiment(exp, trial_log.read_trials())
    print(f"{experiment_id}: BH q={exp.q} over {exp.n_trials} trials, {exp.ci:.0%} CIs, "
          f"pass needs >= {exp.min_folds_improving}/{len(exp.test_years)} years and every era better")
    print(table.to_string(index=False, float_format=lambda v: f"{v:+.6f}"))
    for step, verdict in groups.items():
        print(f"  {step}: {verdict}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.models.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    gates_cmd = sub.add_parser("run-gates", help="run the four harness gates")
    gates_cmd.add_argument("--quick", action="store_true", help="the tests' size (minutes, not tens of minutes)")
    gates_cmd.add_argument("--smoke-db", type=Path, default=None,
                           help="market-data SQLite path: also run the leakage gate on real bars (read-only)")
    gates_cmd.add_argument("--seed", type=int, default=0)
    feat = sub.add_parser("build-features", help="build the model-feature cache")
    feat.add_argument("--db", type=Path, required=True, help="market-data SQLite path (opened read-only)")
    feat.add_argument("--out", type=Path, required=True)
    feat.add_argument("--start", default="2010-01-01")
    feat.add_argument("--end", default="2021-12-31")
    feat.add_argument("--indices", nargs="+", default=["sp500"])
    vend = sub.add_parser("vendor-check", help="can a model tell Tiingo rows from yfinance rows?")
    vend.add_argument("--db", type=Path, required=True)
    vend.add_argument("--features", type=Path, default=None,
                      help="a build-features output directory (adds the delisted-vs-live read-outs)")
    vend.add_argument("--start", default="2010-01-01", help="same-ticker window")
    vend.add_argument("--end", default="2021-12-31")
    lab = sub.add_parser("build-labels", help="build the barrier-label cache")
    lab.add_argument("--db", type=Path, required=True, help="market-data SQLite path (opened read-only)")
    lab.add_argument("--out", type=Path, required=True)
    lab.add_argument("--start", default="2010-01-01")
    lab.add_argument("--end", default="2021-12-31")
    lab.add_argument("--indices", nargs="+", default=["sp500"])
    lab.add_argument("--horizons", nargs="+", type=int, default=[10, 21, 42, 63])
    run = sub.add_parser("run-experiment", help="run a pre-registered ablation, logging every trial")
    run.add_argument("experiment")
    run.add_argument("--features", type=Path, required=True, help="a build-features output directory")
    run.add_argument("--labels", type=Path, required=True, help="a build-labels output directory")
    run.add_argument("--horizons", nargs="+", type=int, default=None, help="a subset of the registered horizons")
    run.add_argument("--n-boot", type=int, default=1000)
    close = sub.add_parser("close-experiment", help="BH and verdicts over an experiment's logged trials")
    close.add_argument("experiment")
    args = parser.parse_args(argv)
    if args.command == "build-labels":
        return build_labels(args.db, args.out, args.start, args.end, tuple(args.indices), tuple(args.horizons))
    if args.command == "run-experiment":
        return run_experiment(args.experiment, args.features, args.labels,
                              tuple(args.horizons) if args.horizons else None, args.n_boot)
    if args.command == "close-experiment":
        return close_experiment(args.experiment)
    if args.command == "run-gates":
        return run_gates(args.quick, args.smoke_db, args.seed)
    if args.command == "build-features":
        return build_features(args.db, args.out, args.start, args.end, tuple(args.indices))
    if args.command == "vendor-check":
        return vendor_check(args.db, args.features, args.start, args.end)
    return 2


if __name__ == "__main__":
    sys.exit(main())

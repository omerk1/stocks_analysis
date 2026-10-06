"""The four gates that must pass before any real-data fit
(`docs/modeling/VALIDATION_HARNESS.md` §8). Each gate returns its raw numbers;
`verdict` turns them into named pass/fail checks. The CLI (`cli.py run-gates`)
and the tests (`tests/test_models_gates.py`) call the same functions, so their
pass/fail logic can't drift apart.

1. `planted_gate` -- a feature with a known effect (`synthetic.planted_panel`)
   through the real fit (`learners.fit_predict`, calibration included) and the
   real paired bootstrap vs B0. Its Brier gain's CI must contain the exact
   oracle gain; a noise feature must show no gain; the feature one bar late
   must lose the expected share of the gain.
2. `shuffle_gate` -- the same panel with outcomes shuffled among each date's
   rows. Within-day skill (IC, top-k excess) must vanish, and the Brier gain
   over B0 too (valid here because no synthetic feature knows the date's
   regime; on real data a market-wide feature could legitimately keep some).
   The same measures on the unshuffled panel must detect the skill, so a pass
   isn't vacuous.
3. `leakage_gate` -- every registered source (`features/registry.py`),
   recomputed after perturbing everything after `cut`: the future path, a
   future split (rescales earlier adjusted prices and volumes, and is added
   to the splits table), a future dividend (rescales earlier total-return
   prices) and a delisting right after `cut` (later bars removed). Nothing
   dated <= `cut` may move. Two planted canaries -- one
   reading tomorrow's close, one an adjusted price level -- must be caught.
4. `purge_gate` -- real `barrier_labels` windows (holidays, delistings) for
   every v1 horizon, both fold schemes with their inner folds, with and
   without embargo; then `fit_predict` traced with a recording model: no row
   it fits or calibrates on has a label window reaching the period it's
   evaluated on.

Gate CIs are 99%, not the harness's reporting 90%: a gate should fail on a
bug, not on one draw in ten.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.foundation.market_common.price_basis import PriceBasis
from src.models import dataset
from src.models.baselines import ConstantModel
from src.models.features import registry as reg
from src.models.inference import BootstrapResult, paired_loss_diff, per_date_diff
from src.models.labels.barriers import BarrierCell, barrier_labels, v1_grid
from src.models.learners import BoostedModel, BoostingConfig, fit_predict
from src.models.metrics import daily_ic, top_k_daily
from src.models.splits import EXPANDING, SLIDING, V1_TEST_YEARS, Fold, fold_masks, inner_folds, walk_forward_folds
from src.models.synthetic import (
    PlantedSpec,
    oracle_brier_gain,
    expected_uplift,
    oracle_stale_brier_gain,
    planted_panel,
    shuffle_within_date,
    synthetic_bars,
)

GATE_CI = 0.99
GATE_N_BOOT = 2000
TOP_KS = (5, 20)


@dataclass(frozen=True)
class GateSize:
    n_tickers: int
    start: str
    test_years: tuple[int, ...]
    first_train_start: str


# FULL: the v1 folds (2014-2021 test years). QUICK: the tests' size.
FULL = GateSize(200, "2011-01-03", V1_TEST_YEARS, "2011-01-01")
QUICK = GateSize(80, "2015-01-02", (2019, 2020, 2021), "2015-01-01")


def _ci_contains(result: BootstrapResult, value: float) -> bool:
    return result.ci_low <= value <= result.ci_high


# ---------------------------------------------------------------- gates 1-2

def _oos(panel: pd.DataFrame, folds: list[Fold], make_model) -> pd.DataFrame:
    return pd.concat([fit_predict(panel, f, make_model) for f in folds], ignore_index=True)


def _skill(preds: pd.DataFrame, panel: pd.DataFrame, cell: BarrierCell, neither_ret: float, seed: int) -> dict:
    """Within-day skill against zero: mean daily IC, and top-k excess return
    over the day's mean, each with its date-block CI."""
    frame = preds.merge(panel[["ticker", "date", "ret", "atr", "close_t"]], on=["ticker", "date"])
    out = {}
    ic = daily_ic(frame).dropna()
    out["ic"] = per_date_diff(ic, pd.Series(0.0, index=ic.index), cell.horizon, True, GATE_N_BOOT, GATE_CI, seed)
    for k in TOP_KS:
        excess = top_k_daily(frame, cell, neither_ret, k)["excess"].dropna()
        out[f"top{k}_excess"] = per_date_diff(excess, pd.Series(0.0, index=excess.index), cell.horizon, True,
                                              GATE_N_BOOT, GATE_CI, seed)
    return out


def _uplift(preds: pd.DataFrame, panel: pd.DataFrame, col: str, horizon: int, seed: int) -> BootstrapResult:
    """Per date, mean predicted P(+1) where `col` > 0 minus where it's <= 0:
    the planted effect read back in probability units (descriptive)."""
    frame = preds.merge(panel[["ticker", "date", col]], on=["ticker", "date"]).dropna(subset=[col])
    above = frame[col] > 0
    per_date = (frame[above].groupby("date")["p_up"].mean() - frame[~above].groupby("date")["p_up"].mean()).dropna()
    return per_date_diff(per_date, pd.Series(0.0, index=per_date.index), horizon, True, GATE_N_BOOT, GATE_CI, seed)


def planted_and_shuffle_gates(size: GateSize = FULL, config: BoostingConfig = BoostingConfig(), seed: int = 0) -> dict:
    """Gates 1 and 2 (they share the panel and B0's fit)."""
    spec = PlantedSpec(n_tickers=size.n_tickers, start=size.start, seed=seed)
    cell = BarrierCell(spec.horizon, spec.upper, spec.lower)
    panel = planted_panel(spec)
    folds = walk_forward_folds(size.test_years, size.first_train_start)
    first_test = folds[0].test_start
    train_rows = panel[(panel["date"] < first_test) & (panel["hit"] == 0)]
    neither_ret = float(train_rows["ret"].mean())

    def boosted(col):
        return lambda: BoostedModel([col], config, seed, registered_only=False)  # synthetic columns

    def brier_vs(preds, base):
        return paired_loss_diff(preds, base, spec.horizon, "brier", GATE_N_BOOT, GATE_CI, seed)

    b0 = _oos(panel, folds, ConstantModel)
    preds = {col: _oos(panel, folds, boosted(col)) for col in ("x", "noise", "x_stale")}
    planted = {col: brier_vs(p, b0) for col, p in preds.items()}

    uplift = {col: _uplift(preds[col], panel, col, spec.horizon, seed) for col in ("x", "x_stale")}

    shuffled = shuffle_within_date(panel, seed=seed + 1)
    shuffled_b0 = _oos(shuffled, folds, ConstantModel)
    shuffled_x = _oos(shuffled, folds, boosted("x"))

    return {
        "spec": spec, "n_rows": len(b0), "n_dates": int(b0["date"].nunique()),
        "oracle_gain": oracle_brier_gain(spec.delta),
        "oracle_stale_gain": oracle_stale_brier_gain(spec.delta, spec.rho),
        "brier_vs_b0": planted,
        "uplift": uplift,
        "expected_uplift": {"x": expected_uplift(spec.delta, spec.rho, stale=False),
                            "x_stale": expected_uplift(spec.delta, spec.rho, stale=True)},
        "skill": _skill(preds["x"], panel, cell, neither_ret, seed),
        "shuffled_brier_vs_b0": brier_vs(shuffled_x, shuffled_b0),
        "shuffled_skill": _skill(shuffled_x, shuffled, cell, neither_ret, seed),
    }


def planted_verdict(r: dict, check_stale_amount: bool = True) -> dict[str, bool]:
    """`check_stale_amount=False` at the QUICK size only: with 2-4 training
    years, the inner-fold isotonic calibration shrinks the weak, smooth
    one-bar-late signal by about a quarter (uncalibrated it's recovered in
    full), so its Brier gain falls short of the oracle. At the FULL size it
    matches; that run is the gate of record."""
    b = r["brier_vs_b0"]
    out = {
        "planted_recovered": _ci_contains(b["x"], r["oracle_gain"]),
        "noise_shows_no_gain": b["noise"].ci_high >= 0.0,
        "stale_degrades": b["x_stale"].ci_low > b["x"].ci_high,
    }
    if check_stale_amount:
        out["stale_matches_expected"] = _ci_contains(b["x_stale"], r["oracle_stale_gain"])
    return out


def shuffle_verdict(r: dict) -> dict[str, bool]:
    out = {f"unshuffled_{k}_detected": v.ci_low > 0.0 for k, v in r["skill"].items()}
    out.update({f"shuffled_{k}_zero": _ci_contains(v, 0.0) for k, v in r["shuffled_skill"].items()})
    out["shuffled_brier_no_gain"] = r["shuffled_brier_vs_b0"].ci_high >= 0.0
    return out


# ---------------------------------------------------------------- gate 3

def _price_cols() -> list[str]:
    return ["open", "high", "low", "close"]


def _event_date(frame: pd.DataFrame, cut: pd.Timestamp, offset: int = 5) -> pd.Timestamp | None:
    after = np.sort(frame.loc[frame["date"] > cut, "date"].unique())
    return pd.Timestamp(after[min(offset, len(after) - 1)]) if len(after) else None


def perturb_path(bars, splits, cut, seed=0):
    """Everything after `cut` replaced by a new walk: a one-day shock (x2 or
    x0.5) then a drifting random factor; volume rescaled at random. The same
    factor on every basis, per ticker."""
    tickers = sorted(set().union(*(b["ticker"].unique() for b in bars.values())))
    out = {}
    for basis, frame in bars.items():
        frame = frame.copy()
        for i, ticker in enumerate(tickers):
            after = (frame["ticker"] == ticker) & (frame["date"] > cut)
            n = int(after.sum())
            if not n:
                continue
            rng = np.random.default_rng([seed, i])
            factor = (2.0 if i % 2 else 0.5) * np.exp(np.cumsum(rng.normal(0.002, 0.03, n)))
            for col in _price_cols():
                frame.loc[after, col] = frame.loc[after, col].to_numpy() * factor
            frame.loc[after, "volume"] = frame.loc[after, "volume"].to_numpy() * rng.lognormal(0.0, 0.5, n)
        out[basis] = frame
    return out, splits


def perturb_split(bars, splits, cut, seed=0):
    """A split a few bars after `cut` (alternately 3-for-1 and 1-for-4), as a
    vendor would store it: every earlier adjusted price divided by the ratio,
    volume multiplied, the split added to the ticker's splits."""
    out = {basis: frame.copy() for basis, frame in bars.items()}
    new_splits = dict(splits)
    reference = bars[dataset.UNIVERSE_BASIS]
    for i, ticker in enumerate(sorted(reference["ticker"].unique())):
        when = _event_date(reference[reference["ticker"] == ticker], cut)
        if when is None:
            continue
        ratio = 3.0 if i % 2 else 0.25
        for frame in out.values():
            before = (frame["ticker"] == ticker) & (frame["date"] < when)
            for col in _price_cols():
                frame.loc[before, col] = frame.loc[before, col].to_numpy() / ratio
            frame.loc[before, "volume"] = frame.loc[before, "volume"].to_numpy() * ratio
        row = pd.DataFrame({"execution_date": [when], "ratio": [ratio]})
        old = splits.get(ticker)
        new_splits[ticker] = row if old is None or old.empty else pd.concat([old, row], ignore_index=True)
    return out, new_splits


def perturb_dividend(bars, splits, cut, seed=0):
    """A 3% dividend a few bars after `cut`: every earlier total-return price
    x0.97. Traded prices don't move (they're split-adjusted only)."""
    out = dict(bars)
    frame = bars[PriceBasis.TOTAL_RETURN].copy()
    for ticker in frame["ticker"].unique():
        when = _event_date(frame[frame["ticker"] == ticker], cut)
        if when is None:
            continue
        before = (frame["ticker"] == ticker) & (frame["date"] < when)
        for col in _price_cols():
            frame.loc[before, col] = frame.loc[before, col].to_numpy() * 0.97
    out[PriceBasis.TOTAL_RETURN] = frame
    return out, splits


def perturb_delisting(bars, splits, cut, seed=0):
    """Every other ticker delists right after `cut`: its later bars are gone.
    Catches a column that reads whether a next bar exists."""
    tickers = sorted(set().union(*(b["ticker"].unique() for b in bars.values())))
    gone = set(tickers[::2])
    out = {basis: frame[~(frame["ticker"].isin(gone) & (frame["date"] > cut))].reset_index(drop=True)
           for basis, frame in bars.items()}
    return out, splits


PERTURBATIONS = {"future_path": perturb_path, "future_split": perturb_split, "future_dividend": perturb_dividend,
                 "future_delisting": perturb_delisting}

# Canaries: columns that leak on purpose, so the gate is shown to bite.
CANARY_SOURCES = {
    "canary_next_close": reg.Source(PriceBasis.TOTAL_RETURN,
                                    lambda b, s: pd.DataFrame({"peek_next_close": b["close"].shift(-1) / b["close"]})),
    "canary_price_level": reg.Source(PriceBasis.TOTAL_RETURN,
                                     lambda b, s: pd.DataFrame({"adjusted_close_level": b["close"]})),
}
CANARIES = (
    reg.FeatureSpec("peek_next_close", "canary", reg.MODEL, "dense", None, "canary_next_close", 0),
    reg.FeatureSpec("adjusted_close_level", "canary", reg.MODEL, "dense", None, "canary_price_level", 0),
)
# Which perturbation each canary must be caught by.
CANARY_CAUGHT_BY = {"peek_next_close": ("future_path", "future_delisting"),
                    "adjusted_close_level": ("future_split", "future_dividend")}


def _changed_columns(before: pd.DataFrame, after: pd.DataFrame, cut: pd.Timestamp) -> dict[str, int]:
    """Columns whose value on any row dated <= cut differs (NaN == NaN)."""
    left = before[before["date"] <= cut]
    right = after[after["date"] <= cut]
    merged = left.merge(right, on=["ticker", "date"], suffixes=("_a", "_b"), validate="one_to_one")
    if not len(merged) == len(left) == len(right):
        return {"<row set>": abs(len(left) - len(right)) or 1}
    changed = {}
    for col in left.columns.drop(["ticker", "date"]):
        a, b = merged[f"{col}_a"], merged[f"{col}_b"]
        if a.dtype == bool or b.dtype == bool:
            same = a.fillna(False).astype(bool).to_numpy() == b.fillna(False).astype(bool).to_numpy()
        else:
            fa, fb = a.astype(float).to_numpy(), b.astype(float).to_numpy()
            same = np.isclose(fa, fb, rtol=1e-6, atol=1e-9, equal_nan=True)
        if (~same).any():
            changed[col] = int((~same).sum())
    return changed


def _warmup_mismatches(values: pd.DataFrame, registry) -> dict[str, list]:
    """Registered float columns whose first defined value isn't at the
    declared `warmup_bars` for a ticker with enough history."""
    bad = {}
    for spec in registry:
        if spec.source is None or spec.warmup_bars == 0 or values[spec.name].dtype == bool:
            continue
        for ticker, g in values.groupby("ticker", sort=False):
            col = g[spec.name].to_numpy(dtype=float)
            if len(col) < spec.warmup_bars + 5:
                continue
            first = int(np.argmax(~np.isnan(col))) if (~np.isnan(col)).any() else None
            if first != spec.warmup_bars - 1:
                bad.setdefault(spec.name, []).append((ticker, first))
    return bad


def leakage_gate(
    bars: dict[PriceBasis, pd.DataFrame], splits: dict[str, pd.DataFrame], cut: str | pd.Timestamp,
    registry: tuple[reg.FeatureSpec, ...] = reg.REGISTRY, seed: int = 0,
) -> dict:
    """`bars`: one long frame per basis the registry's sources read (the
    synthetic gate passes the same walk on both). Recomputes every source
    under each perturbation."""
    cut = pd.Timestamp(cut)
    specs = registry + CANARIES
    sources = {**reg.SOURCES, **CANARY_SOURCES}
    base = reg.compute_registered(bars, splits, specs, sources)
    registered = {s.name for s in registry} | {f"{s.name}_rank" for s in registry if s.ranked}
    leaks, canaries = {}, {}
    for name, perturb in PERTURBATIONS.items():
        pbars, psplits = perturb(bars, splits, cut, seed)
        changed = _changed_columns(base, reg.compute_registered(pbars, psplits, specs, sources), cut)
        leaks[name] = {c: n for c, n in changed.items() if c in registered or c == "<row set>"}
        canaries[name] = sorted(c for c in changed if c not in registered)

    # The future-path perturbation must move labels that look across the cut.
    label_bars = bars[dataset.LABEL_BASIS]
    moved_bars, _ = perturb_path(bars, splits, cut, seed)
    cell = [BarrierCell(21, 2.0, 1.5)]
    a = barrier_labels(label_bars, cell).set_index(["ticker", "date"])["hit"]
    b = barrier_labels(moved_bars[dataset.LABEL_BASIS], cell).set_index(["ticker", "date"])["hit"]
    near = (a.index.get_level_values("date") <= cut) & (a.index.get_level_values("date") > cut - pd.Timedelta(days=30))
    labels_moved = int((a[near].fillna(9) != b.reindex(a.index)[near].fillna(9)).sum())

    return {
        "cut": cut, "n_rows_checked": int((base["date"] <= cut).sum()),
        "n_tickers": int(base["ticker"].nunique()),
        "columns": sorted(registered & set(base.columns)),
        "not_bar_derived": [s.name for s in registry if s.source is None],
        "leaks": leaks, "canaries_caught": canaries, "labels_moved": labels_moved,
        "warmup_mismatches": _warmup_mismatches(base, registry),
    }


def leakage_verdict(r: dict) -> dict[str, bool]:
    out = {f"{name}_no_leak": not leaks for name, leaks in r["leaks"].items()}
    for canary, perturbations in CANARY_CAUGHT_BY.items():
        out[f"canary_{canary}_caught"] = all(canary in r["canaries_caught"][p] for p in perturbations)
    out["labels_moved"] = r["labels_moved"] > 0
    out["warmups_as_declared"] = not r["warmup_mismatches"]
    return out


def synthetic_leakage_inputs(n_tickers: int = 12, seed: int = 0):
    """Synthetic bars on both bases (the same walk; the perturbations make them
    differ), with one reverse split before the cut so `history_eligible` and
    `unadjusted_close` have something to undo. Returns (bars, splits, cut)."""
    bars = synthetic_bars(n_tickers, start="2016-01-04", end="2019-12-31", delist_share=0.2, late_share=0.2,
                          seed=seed)
    cut = pd.Timestamp("2019-03-29")
    ticker = sorted(bars["ticker"].unique())[0]
    when = pd.Timestamp("2018-06-01")
    before = (bars["ticker"] == ticker) & (bars["date"] < when)
    bars.loc[before, _price_cols()] = bars.loc[before, _price_cols()].to_numpy() / 0.25
    bars.loc[before, "volume"] = bars.loc[before, "volume"].to_numpy() * 0.25
    splits = {ticker: pd.DataFrame({"execution_date": [when], "ratio": [0.25]})}
    return {PriceBasis.TOTAL_RETURN: bars, PriceBasis.TRADED: bars.copy()}, splits, cut


def real_leakage_inputs(conn, tickers: list[str], start: str, end: str):
    """Real bars on both bases (with the modeling modules' Tiingo fallback)
    and each ticker's splits from its own vendor. Read-only."""
    dataset.check_holdout(end)
    bars = {
        dataset.LABEL_BASIS: dataset.read_bars_bulk(conn, tickers, dataset.LABEL_BASIS, start, end,
                                                    fallback=dataset.LABEL_FALLBACK),
        dataset.UNIVERSE_BASIS: dataset.read_bars_bulk(conn, tickers, dataset.UNIVERSE_BASIS, start, end,
                                                       fallback=dataset.UNIVERSE_FALLBACK),
    }
    sources = dataset.resolve_sources(conn, tickers, dataset.UNIVERSE_BASIS, dataset.UNIVERSE_FALLBACK)
    return bars, dataset._read_splits_bulk(conn, sources), sources


# ---------------------------------------------------------------- gate 4

class _Recorder(ConstantModel):
    """B0 that logs the label windows of every frame it fits or predicts."""

    def __init__(self, log: list):
        self.log = log

    def fit(self, frame, y, sample_weight=None):
        self.log.append(("fit", frame[["date", "label_end_date"]].copy()))
        return super().fit(frame, y, sample_weight)

    def predict_proba(self, frame):
        self.log.append(("predict", frame[["date", "label_end_date"]].copy()))
        return super().predict_proba(frame)


def _touches(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> np.ndarray:
    """Rows whose label window [date, label_end_date] intersects [start, end]."""
    return ((frame["date"] <= end) & (frame["label_end_date"] >= start)).to_numpy()


def _within(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> np.ndarray:
    return frame["date"].between(start, end).to_numpy()


def _fold_mask_violations(labels: pd.DataFrame, fold: Fold, embargo: int) -> dict[str, int]:
    train, test = fold_masks(labels, fold, embargo_days=embargo)
    tr, te = labels[train], labels[test]
    return {
        "train_touches_test": int(_touches(tr, fold.test_start, fold.test_end).sum()),
        "train_outside_window": int((~_within(tr, fold.train_start, fold.train_end)).sum()),
        "test_outside_period": int((~_within(te, fold.test_start, fold.test_end)).sum()),
        "train_and_test": int((train & test).sum()),
    }


def _fit_predict_violations(labels: pd.DataFrame, fold: Fold, n_inner: int = 2) -> dict[str, int]:
    log: list = []
    fit_predict(labels, fold, lambda: _Recorder(log), calibrate=True, n_inner=n_inner)
    inner = inner_folds(fold, n_inner=n_inner)
    *pairs, (k_fit, final_fit), (k_pred, final_pred) = _pairs(log)
    out = {"structure": int(len(pairs) != len(inner) or (k_fit, k_pred) != ("fit", "predict"))}
    out["inner_fit_touches_inner_test"] = 0
    out["inner_fit_reaches_outer_test"] = 0
    out["calibration_outside_inner_test"] = 0
    out["calibration_reaches_outer_test"] = 0
    for f, ((_, fit_rows), (_, pred_rows)) in zip(inner, pairs):
        out["inner_fit_touches_inner_test"] += int(_touches(fit_rows, f.test_start, f.test_end).sum())
        out["inner_fit_reaches_outer_test"] += int(_touches(fit_rows, fold.test_start, fold.test_end).sum())
        out["calibration_outside_inner_test"] += int((~_within(pred_rows, f.test_start, f.test_end)).sum())
        out["calibration_reaches_outer_test"] += int(_touches(pred_rows, fold.test_start, fold.test_end).sum())
    out["final_fit_touches_test"] = int(_touches(final_fit, fold.test_start, fold.test_end).sum())
    out["final_predict_outside_test"] = int((~_within(final_pred, fold.test_start, fold.test_end)).sum())
    return out


def _pairs(log: list):
    """fit_predict's log: (fit, predict) per inner fold, then the final fit
    and the final predict. Returns (*inner_pairs, (kind, final_fit), (kind, final_predict))."""
    *inner, final_fit, final_pred = log
    pairs = [(inner[i], inner[i + 1]) for i in range(0, len(inner) - 1, 2)]
    return (*pairs, final_fit, final_pred)


def purge_gate(n_tickers: int = 30, seed: int = 0, test_years: tuple[int, ...] = V1_TEST_YEARS,
               first_train_start: str = "2011-01-01") -> dict:
    bars = synthetic_bars(n_tickers, start="2010-01-04", seed=seed)
    horizons = sorted({c.horizon for c in v1_grid()})
    totals: dict[str, int] = {}
    checked = {"fold_masks": 0, "fit_predict": 0, "truncated_rows": 0, "unpurged_canary": 0}

    def add(counts):
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v

    for h in horizons:
        cell = next(c for c in v1_grid() if c.horizon == h and (c.upper, c.lower) == (2.0, 1.5))
        labels = barrier_labels(bars, [cell])
        labels = labels[["ticker", "date", "hit", "label_end_date", "truncated"]]
        checked["truncated_rows"] += int(labels["truncated"].sum())
        for scheme in (EXPANDING, SLIDING):
            outer = walk_forward_folds(test_years, first_train_start, scheme)
            for fold in outer + [i for o in outer for i in inner_folds(o, scheme=scheme)]:
                for embargo in (0, 21):
                    add(_fold_mask_violations(labels, fold, embargo))
                    checked["fold_masks"] += 1
                # Canary: the training window without the purge must touch the test period.
                window = labels[_within(labels, fold.train_start, fold.train_end) & labels["label_end_date"].notna().to_numpy()]
                checked["unpurged_canary"] += int(_touches(window, fold.test_start, fold.test_end).any())
            for fold in outer:
                add(_fit_predict_violations(labels, fold))
                checked["fit_predict"] += 1
    n_folds = len(horizons) * 2 * (len(test_years) * 3)
    return {"violations": totals, "checked": checked, "n_folds_expected": n_folds, "horizons": horizons}


def purge_verdict(r: dict) -> dict[str, bool]:
    out = {f"no_{k}": v == 0 for k, v in r["violations"].items()}
    out["truncated_windows_exercised"] = r["checked"]["truncated_rows"] > 0
    out["unpurged_canary_caught_every_fold"] = r["checked"]["unpurged_canary"] == r["n_folds_expected"]
    return out

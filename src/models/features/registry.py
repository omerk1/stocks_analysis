"""The feature registry (`docs/modeling/VALIDATION_HARNESS.md` §7), minimal: every
column a model reads -- and every other column decided at the close of t (the
universe filters, the EV ranking's ATR) -- is declared here with how it's
built. The leakage gate (`gates.py`, §8 gate 3) runs every registered source,
so a new feature is covered by being registered. `check_columns` refuses a
model column that isn't.

A source computes one ticker's columns from that ticker's bars (indexed by
date) on one price basis, plus the splits of the vendor those bars came from.
The leakage gate perturbs both, so a source must only use its inputs up to
each row's date -- including corporate actions: a split or dividend after t
rescales every earlier adjusted price, so a column at t may depend on price
*ratios* within the past, never on adjusted price *levels*.

Not yet here (§7, for the ablation step): grouping beyond this file's
`group`, and the ablation order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.history_breaks import HistoryBreakConfig, training_eligibility
from src.foundation.market_common.price_basis import PriceBasis
from src.models import dataset
from src.models.features import baseline
from src.models.labels.barriers import ATR_PERIOD

# Shapes (IDEAS.md §2b) and priors (IDEAS.md §2).
SHAPES = ("dense", "event", "level_set", "static", "market_wide")
PRIORS = ("supported", "weak", "null")

# Roles: what the column is for at decision time.
MODEL = "model"          # a model input
UNIVERSE = "universe"    # decides whether the row exists (H3)
DECISION = "decision"    # used to rank by EV (metrics.expected_value)


@dataclass(frozen=True)
class Source:
    basis: PriceBasis
    compute: Callable[[pd.DataFrame, pd.DataFrame | None], pd.DataFrame]  # (bars by date, splits) -> columns by date


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str
    role: str
    shape: str
    prior: str | None            # None for controls (baselines) and non-model columns
    source: str | None           # key into SOURCES; None = not computed from bars
    warmup_bars: int             # bars up to and including the first defined value; 0 = never NaN
    ranked: bool = False         # a per-date percentile `<name>_rank` is also a model column
    note: str = ""


def _baseline(bars: pd.DataFrame, splits: pd.DataFrame | None) -> pd.DataFrame:
    return baseline.ticker_features(bars["close"])


def _universe(bars: pd.DataFrame, splits: pd.DataFrame | None) -> pd.DataFrame:
    long = bars.reset_index().assign(ticker="_")
    long.attrs["price_basis"] = dataset.UNIVERSE_BASIS.value
    flags = training_eligibility(bars, splits, HistoryBreakConfig())
    return pd.DataFrame({
        "dollar_volume_20d": dataset.trailing_dollar_volume(long).to_numpy(),
        "unadjusted_close": flags["unadjusted_close"].to_numpy(),
        "history_eligible": flags["eligible"].to_numpy(),
    }, index=bars.index)


def _decision(bars: pd.DataFrame, splits: pd.DataFrame | None) -> pd.DataFrame:
    """ATR over the decision close, as `metrics.expected_value` uses them: the
    labeler's ATR (same function and period as `labels/barriers.py`) over the
    close of t. Unmasked: the label cache NaNs `atr` where the label can't
    resolve (e.g. no bar t+1), which depends on the future; those rows are
    never scored, but the column itself must not."""
    atr = indicators.atr(bars, ATR_PERIOD)
    return pd.DataFrame({"atr_pct": atr / bars["close"]}, index=bars.index)


SOURCES: dict[str, Source] = {
    "baseline": Source(baseline.FEATURE_BASIS, _baseline),
    "universe": Source(dataset.UNIVERSE_BASIS, _universe),
    "decision": Source(dataset.LABEL_BASIS, _decision),
}

REGISTRY: tuple[FeatureSpec, ...] = (
    FeatureSpec("mom_12_1", "baseline", MODEL, "dense", None, "baseline", 253, ranked=True),
    FeatureSpec("realized_vol_63", "baseline", MODEL, "dense", None, "baseline", 64, ranked=True),
    FeatureSpec("mom_1_0", "baseline", MODEL, "dense", None, "baseline", 22, ranked=True),
    FeatureSpec("dist_pct_sma_50", "baseline", MODEL, "dense", None, "baseline", 50, ranked=True),
    FeatureSpec("sector", "baseline", MODEL, "static", None, None, 0,
                note="current-state, not point-in-time (ma_study_insights.md §2.4); delisted members' "
                     "from SEC SIC codes (sec_sectors.py)"),
    FeatureSpec("dollar_volume_20d", "universe", UNIVERSE, "dense", None, "universe", dataset.DOLLAR_VOLUME_WINDOW),
    FeatureSpec("unadjusted_close", "universe", UNIVERSE, "dense", None, "universe", 1),
    FeatureSpec("history_eligible", "universe", UNIVERSE, "dense", None, "universe", 0),
    FeatureSpec("atr_pct", "decision", DECISION, "dense", None, "decision", 15),
)

BY_NAME = {spec.name: spec for spec in REGISTRY}


def _validate(registry: tuple[FeatureSpec, ...]) -> None:
    names = [s.name for s in registry]
    if len(names) != len(set(names)):
        raise ValueError("duplicate registered name")
    for s in registry:
        if s.shape not in SHAPES or (s.prior is not None and s.prior not in PRIORS):
            raise ValueError(f"{s.name}: bad shape {s.shape!r} or prior {s.prior!r}")
        if s.role not in (MODEL, UNIVERSE, DECISION):
            raise ValueError(f"{s.name}: bad role {s.role!r}")
        if s.source is not None and s.source not in SOURCES:
            raise ValueError(f"{s.name}: unknown source {s.source!r}")


_validate(REGISTRY)


def model_columns(registry: tuple[FeatureSpec, ...] = REGISTRY) -> set[str]:
    """Every column a model may read: registered model features and their ranks."""
    cols = set()
    for s in registry:
        if s.role == MODEL:
            cols.add(s.name)
            if s.ranked:
                cols.add(f"{s.name}_rank")
    return cols


def check_columns(columns: list[str], registry: tuple[FeatureSpec, ...] = REGISTRY) -> None:
    """Raises if a model would read a column nobody registered (and so nobody
    leakage-tested)."""
    unknown = sorted(set(columns) - model_columns(registry))
    if unknown:
        raise ValueError(f"unregistered model columns: {unknown}; register them in features/registry.py")


def compute_registered(
    bars: dict[PriceBasis, pd.DataFrame],
    splits: dict[str, pd.DataFrame],
    registry: tuple[FeatureSpec, ...] = REGISTRY,
    sources: dict[str, Source] = SOURCES,
) -> pd.DataFrame:
    """Every bar-derived registered column for every (ticker, date), plus the
    per-date ranks of ranked ones (over all tickers passed). `bars` holds one
    long frame (ticker, date, OHLCV) per basis; `splits` is per ticker."""
    specs = [s for s in registry if s.source is not None]
    by_source: dict[str, list[str]] = {}
    for s in specs:
        by_source.setdefault(s.source, []).append(s.name)
    out = None
    for name, cols in by_source.items():
        source = sources[name]
        parts = []
        for ticker, g in bars[source.basis].groupby("ticker", sort=False):
            values = source.compute(g.drop(columns="ticker").set_index("date").sort_index(), splits.get(ticker))
            parts.append(values[cols].assign(ticker=ticker).reset_index())
        frame = pd.concat(parts, ignore_index=True)
        out = frame if out is None else out.merge(frame, on=["ticker", "date"], how="outer")
    ranked = tuple(s.name for s in specs if s.ranked)
    if ranked:
        out = baseline.add_ranks(out, ranked)
    return out.sort_values(["ticker", "date"], ignore_index=True)

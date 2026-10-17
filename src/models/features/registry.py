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

A `detector` source (the LRP levels) is a per-ticker source that also takes
the ticker (the snapshot cache is per ticker) and runs pattern detectors over
the ticker's whole history; the leakage gate runs it fresh, from a few weeks
before its cut.

A `PanelSource` instead computes from every ticker's bars at once, plus a
`market.PanelContext` (point-in-time membership, sectors, the benchmark): the
market-wide and sector-relative columns. The leakage gate perturbs all of its
inputs' bars the same way, so it is covered like any other source. The
company-financials columns (`fundamentals.py`) are a panel source too, read
from the context's filings tables; the gate's `future_filings` perturbation
covers those. Valuation (`valuation.py`) divides filings by a market cap from
the traded close and the context's share counts; panel sources get this
call's splits in the context, so `future_split` reaches it.

Not yet here (§7, for the ablation step): grouping beyond this file's
`group`, and the ablation order.
"""

from __future__ import annotations

import functools
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.history_breaks import HistoryBreakConfig, training_eligibility
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS, PriceBasis
from src.models import dataset
from src.models.features import baseline, fundamentals, level_features, ma_family, market, valuation
from src.models.features import indicators as indicator_features
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
    compute: Callable[..., pd.DataFrame]  # (bars by date, splits[, ticker]) -> columns by date
    # Detector runs over the ticker's whole history (the LRP levels): called
    # with the ticker too, fed bars from the first one (`features/cache.py`),
    # and minutes per ticker when not cached, so the vendor check runs it on a
    # sample (`vendor_check.same_ticker`).
    detector: bool = False

    def __call__(self, bars: pd.DataFrame, splits: pd.DataFrame | None, ticker: str) -> pd.DataFrame:
        return self.compute(bars, splits, ticker) if self.detector else self.compute(bars, splits)


@dataclass(frozen=True)
class PanelSource:
    basis: PriceBasis
    compute: Callable[[pd.DataFrame, market.PanelContext], pd.DataFrame]  # (long bars, context) -> ticker, date, columns


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str
    role: str
    shape: str
    prior: str | None            # None for controls (baselines) and non-model columns
    source: str | None           # key into SOURCES; None = not computed from bars
    warmup_bars: int             # bars up to and including the first defined value; 0 = never NaN,
                                 # or not set by bars (filings-based columns); market_wide: counted
                                 # on the benchmark's bars
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


def _ma_family(bars: pd.DataFrame, splits: pd.DataFrame | None) -> pd.DataFrame:
    return ma_family.ticker_features(bars)


def _liquidity(bars: pd.DataFrame, splits: pd.DataFrame | None) -> pd.DataFrame:
    return ma_family.liquidity_features(bars)


def _indicators(bars: pd.DataFrame, splits: pd.DataFrame | None) -> pd.DataFrame:
    return indicator_features.ticker_features(bars)


def level_source(root: Path | None = level_features.DEFAULT_ROOT,
                 snapshot_start: pd.Timestamp = level_features.SNAPSHOT_START) -> Source:
    """The LRP levels' source, reading the snapshot cache under `root` (None:
    always compute). `snapshot_start`: the first snapshot week -- the leakage
    gate and the vendor check start near their window to keep detector runs
    few; the registered source starts where the cache does."""
    return Source(dataset.UNIVERSE_BASIS,
                  functools.partial(level_features.ticker_features, root=root, snapshot_start=snapshot_start),
                  detector=True)


SOURCES: dict[str, Source | PanelSource] = {
    "baseline": Source(baseline.FEATURE_BASIS, _baseline),
    "ma_family": Source(baseline.FEATURE_BASIS, _ma_family),
    "indicators": Source(baseline.FEATURE_BASIS, _indicators),
    "market": PanelSource(baseline.FEATURE_BASIS, market.panel_features),
    # bars only give the (ticker, date) rows; the values come from the context's filings tables
    "fundamentals": PanelSource(baseline.FEATURE_BASIS, fundamentals.panel_features),
    # market cap = the traded close (unadjusted for splits after t) x the share count known on t
    "valuation": PanelSource(MODULE_PRICE_BASIS["market_cap"], valuation.panel_features),
    "liquidity": Source(dataset.UNIVERSE_BASIS, _liquidity),
    "universe": Source(dataset.UNIVERSE_BASIS, _universe),
    "decision": Source(dataset.LABEL_BASIS, _decision),
    "levels": level_source(),
}

# The LRP level features (combined-model step 2, 2026-10-15; LRP.md §2.1-2.3,
# definitions in level_features.py): every prior null (LRP §1.1, §3). Warmup 0:
# a level column is defined from the ticker's first snapshot week onward
# (ATR(14) permitting), not after a fixed bar count.
_LEVEL_GROUPS = (("levels_nearest", level_features.NEAREST), ("levels_aggregate", level_features.AGGREGATE),
                 ("levels_barrier", level_features.BARRIER))
LEVEL_SPECS = tuple(FeatureSpec(name, group, MODEL, "level_set", "null", "levels", 0)
                    for group, names in _LEVEL_GROUPS for name in names)

REGISTRY: tuple[FeatureSpec, ...] = (
    FeatureSpec("mom_12_1", "baseline", MODEL, "dense", None, "baseline", 253, ranked=True),
    FeatureSpec("realized_vol_63", "baseline", MODEL, "dense", None, "baseline", 64, ranked=True),
    FeatureSpec("mom_1_0", "baseline", MODEL, "dense", None, "baseline", 22, ranked=True),
    FeatureSpec("dist_pct_sma_50", "baseline", MODEL, "dense", None, "baseline", 50, ranked=True),
    FeatureSpec("sector", "baseline", MODEL, "static", None, None, 0,
                note="current-state, not point-in-time (ma_study_insights.md §2.4); delisted members' "
                     "from SEC SIC codes (sec_sectors.py)"),
    # MA family (ma_study_insights.md §2.2; priors IDEAS.md §2, the last three
    # assigned when E1 was planned, 2026-10-06).
    FeatureSpec("slope_log_21_sma_50", "ma", MODEL, "dense", "supported", "ma_family", 71, ranked=True,
                note="the study's Tier-2 cell is its per-date rank, both tails"),
    FeatureSpec("ribbon_agreement_state", "ma", MODEL, "dense", "supported", "ma_family", 221),
    FeatureSpec("dist_z_sma_20", "ma", MODEL, "dense", "weak", "ma_family", 271),
    FeatureSpec("dist_from_52w_low", "ma", MODEL, "dense", "weak", "ma_family", 252),
    FeatureSpec("stack_fully_bearish", "ma", MODEL, "dense", "weak", "ma_family", 200,
                note="survivorship-capped bearish state (ma_study_insights.md §5)"),
    FeatureSpec("log_dollar_volume_20d", "ma", MODEL, "dense", "weak", "liquidity", 20, ranked=True,
                note="size/liquidity control until point-in-time market cap exists"),
    FeatureSpec("macd_hist_pct", "ma", MODEL, "dense", "weak", "ma_family", 34),
    FeatureSpec("ribbon_width_pctile", "ma", MODEL, "dense", "weak", "ma_family", 451),
    FeatureSpec("dist_z_sma_200", "ma", MODEL, "dense", "weak", "ma_family", 451),
    FeatureSpec("slope_log_63_sma_50", "ma", MODEL, "dense", "weak", "ma_family", 113),
    FeatureSpec("adx_14", "ma", MODEL, "dense", "weak", "ma_family", 29),
    # Indicators and market regime (combined-model step 2b, 2026-10-10): the lean
    # list, one column per idea; every prior null (IDEAS.md §2).
    FeatureSpec("bb_width_pctile", "volatility", MODEL, "dense", "null", "indicators", 271,
                note="Bollinger(20, 2) width as a trailing 252-day percentile; compression"),
    FeatureSpec("atr_ratio_5_63", "volatility", MODEL, "dense", "null", "indicators", 64,
                note="< 1 squeeze, > 1 expansion"),
    FeatureSpec("rvol_21_pctile_252", "volatility", MODEL, "dense", "null", "indicators", 273,
                note="21-day realised vol against the ticker's own trailing year"),
    FeatureSpec("rel_volume_20", "volume", MODEL, "dense", "null", "indicators", 20, ranked=True),
    FeatureSpec("updown_volume_20", "volume", MODEL, "dense", "null", "indicators", 21,
                note="signed volume share; OBV's 20-day change, scale-free"),
    FeatureSpec("rsi_14", "oscillator", MODEL, "dense", "null", "indicators", 15,
                note="M17: corr 0.86 with dist_z_sma_20, sign flips near the MA; kept for that interaction"),
    FeatureSpec("spy_dist_sma_200", "market", MODEL, "market_wide", "null", "market", 200),
    FeatureSpec("spy_slope_log_63", "market", MODEL, "market_wide", "null", "market", 113,
                note="slope_log_63 of SPY's SMA50"),
    FeatureSpec("spy_rvol_21", "market", MODEL, "market_wide", "null", "market", 22),
    FeatureSpec("breadth_above_sma50", "market", MODEL, "market_wide", "null", "market", 50,
                note="point-in-time members, delisted included"),
    FeatureSpec("breadth_above_sma200", "market", MODEL, "market_wide", "null", "market", 200),
    FeatureSpec("adv_dec_10", "market", MODEL, "market_wide", "null", "market", 11),
    FeatureSpec("sector_rel_mom_63", "relative", MODEL, "dense", "null", "market", 64,
                note="vs the sector members' median; sector is current-state (inherits its leak)"),
    FeatureSpec("sector_rank_mom_63", "relative", MODEL, "dense", "null", "market", 64),
    # Company financials (docs/fundamentals/plan.md step 3, 2026-10-14): from the
    # fundamentals and earnings tables, defined from a ticker's first usable
    # filing (warmup 0: not a bar count). Untested here, so prior null; the
    # literature's post-earnings drift is what step 4 tests.
    FeatureSpec("days_since_earnings", "fundamentals", MODEL, "event", "null", "fundamentals", 0),
    FeatureSpec("days_to_earnings_expected", "fundamentals", MODEL, "event", "null", "fundamentals", 0,
                note="the expected date (a year after the same quarter's), never the realized one"),
    FeatureSpec("sue_net_income", "fundamentals", MODEL, "event", "null", "fundamentals", 0, ranked=True,
                note="net income, not EPS: same number up to share-count changes, without EPS's data problems"),
    FeatureSpec("rev_growth_yoy", "fundamentals", MODEL, "event", "null", "fundamentals", 0, ranked=True),
    FeatureSpec("rev_growth_accel", "fundamentals", MODEL, "event", "null", "fundamentals", 0,
                note="change in YoY growth vs the previous quarter; the seasonality-free stand-in for QoQ"),
    FeatureSpec("net_margin_ttm", "fundamentals", MODEL, "event", "null", "fundamentals", 0),
    FeatureSpec("debt_to_equity", "fundamentals", MODEL, "event", "null", "fundamentals", 0),
    FeatureSpec("earnings_yield", "fundamentals", MODEL, "dense", "null", "valuation", 0, ranked=True,
                note="E/P, not P/E: continuous through zero earnings"),
    FeatureSpec("sales_yield", "fundamentals", MODEL, "dense", "null", "valuation", 0, ranked=True),
    FeatureSpec("book_to_market", "fundamentals", MODEL, "dense", "null", "valuation", 0, ranked=True),
    FeatureSpec("share_change_yoy", "fundamentals", MODEL, "event", "null", "valuation", 0, ranked=True,
                note="log share count vs a year earlier, split-adjusted: + dilution, - buybacks"),
    FeatureSpec("dollar_volume_20d", "universe", UNIVERSE, "dense", None, "universe", dataset.DOLLAR_VOLUME_WINDOW),
    FeatureSpec("unadjusted_close", "universe", UNIVERSE, "dense", None, "universe", 1),
    FeatureSpec("history_eligible", "universe", UNIVERSE, "dense", None, "universe", 0),
    FeatureSpec("atr_pct", "decision", DECISION, "dense", None, "decision", 15),
    *LEVEL_SPECS,
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


def model_specs(group: str | None = None, priors: tuple[str, ...] | None = None,
                registry: tuple[FeatureSpec, ...] = REGISTRY) -> list[FeatureSpec]:
    """Registered model features, optionally one group and/or some priors."""
    return [s for s in registry if s.role == MODEL and (group is None or s.group == group)
            and (priors is None or s.prior in priors)]


def model_input(spec: FeatureSpec) -> str:
    """The column a model reads for `spec`: its per-date rank if ranked."""
    return f"{spec.name}_rank" if spec.ranked else spec.name


def check_columns(columns: list[str], registry: tuple[FeatureSpec, ...] = REGISTRY) -> None:
    """Raises if a model would read a column nobody registered (and so nobody
    leakage-tested)."""
    unknown = sorted(set(columns) - model_columns(registry))
    if unknown:
        raise ValueError(f"unregistered model columns: {unknown}; register them in features/registry.py")


def is_detector(spec: FeatureSpec, sources: dict[str, Source | PanelSource] = SOURCES) -> bool:
    """Whether `spec` comes from a detector source (`Source.detector`)."""
    return spec.source is not None and getattr(sources[spec.source], "detector", False)


def _ticker_columns(source: Source, bars: pd.DataFrame, splits: pd.DataFrame | None, ticker: str,
                    cols: list[str], since: pd.Timestamp | None = None) -> pd.DataFrame:
    values = source(bars, splits, ticker)[cols]
    if since is not None:
        values = values[values.index >= since]
    return values.assign(ticker=ticker).reset_index()


def compute_registered(
    bars: dict[PriceBasis, pd.DataFrame],
    splits: dict[str, pd.DataFrame],
    registry: tuple[FeatureSpec, ...] = REGISTRY,
    sources: dict[str, Source | PanelSource] = SOURCES,
    rank: bool = True,
    context: market.PanelContext | None = None,
    workers: int = 1,
    since: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Every bar-derived registered column for every (ticker, date), plus the
    per-date ranks of ranked ones (over all tickers passed; `rank=False` to
    rank later over another row set, e.g. the eligible universe). `bars` holds
    one long frame (ticker, date, OHLCV) per basis; `splits` is per ticker;
    `context` is what panel sources read besides bars (default: every ticker
    passed is a member, no sectors). `workers` > 1: per-ticker sources in
    that many processes (the same function per ticker, so the same values).
    `since`: per-ticker sources' rows before it are dropped (computed on the
    whole frame first, so a warmup is still warm)."""
    context = context if context is not None else market.PanelContext()
    if context.splits is not None:
        raise ValueError("PanelContext.splits is filled from compute_registered's `splits`; pass them there")
    specs = [s for s in registry if s.source is not None]
    by_source: dict[str, list[str]] = {}
    for s in specs:
        by_source.setdefault(s.source, []).append(s.name)
    out = None
    for name, cols in by_source.items():
        source = sources[name]
        if isinstance(source, PanelSource):
            frame = source.compute(bars[source.basis], replace(context, splits=splits))[["ticker", "date", *cols]]
            out = frame if out is None else out.merge(frame, on=["ticker", "date"], how="outer")
            continue
        groups = [(ticker, g.drop(columns="ticker").set_index("date").sort_index())
                  for ticker, g in bars[source.basis].groupby("ticker", sort=False)]
        args = [(source, g, splits.get(ticker), ticker, cols, since) for ticker, g in groups]
        if workers > 1 and len(args) > 1:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                parts = list(pool.map(_ticker_columns, *zip(*args), chunksize=1))
        else:
            parts = [_ticker_columns(*a) for a in args]
        frame = pd.concat(parts, ignore_index=True)
        out = frame if out is None else out.merge(frame, on=["ticker", "date"], how="outer")
    ranked = tuple(s.name for s in specs if s.ranked)
    if ranked and rank:
        out = baseline.add_ranks(out, ranked)
    return out.sort_values(["ticker", "date"], ignore_index=True)

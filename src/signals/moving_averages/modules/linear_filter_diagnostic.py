"""M16 -- Rules as linear filters (unifying diagnostic) (DESIGN.md, lines
~854-865; PREREGISTRATION.md, 2026-09-25).

Track A (exploration) -- see PREREGISTRATION.md's M16 entry for the
track-determination reasoning. Zakamulin's (2017) point: price-minus-MA,
MA-crossover spreads, momentum, and MA slope are all (approximately)
linear filters of past daily returns, differing only in kernel shape. This
study has treated these as separate indicators across M1/M3/M4/M6.1/M6.2/
M6.3; this module asks whether they're actually one signal with many
names, using `stats/kernel_space.py`'s empirical impulse-response
machinery (no hand-derived closed form needed per rule, robust to
`slope_log_k`'s own lack of one).

**Scope call (documented, not a silent narrowing):** only *continuous*
constructions are represented in kernel space -- `dist_pct`, `slope_log_21`,
momentum, and crossover *spreads* (the raw MA difference, before any
threshold). Already-thresholded binary/categorical features
(`above_sma_k`, a golden-cross *event*) are a decision boundary applied on
top of an underlying linear filter, not linear filters themselves --
DESIGN's own motivating claim is about the continuous quantities
underneath these decisions, so thresholded rules are excluded from the
kernel-space comparison rather than force an awkward binary-rule
representation.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features.distance import dist_pct
from src.signals.moving_averages.features.ma import compute_ma
from src.signals.moving_averages.features.slope import slope_log_k
from src.signals.moving_averages.stats import kernel_space as ks

SMA_EMA_LOOKBACKS = (20, 50, 150, 200)
SLOPE_K = 21
MAX_LAG = 400

# M3's own 5 crossover pairs (PREREGISTRATION.md's M3 entry) -- kept
# identical so the crossover-spread rules here map 1:1 onto cells this
# study has already tested post-threshold.
CROSSOVER_PAIRS = {
    "crossover_sma_50_sma_200": (("sma", 50), ("sma", 200)),
    "crossover_sma_20_sma_50": (("sma", 20), ("sma", 50)),
    "crossover_sma_50_sma_150": (("sma", 50), ("sma", 150)),
    "crossover_ema_10_ema_20": (("ema", 10), ("ema", 20)),
    "crossover_ema_8_ema_21": (("ema", 8), ("ema", 21)),
}


def _dist_pct_feature(family: str, lookback: int):
    def feature(close: pd.Series) -> pd.Series:
        return dist_pct(close, compute_ma(close, family, lookback))

    return feature


def _slope_feature(family: str, lookback: int):
    def feature(close: pd.Series) -> pd.Series:
        return slope_log_k(compute_ma(close, family, lookback), SLOPE_K)

    return feature


def _crossover_spread_feature(fast: tuple[str, int], slow: tuple[str, int]):
    def feature(close: pd.Series) -> pd.Series:
        fast_ma = compute_ma(close, fast[0], fast[1])
        slow_ma = compute_ma(close, slow[0], slow[1])
        return (fast_ma - slow_ma) / close

    return feature


def _mom_12_1(close: pd.Series) -> pd.Series:
    from src.signals.moving_averages.features.context import mom_12_1

    return mom_12_1(close)


def _mom_1_0(close: pd.Series) -> pd.Series:
    from src.signals.moving_averages.features.context import mom_1_0

    return mom_1_0(close)


def candidate_rules() -> dict[str, callable]:
    """Every candidate rule's `feature_fn(close) -> Series`, keyed by name.
    Names for `dist_pct`/`slope_log_21` cells match this study's own
    `EXPERIMENTS.csv` cell-naming convention directly (`dist_pct_sma_20`,
    not a fresh name), so the IC-vs-kernel-shape table can join on name.
    """
    rules: dict[str, callable] = {}
    for family in ("sma", "ema"):
        for lookback in SMA_EMA_LOOKBACKS:
            rules[f"dist_pct_{family}_{lookback}"] = _dist_pct_feature(family, lookback)
            rules[f"slope_log_{SLOPE_K}_{family}_{lookback}"] = _slope_feature(family, lookback)
    rules["mom_12_1"] = _mom_12_1
    rules["mom_1_0"] = _mom_1_0
    for name, (fast, slow) in CROSSOVER_PAIRS.items():
        rules[name] = _crossover_spread_feature(fast, slow)
    return rules


def kernel_table(rules: dict[str, callable] | None = None) -> pd.DataFrame:
    """One row per rule: its own empirical weight vector's centroid
    (effective lookback) and dispersion (effective smoothing width). The
    weight vectors themselves are not returned here (400-element arrays,
    not table-shaped) -- see `weight_vectors` for those, needed separately
    for the similarity matrix.
    """
    rules = rules or candidate_rules()
    rows = []
    for name, feature_fn in rules.items():
        weights = ks.impulse_response(feature_fn, max_lag=MAX_LAG)
        rows.append(
            {
                "name": name,
                "centroid": ks.kernel_centroid(weights),
                "dispersion": ks.kernel_dispersion(weights),
            }
        )
    return pd.DataFrame(rows)


def weight_vectors(rules: dict[str, callable] | None = None) -> dict[str, "ks.Weights"]:
    rules = rules or candidate_rules()
    return {name: ks.impulse_response(feature_fn, max_lag=MAX_LAG) for name, feature_fn in rules.items()}

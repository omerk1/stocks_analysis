"""The MA-family model features (`ma_study_insights.md` §2.2, the v1 list), on the
harness's timing: a row at date t holds values known at the close of t (the
decision; entry is t+1's open). Definitions are the MA study's own functions,
called directly, as `features/baseline.py` does for the baselines; the study's
cached panel isn't reused (lagged one row, survivors only).

Every column is scale-free -- a ratio, a log difference, a z-score, a count or
a trailing range position -- because a split or dividend after t rescales all
earlier adjusted prices (the leakage gate checks this). So MACD enters as its
histogram over the close, not in price units.

Changes from the §2.2 list, decided when E1 was planned (2026-10-06):
- `abs_slope_pctile_21_sma_50` dropped: it encodes the U-shape for a linear
  model; the v1 learner is a tree and gets the rank itself.
- `dollar_volume` tercile -> a per-date rank of the trailing 20-day dollar
  volume (`liquidity_features`, traded prices), as the baselines use ranks.
- `adx_14` as the level, not the three-bucket regime: a tree finds its own cuts.
  Computed by `adx` below, the study's formula with a tie tolerance (why there).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.dataset import DOLLAR_VOLUME_WINDOW
from src.signals.moving_averages.features import context, distance, ma, oscillators
from src.signals.moving_averages.features.ribbon import RIBBON_WIDTH_WINDOW
from src.signals.moving_averages.features.slope import slope_log_k

RIBBON_AGREEMENT_LOOKBACKS = (10, 20, 50, 100, 200)  # modules/ribbon_slope_agreement.py
RIBBON_WIDTH_LOOKBACKS = (20, 50, 150, 200)          # features/ribbon.py::RIBBON_SMA_COLS
STACK_LOOKBACKS = (20, 50, 150, 200)                 # modules/stack_minervini.py

MA_COLUMNS = (
    "slope_log_21_sma_50", "ribbon_agreement_state",
    "dist_z_sma_20", "dist_z_sma_200", "slope_log_63_sma_50", "ribbon_width_pctile",
    "stack_fully_bearish", "dist_from_52w_low", "macd_hist_pct", "adx_14",
)


def _ribbon_width_pctile(width: pd.Series, window: int = RIBBON_WIDTH_WINDOW) -> pd.Series:
    """`features/ribbon.py::ribbon_width_pctile` for one ticker: the position of
    today's width within its trailing `window` range, NaN where the range is 0."""
    lo = width.rolling(window, min_periods=window).min()
    hi = width.rolling(window, min_periods=window).max()
    span = hi - lo
    return ((width - lo) / span).mask(span == 0)


TIE_TOLERANCE = 1e-9  # relative to the close


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """`regime.average_directional_index` (Wilder's ADX), except that the
    "which move is larger" comparisons treat moves within `TIE_TOLERANCE` x
    close as equal. With strict comparisons, cent-rounded prices (Tiingo's)
    that tie exactly stop tying after a later split or dividend rescales them
    -- float noise picks a side -- so ADX at t would depend on corporate
    actions after t (caught by the leakage gate's real-bar smoke run: up to 3.9
    ADX points). Identical to the study's ADX wherever no near-tie occurs."""
    eps = TIE_TOLERANCE * close.abs()
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move - down_move > eps) & (up_move > eps), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move - up_move > eps) & (down_move > eps), down_move, 0.0), index=high.index)

    prev_close = close.shift(1)
    true_range = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)

    alpha = 1.0 / period
    smoothed_tr = true_range.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean() / smoothed_tr
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean() / smoothed_tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    out = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    out.iloc[: 2 * period] = np.nan
    return out


def ticker_features(bars: pd.DataFrame) -> pd.DataFrame:
    """One ticker's MA-family columns from its bars (indexed by date; open,
    high, low, close), each known at that date's close."""
    close = bars["close"]
    sma = {k: ma.compute_ma(close, "sma", k) for k in sorted(set(RIBBON_AGREEMENT_LOOKBACKS + STACK_LOOKBACKS))}

    slopes = pd.concat([slope_log_k(sma[k], 21) for k in RIBBON_AGREEMENT_LOOKBACKS], axis=1)
    # A slope within float noise of 0 (a flat SMA on cent prices) is not "rising":
    # a later rescaling would otherwise decide it (see `adx`).
    agreement = (slopes > TIE_TOLERANCE).sum(axis=1).astype("float64").where(slopes.notna().all(axis=1))

    ribbon = pd.concat([sma[k] for k in RIBBON_WIDTH_LOOKBACKS], axis=1)
    width = ribbon.std(axis=1, skipna=False) / ribbon.mean(axis=1, skipna=False)

    # close < sma20 < sma50 < sma150 < sma200, undefined until every SMA exists
    # (a comparison reads NaN as False; CLAUDE.md invariant #9).
    chain = [close] + [sma[k] for k in STACK_LOOKBACKS]
    bearish = np.logical_and.reduce([chain[i + 1] - chain[i] > TIE_TOLERANCE * close.abs()
                                     for i in range(len(chain) - 1)])
    defined = pd.concat(chain, axis=1).notna().all(axis=1)
    stack_bearish = pd.Series(bearish.astype("float64"), index=close.index).where(defined)

    _, _, hist = oscillators.macd_components(close)

    return pd.DataFrame({
        "slope_log_21_sma_50": slope_log_k(sma[50], 21),
        "ribbon_agreement_state": agreement,
        "dist_z_sma_20": distance.dist_z(distance.dist_pct(close, sma[20])),
        "dist_z_sma_200": distance.dist_z(distance.dist_pct(close, sma[200])),
        "slope_log_63_sma_50": slope_log_k(sma[50], 63),
        "ribbon_width_pctile": _ribbon_width_pctile(width),
        "stack_fully_bearish": stack_bearish,
        "dist_from_52w_low": context.dist_from_52w_low(close),
        "macd_hist_pct": hist / close,
        "adx_14": adx(bars["high"], bars["low"], close, 14),
    }, index=close.index).astype("float32")


def liquidity_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Log trailing 20-day median dollar volume, on traded prices (split
    adjustment cancels in close x volume; dividend adjustment wouldn't)."""
    dv = (bars["close"] * bars["volume"]).rolling(DOLLAR_VOLUME_WINDOW, min_periods=DOLLAR_VOLUME_WINDOW).median()
    return pd.DataFrame({"log_dollar_volume_20d": np.log(dv.where(dv > 0))}, index=bars.index).astype("float32")

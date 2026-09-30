"""M19 -- MA "respect history" (DESIGN.md M19; PREREGISTRATION.md,
2026-09-30).

Has this ticker's MA recently *acted as* support or resistance? Built in
two steps, both per ticker, both on an already one-bar-lagged `dist_atr`
column (the same convention `features/touch.py` documents: a row's
`dist_atr` is the state as of that row's tradeable day):

1. **Confirmed reversal** of a touch (touch detection reused from
   `features/touch.py::touch_positions`, so M5 and M19 agree on what a
   touch is). A touch at row t, arriving from side s (+1 from above, -1
   from below), is confirmed at the first row c in t+1 .. t+K where
   `s * dist_atr[c] >= R` (price is back >= R ATR away on the original
   side) and no row in t+1 .. c closed through the MA (`s * dist_atr < 0`)
   or was undefined. The touch row itself is not part of the through-check:
   the touch band is symmetric (|dist_atr| <= 0.25), so a touch that
   lands a hair past the line is still "at the level" by definition. A
   touch with no such row within K is unconfirmed -- it contributes
   nothing, it is not scored as a failure.

2. **Respect count** at row s: the number of confirmations, per side,
   whose confirmation row c lies in the trailing window of L rows ending
   at s inclusive (s-L < c <= s). **Dated by the confirmation row, never
   the touch row** -- a reversal is only knowable once it has happened.
   `tests/test_moving_averages_leakage.py` asserts this directly (a
   confirmation never appears in the feature before its confirmation
   date) on top of the generic perturb-after-the-cut test.

   NaN wherever `dist_atr` itself is NaN (an MA's warmup: CLAUDE.md
   invariant #9) and for the first L-1 defined rows (the window is not yet
   fully observed), so a short window can't masquerade as "no history".

Columns are named `respect_support_<ma>` (count of confirmed from-above
reversals -- the MA held as support) and `respect_resistance_<ma>` (the
from-below mirror), e.g. `respect_support_sma_50`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features import touch

CONFIRM_WINDOW = 5      # K: trading days after the touch within which the reversal must confirm
CONFIRM_DISTANCE = 1.0  # R: ATR multiple price must move back away on the original side
HISTORY_WINDOW = 126    # L: trailing trading days over which confirmations are counted

SUPPORT = "support"
RESISTANCE = "resistance"


def respect_column(ma_col: str, side: str) -> str:
    return f"respect_{side}_{ma_col}"


def confirmation_positions(
    dist_atr: pd.Series,
    confirm_window: int = CONFIRM_WINDOW,
    confirm_distance: float = CONFIRM_DISTANCE,
    away_threshold: float = touch.AWAY_THRESHOLD,
    touch_threshold: float = touch.TOUCH_THRESHOLD,
    max_days_to_touch: int = touch.MAX_DAYS_TO_TOUCH,
) -> pd.DataFrame:
    """One ticker's already-lagged, date-sorted `dist_atr`. Returns one row
    per touch (`touch_pos`, `direction_sign`) with `confirm_pos` -- the
    0-based row position at which the reversal confirmed, or -1 if it
    never did within `confirm_window` rows. Positions index into
    `dist_atr` itself.
    """
    positions, signs = touch.touch_positions(dist_atr, away_threshold, touch_threshold, max_days_to_touch)
    values = dist_atr.to_numpy(dtype=float)
    n = len(values)
    confirm_pos = np.full(len(positions), -1, dtype=int)
    if len(positions) == 0:
        return pd.DataFrame({"touch_pos": positions, "direction_sign": signs, "confirm_pos": confirm_pos})

    # Vectorised over touches, looped over the K forward offsets (K is
    # tiny). `intact` tracks "no close through the MA and no undefined row
    # so far on rows t+1..t+j"; the first j where the chain is intact and
    # price is >= R away on the original side is the confirmation.
    intact = np.ones(len(positions), dtype=bool)
    for j in range(1, confirm_window + 1):
        idx = positions + j
        in_range = idx < n
        signed = np.full(len(positions), np.nan)
        signed[in_range] = signs[in_range] * values[idx[in_range]]
        defined = ~np.isnan(signed)
        through = defined & (signed < 0)
        intact &= defined & ~through
        confirms = intact & (signed >= confirm_distance) & (confirm_pos < 0)
        confirm_pos[confirms] = idx[confirms]
    return pd.DataFrame({"touch_pos": positions, "direction_sign": signs, "confirm_pos": confirm_pos})


def _respect_counts_one_ticker(
    dist_atr: pd.Series,
    confirm_window: int,
    confirm_distance: float,
    history_window: int,
) -> pd.DataFrame:
    """Per-row `support`/`resistance` confirmation counts for one ticker's
    already-sorted `dist_atr` series (RangeIndex assumed by the caller).
    """
    n = len(dist_atr)
    confirmations = confirmation_positions(dist_atr, confirm_window, confirm_distance)
    confirmed = confirmations[confirmations["confirm_pos"] >= 0]

    out = {}
    defined = dist_atr.notna().to_numpy()
    for side, sign in ((SUPPORT, 1.0), (RESISTANCE, -1.0)):
        indicator = np.zeros(n, dtype=float)
        rows = confirmed.loc[confirmed["direction_sign"] == sign, "confirm_pos"].to_numpy()
        np.add.at(indicator, rows, 1.0)
        series = pd.Series(indicator).where(defined)
        # Rolling L-row sum ending at the row itself: counts confirmations
        # dated <= this row, none dated after it. `min_periods=L` leaves the
        # first L-1 defined rows NaN rather than reporting a partial window.
        out[side] = series.rolling(history_window, min_periods=history_window).sum().to_numpy()
    return pd.DataFrame(out)


def respect_counts(
    panel: pd.DataFrame,
    dist_atr_col: str,
    ticker_col: str = "ticker",
    confirm_window: int = CONFIRM_WINDOW,
    confirm_distance: float = CONFIRM_DISTANCE,
    history_window: int = HISTORY_WINDOW,
) -> pd.DataFrame:
    """`respect_support_<ma>` / `respect_resistance_<ma>` for every row of
    `panel` (index-aligned with `panel`, same row order). `panel` must be
    sorted by (`ticker_col`, date) and carry `dist_atr_col` already
    one-bar-lagged. `dist_atr_col` is expected to be `dist_atr_<ma>`; the
    output columns are keyed by that `<ma>` suffix.
    """
    ma_col = dist_atr_col.removeprefix("dist_atr_")
    support_col = respect_column(ma_col, SUPPORT)
    resistance_col = respect_column(ma_col, RESISTANCE)

    support = np.full(len(panel), np.nan, dtype=np.float32)
    resistance = np.full(len(panel), np.nan, dtype=np.float32)
    positions = np.arange(len(panel))
    for _, idx in panel.groupby(ticker_col, sort=False).indices.items():
        frame = panel[dist_atr_col].iloc[idx].reset_index(drop=True)
        counts = _respect_counts_one_ticker(frame, confirm_window, confirm_distance, history_window)
        support[positions[idx]] = counts[SUPPORT].to_numpy(dtype=np.float32)
        resistance[positions[idx]] = counts[RESISTANCE].to_numpy(dtype=np.float32)

    return pd.DataFrame({support_col: support, resistance_col: resistance}, index=panel.index)


def bounce_flags(
    panel: pd.DataFrame,
    dist_atr_col: str,
    ticker_col: str = "ticker",
    confirm_window: int = CONFIRM_WINDOW,
    confirm_distance: float = CONFIRM_DISTANCE,
) -> pd.DataFrame:
    """M20 (PREREGISTRATION.md 2026-09-30): the confirmed reversal itself as
    an *event flag* -- `bounce_<ma>_from_above` / `bounce_<ma>_from_below`,
    True on the confirmation row c of a touch (see `confirmation_positions`),
    False elsewhere, NaN where `dist_atr` is NaN. Index-aligned with `panel`.
    The flag is dated by the confirmation row, so it is known on the
    tradeable day it marks, same as the respect counts above.
    """
    ma_col = dist_atr_col.removeprefix("dist_atr_")
    above = np.zeros(len(panel), dtype=bool)
    below = np.zeros(len(panel), dtype=bool)
    positions = np.arange(len(panel))
    for _, idx in panel.groupby(ticker_col, sort=False).indices.items():
        series = panel[dist_atr_col].iloc[idx].reset_index(drop=True)
        confirmations = confirmation_positions(series, confirm_window, confirm_distance)
        confirmed = confirmations[confirmations["confirm_pos"] >= 0]
        rows = positions[idx]
        above[rows[confirmed.loc[confirmed["direction_sign"] > 0, "confirm_pos"].to_numpy()]] = True
        below[rows[confirmed.loc[confirmed["direction_sign"] < 0, "confirm_pos"].to_numpy()]] = True
    defined = panel[dist_atr_col].notna().to_numpy()
    out = pd.DataFrame({
        f"bounce_{ma_col}_from_above": pd.array(above, dtype="boolean"),
        f"bounce_{ma_col}_from_below": pd.array(below, dtype="boolean"),
    }, index=panel.index)
    return out.mask(np.repeat((~defined)[:, None], out.shape[1], axis=1))

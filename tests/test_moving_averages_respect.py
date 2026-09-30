"""Tests for M19's respect-history feature (`features/respect.py`,
PREREGISTRATION.md 2026-09-30): confirmed-reversal detection and the
trailing, confirmation-dated count.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.respect import (
    RESISTANCE,
    SUPPORT,
    confirmation_positions,
    respect_column,
    respect_counts,
)

COL = "dist_atr_sma_test"


def _frame(values, ticker="AAA"):
    return pd.DataFrame({"ticker": ticker, "date": pd.bdate_range("2021-01-04", periods=len(values)), COL: values})


# ---- confirmation_positions --------------------------------------------------

def test_from_above_touch_confirms_at_first_row_at_least_r_away():
    # away 2 rows, touch at pos 3, then 0.6, 0.9, 1.1 -> confirms at pos 6.
    values = [np.nan, 1.5, 1.4, 0.2, 0.6, 0.9, 1.1, 1.3, 0.4]
    out = confirmation_positions(pd.Series(values), confirm_window=5, confirm_distance=1.0)
    assert out["touch_pos"].tolist() == [3]
    assert out["direction_sign"].tolist() == [1.0]
    assert out["confirm_pos"].tolist() == [6]


def test_close_through_the_ma_before_reaching_r_blocks_confirmation():
    # Same shape but a close below the MA (-0.1) on the way back up.
    values = [np.nan, 1.5, 1.4, 0.2, -0.1, 0.9, 1.1, 1.3, 0.4]
    out = confirmation_positions(pd.Series(values), confirm_window=5, confirm_distance=1.0)
    assert out["confirm_pos"].tolist() == [-1]


def test_touch_row_itself_slightly_through_does_not_block_confirmation():
    # The touch lands a hair past the line (-0.1, inside the +/-0.25 band);
    # the through-check starts the row after.
    values = [np.nan, 1.5, 1.4, -0.1, 0.6, 1.2, 1.1, 1.3, 0.4]
    out = confirmation_positions(pd.Series(values), confirm_window=5, confirm_distance=1.0)
    assert out["direction_sign"].tolist() == [1.0]
    assert out["confirm_pos"].tolist() == [5]


def test_confirmation_outside_k_is_not_a_confirmation():
    # Reaches 1.0 only 6 rows after the touch: K=5 says no, K=6 says yes.
    values = [np.nan, 1.5, 1.4, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0, 0.9]
    assert confirmation_positions(pd.Series(values), confirm_window=5)["confirm_pos"].tolist() == [-1]
    assert confirmation_positions(pd.Series(values), confirm_window=6)["confirm_pos"].tolist() == [9]


def test_confirm_distance_is_respected():
    values = [np.nan, 1.5, 1.4, 0.2, 0.8, 0.9, 0.95, 0.9, 0.4]
    assert confirmation_positions(pd.Series(values), confirm_distance=1.0)["confirm_pos"].tolist() == [-1]
    assert confirmation_positions(pd.Series(values), confirm_distance=0.75)["confirm_pos"].tolist() == [4]


def test_from_below_touch_mirrors():
    values = [np.nan, -1.5, -1.4, -0.2, -0.6, -1.2, -1.1, -1.3, -0.4]
    out = confirmation_positions(pd.Series(values))
    assert out["direction_sign"].tolist() == [-1.0]
    assert out["confirm_pos"].tolist() == [5]
    # A close *above* the MA on the way back down blocks it.
    values[4] = 0.1
    assert confirmation_positions(pd.Series(values))["confirm_pos"].tolist() == [-1]


def test_no_touches_returns_empty():
    out = confirmation_positions(pd.Series([np.nan, 1.5, 1.6, 1.7]))
    assert len(out) == 0


# ---- respect_counts -----------------------------------------------------------

def test_count_appears_on_the_confirmation_row_not_the_touch_row():
    values = [np.nan, 1.5, 1.4, 0.2, 0.6, 0.9, 1.1, 1.3, 0.4, 0.3]
    counts = respect_counts(_frame(values), COL, history_window=3)
    support = counts[respect_column("sma_test", SUPPORT)]
    # Touch at 3, confirmation at 6. Rows 3..5 must read 0, not 1.
    assert support.iloc[3:6].tolist() == [0.0, 0.0, 0.0]
    assert support.iloc[6:9].tolist() == [1.0, 1.0, 1.0]
    # L=3: the window ending at row 9 is rows 7..9 -- the confirmation at 6 has aged out.
    assert support.iloc[9] == 0.0
    assert counts[respect_column("sma_test", RESISTANCE)].iloc[3:].eq(0.0).all()


def test_count_is_nan_during_warmup_and_until_the_window_is_full():
    values = [np.nan, np.nan, 1.5, 1.4, 1.3, 1.2, 1.1, 1.0]
    counts = respect_counts(_frame(values), COL, history_window=3)
    support = counts[respect_column("sma_test", SUPPORT)]
    # 2 NaN warmup rows, then rows 2 and 3 are inside a not-yet-full window.
    assert support.iloc[:4].isna().all()
    assert support.iloc[4:].eq(0.0).all()


def test_sides_are_counted_separately():
    values = [np.nan, 1.5, 1.4, 0.2, 0.6, 1.2,          # support: touch 3, confirmed at row 5
              -1.5, -1.4, -0.2, -0.6, -1.2, -1.1]        # resistance: touch 8, confirmed at row 10
    counts = respect_counts(_frame(values), COL, history_window=8)
    support = counts[respect_column("sma_test", SUPPORT)]
    resistance = counts[respect_column("sma_test", RESISTANCE)]
    # Row 0 is undefined, so the first full 8-row window ends at row 8.
    assert support.iloc[:8].isna().all() and resistance.iloc[:8].isna().all()
    assert support.iloc[8] == 1.0 and resistance.iloc[8] == 0.0
    assert support.iloc[9] == 1.0 and resistance.iloc[9] == 0.0
    assert support.iloc[10] == 1.0 and resistance.iloc[10] == 1.0
    # Row 11's window is rows 4..11: both confirmations still inside.
    assert support.iloc[11] == 1.0 and resistance.iloc[11] == 1.0


def test_counts_do_not_bleed_across_tickers():
    a = [np.nan, 1.5, 1.4, 0.2, 0.6, 0.9, 1.1, 1.3, 0.4]
    b = [np.nan, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2]   # never touches
    panel = pd.concat([_frame(a, "AAA"), _frame(b, "BBB")], ignore_index=True)
    counts = respect_counts(panel, COL, history_window=2)
    support = counts[respect_column("sma_test", SUPPORT)]
    assert support.iloc[6] == 1.0
    assert support.iloc[9:].fillna(0).eq(0.0).all()
    assert len(counts) == len(panel)
    assert (counts.index == panel.index).all()

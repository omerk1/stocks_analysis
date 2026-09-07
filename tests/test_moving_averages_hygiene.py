"""Phase 0 hygiene tests (DESIGN.md §3.4).

Two kinds, deliberately separated:
- Logic tests against small synthetic fixtures -- deterministic, always run,
  catch a broken flag/threshold regardless of what's in the real DB.
- Real-data smoke checks (`test_smoke_*`), skipped only if the real DB file
  itself is missing (same convention as test_gaps_smoke.py etc.). Among
  these, `test_smoke_delisted_tickers_have_price_history` has a genuinely
  unambiguous right answer and is a hard assertion, not skipped just
  because the honest current answer is inconvenient.

The golden-fixture SMA/EMA test compares this repo's existing
`price_based_indicators` implementations against an independent, hand-
derived reference computed directly from the textbook formulas in this file
-- not against the same talib call a second time (that would only prove
talib agrees with itself). This is DESIGN §3.4's "MA values reproduce a
reference implementation to 1e-9" requirement, run now against what exists
today (SMA/EMA) so the guard is already in place before Phase 2 adds
WMA/HMA/KAMA and needs the same check.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.foundation.feature_engineering.price_based_indicators import (
    exponential_moving_average,
    moving_average,
)
from src.foundation.market_common.data import load_bars
from src.foundation.market_common.models import Timeframe
from src.signals.moving_averages.data import (
    LARGE_MOVE_THRESHOLD,
    delisted_coverage_by_year,
    flag_forward_filled_halts,
    flag_large_moves,
    spot_check_sample,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_DB_PATH = REPO_ROOT / "data" / "raw" / "market_data.sqlite"


def _bars(closes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 1_000_000.0},
        index=idx,
    )


# ---- flag_forward_filled_halts ----

def test_flags_a_flat_run_at_or_above_the_minimum_length():
    bars = _bars([100, 101, 102, 102, 102, 102, 103, 104])  # 4 identical closes in a row

    flagged = flag_forward_filled_halts(bars, min_run=3)

    assert len(flagged) == 4
    assert (flagged["close"] == 102).all()


def test_does_not_flag_normal_day_to_day_variation():
    bars = _bars([100, 101, 99, 102, 98, 103, 97])

    flagged = flag_forward_filled_halts(bars, min_run=3)

    assert flagged.empty


def test_does_not_flag_a_run_shorter_than_the_minimum():
    bars = _bars([100, 101, 101, 102])  # only 2 identical closes

    flagged = flag_forward_filled_halts(bars, min_run=3)

    assert flagged.empty


def test_flag_forward_filled_halts_on_empty_input():
    bars = _bars([])

    flagged = flag_forward_filled_halts(bars, min_run=3)

    assert flagged.empty
    assert {"run_id", "run_length"}.issubset(flagged.columns)


# ---- flag_large_moves ----

def test_flags_a_move_beyond_the_threshold():
    bars = _bars([100, 100, 160, 160])  # +60% on day 3

    flagged = flag_large_moves(bars, threshold=LARGE_MOVE_THRESHOLD)

    assert len(flagged) == 1
    assert flagged.index[0] == bars.index[2]
    assert flagged["ret"].iloc[0] == pytest.approx(0.6)


def test_does_not_flag_a_move_within_the_threshold():
    bars = _bars([100, 130, 130])  # +30%, under the 50% default

    flagged = flag_large_moves(bars, threshold=LARGE_MOVE_THRESHOLD)

    assert flagged.empty


def test_flags_a_large_downside_move_too():
    bars = _bars([100, 40])  # -60%

    flagged = flag_large_moves(bars, threshold=LARGE_MOVE_THRESHOLD)

    assert len(flagged) == 1
    assert flagged["ret"].iloc[0] == pytest.approx(-0.6)


# ---- golden fixture: MA values vs. an independent reference implementation ----

def _reference_sma(values: list[float], window: int) -> list[float]:
    """Plain-Python loop-based mean -- deliberately not pandas .rolling()
    or numpy convolution, to be as independent an implementation of "SMA"
    as practical, for catching a future regression in the real one.
    """
    out = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(float("nan"))
        else:
            out.append(sum(values[i + 1 - window:i + 1]) / window)
    return out


def _reference_ema(values: list[float], window: int) -> list[float]:
    """Textbook recursive EMA, seeded with the SMA of the first `window`
    values -- talib's own seeding convention, but implemented independently
    of talib here.
    """
    alpha = 2.0 / (window + 1)
    out = [float("nan")] * (window - 1)
    seed = sum(values[:window]) / window
    out.append(seed)
    prev = seed
    for v in values[window:]:
        prev = alpha * v + (1 - alpha) * prev
        out.append(prev)
    return out


def test_sma_matches_independent_reference_to_1e9():
    values = [100.0, 102.5, 101.0, 105.0, 103.5, 107.0, 106.5, 110.0, 108.0, 112.0]
    close = pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)))

    result = moving_average(close, window=3)
    expected = pd.Series(_reference_sma(values, window=3), index=close.index)

    pd.testing.assert_series_equal(result, expected, check_exact=False, atol=1e-9)


def test_ema_matches_independent_reference_to_1e9():
    values = [100.0, 102.5, 101.0, 105.0, 103.5, 107.0, 106.5, 110.0, 108.0, 112.0]
    close = pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)))

    result = exponential_moving_average(close, window=3)
    expected = pd.Series(_reference_ema(values, window=3), index=close.index)

    pd.testing.assert_series_equal(result, expected, check_exact=False, atol=1e-9)


# ---- real-data audits (smoke) ----

def test_smoke_delisted_tickers_have_price_history():
    """DESIGN.md §3.4: 'Delisted-name count per year is non-trivial and
    roughly matches expectation (if you have zero delistings, your data
    vendor is lying to you).' A real, unambiguous pass/fail against
    whatever is actually loaded -- not skipped just because the honest
    answer may currently be "zero" (see CLAUDE.md invariant #4).
    """
    if not REAL_DB_PATH.exists():
        pytest.skip(f"real DB not found at {REAL_DB_PATH}")

    conn = sqlite3.connect(REAL_DB_PATH)
    coverage = delisted_coverage_by_year(conn)
    conn.close()

    assert not coverage.empty, (
        "Zero delisted tickers have any bars_1d row in this DB. Per DESIGN.md §3.4 "
        "and CLAUDE.md invariant #4, every downstream 'weak MA state' result is "
        "survivorship-biased until this is fixed. Delisted-name price history has "
        "never been ingested here (see docs/limitations.md); this needs a paid data "
        "tier or vendor swap before Track A/B results can be trusted."
    )


def test_smoke_hygiene_functions_run_against_real_data():
    """Structural smoke test, not a pass/fail on counts -- flat-run and
    large-move flags are for human review (DESIGN.md §3.4); a real large
    move can be genuine (earnings, a real crash), not a bug. Just confirms
    the functions run end-to-end against real bars and return the expected
    shape.
    """
    if not REAL_DB_PATH.exists():
        pytest.skip(f"real DB not found at {REAL_DB_PATH}")

    conn = sqlite3.connect(REAL_DB_PATH)
    bars = load_bars(conn, "AAPL", Timeframe.DAILY)
    conn.close()

    assert not bars.empty

    halts = flag_forward_filled_halts(bars)
    moves = flag_large_moves(bars)

    assert {"run_id", "run_length"}.issubset(halts.columns)
    assert "ret" in moves.columns


def test_smoke_spot_check_sample_is_reproducible():
    if not REAL_DB_PATH.exists():
        pytest.skip(f"real DB not found at {REAL_DB_PATH}")

    conn = sqlite3.connect(REAL_DB_PATH)
    first = spot_check_sample(conn, n=20, seed=42)
    second = spot_check_sample(conn, n=20, seed=42)
    conn.close()

    assert len(first) == 20
    pd.testing.assert_frame_equal(first, second)

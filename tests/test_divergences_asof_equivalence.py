"""Does ONE full-history detection run, filtered to `confirmed_at <= t`,
reproduce what a true `detect(as_of=t)` run would have shown?

Why this matters: the full-universe backfill (and any per-date feature
built on top of its stored rows) runs detection once per ticker over all
history and selects rows by `confirmed_at <= date` -- re-running
`detect(as_of=date)` per (ticker, date) is computationally infeasible at
universe scale. That shortcut is only valid if filtering is equivalent to
truncating.

Where equivalence is exact: pivot detection is a sequential state machine
over bars, so the sequence of CONFIRMED pivots at any cutoff is a strict
prefix of the full run's -- truncation can never change an
already-confirmed pivot.

Where it can differ: `_pair_pivots` claims, per price pivot, the nearest
same-kind indicator pivot within `pairing_window` bars, over the whole
pivot list. The full run's list includes indicator pivots that were not
yet CONFIRMED at t; one of those can win a claim (it's closer) that the
truncated run gave to an earlier, already-confirmed pivot. The resulting
divergence row then carries a `confirmed_at > t` (filtered out), while the
truncated run's alternative pairing was visible at t -- so the filtered
full run can MISS (or re-pair) events whose p2 sits within roughly
`pairing_window` bars of a slow-confirming indicator pivot near the
cutoff. This is bounded to the cutoff's immediate neighborhood: both runs
agree on every pairing whose candidate pivots are all resolved by t.

The real-ticker test quantifies that boundary effect and FAILS only if a
mismatch appears for an event meaningfully older than the cutoff (which
would indicate a real equivalence bug, not boundary noise).

Two scope limits, recorded here so downstream feature work can't miss
them:

- **Confluence is NOT covered by this guarantee.** `_key` compares event
  identity/geometry only. Stored backfill rows carry FULL-RUN
  `confluence_count`/`agreeing_indicators` -- the backfill necessarily
  runs with as_of=None, and `detect()` computes confluence after the
  as_of filter precisely because confluence is not truncation-stable. A
  per-date consumer must re-cluster point-in-time from the stored rows
  (direction, form, p2_date, confirmed_at suffice) rather than read the
  stored values as as-of-date facts.

- **Holdout.** Detection is production signal infrastructure and runs
  over full history, like gaps/sr_lines; the divergence-context STUDY's
  analyses stay inside the development window (<= 2021-12-31), which is
  why every real-ticker cutoff below stops there.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.detect import detect
from src.signals.divergences.models import Divergence
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS, source_for

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_DB_PATH = REPO_ROOT / "data" / "raw" / "market_data.sqlite"

# Older than this many calendar days before the cutoff, pairing can no
# longer plausibly involve a pivot that was unconfirmed at the cutoff --
# a mismatch there is a bug, not boundary noise. A full year, not "a few
# bars": RSI pivots confirm fast (flat 5-point threshold), but
# macd_hist/obv confirm against 1x rolling-100-bar std, and in a long
# low-volatility drift a candidate pivot can sit unconfirmed for months.
# Observed on current data: zero mismatches of ANY age, so this bound
# only exists to classify future ones.
STALE_MISMATCH_DAYS = 365


def _key(d: Divergence) -> tuple:
    return (d.indicator.value, d.direction.value, d.form.value, d.p2_date)


def _filtered_full(full: list[Divergence], as_of: str) -> set[tuple]:
    ts = pd.Timestamp(as_of)
    return {_key(d) for d in full if pd.Timestamp(d.confirmed_at) <= ts}


# ---- synthetic: exact equivalence on a controlled fixture ----

_CLOSES = [
    100, 101, 102, 103, 104, 105, 120, 115, 110, 105, 100, 95, 90, 100, 110, 120, 130, 125, 115, 105, 95, 90, 85, 80,
    75, 70, 68, 66, 64, 62, 60, 58, 56, 54, 52, 50, 48, 46, 44, 42,
    50, 60, 70, 80, 90, 100, 110, 120, 135, 130, 120, 110, 100, 95, 90, 85, 80, 75, 70, 65,
]


@pytest.fixture
def synthetic_conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    idx = pd.bdate_range("2020-01-01", periods=len(_CLOSES))
    frame = pd.DataFrame(
        {
            "timestamp": idx,
            "open": _CLOSES,
            "high": [c + 0.5 for c in _CLOSES],
            "low": [c - 0.5 for c in _CLOSES],
            "close": _CLOSES,
            "volume": [1000] * len(_CLOSES),
            "is_partial": [0] * len(_CLOSES),
        }
    ).set_index("timestamp")
    db.upsert_bars(connection, "bars_1d", "TST", db.YFINANCE_SPLIT_ONLY, frame)
    yield connection, idx
    connection.close()


def test_synthetic_filtered_full_run_matches_true_as_of_at_every_cutoff(synthetic_conn):
    connection, idx = synthetic_conn
    config = DivergenceConfig(
        indicators=["rsi"], warmup_bars=5, atr_period=3, rsi_period=3,
        min_bars=0, pairing_window=3, min_pivot_span_bars=5,
    )
    full, _report, skip = detect(connection, "TST", Timeframe.DAILY, config)
    assert skip is None
    assert full  # fixture must actually produce divergences to compare

    # Every 5th bar as a cutoff covers: before any divergence, between
    # appearance and confirmation, at confirmation, and long after.
    # Starting at idx[6], not idx[0]: below warmup_bars+2 bars,
    # _warmup_offset's n-2 clamp would give the truncated run a different
    # slice origin than the full run's, voiding the prefix-stability
    # premise this test rests on. Production is shielded from that regime
    # by min_bars=150, which this config disables (min_bars=0).
    for cutoff in idx[6::5]:
        as_of = cutoff.isoformat()
        asof_divs, _r, s = detect(connection, "TST", Timeframe.DAILY, config, as_of=as_of)
        assert s is None
        assert {_key(d) for d in asof_divs} == _filtered_full(full, as_of), (
            f"filtered full-history run diverges from true as_of run at {as_of}"
        )


# ---- real tickers: quantify the boundary effect, fail on stale mismatches ----


@pytest.fixture
def real_conn():
    if not Path(REAL_DB_PATH).exists():
        pytest.skip(f"real DB not found at {REAL_DB_PATH}")
    connection = db.get_connection(f"file:{REAL_DB_PATH}?mode=ro", uri=True)
    yield connection
    connection.close()


def _has_data(connection, ticker: str) -> bool:
    # Guard on the source detect() will actually load -- the module's own
    # price basis (traded -> 'yfinance_split_only'), NOT 'yfinance': on a
    # checkout holding only one of the two, guarding on the wrong source
    # turns an intended skip into a hard failure (or vice versa).
    row = connection.execute(
        "SELECT COUNT(*) FROM bars_1d WHERE ticker = ? AND source = ?",
        (ticker, source_for(MODULE_PRICE_BASIS["divergences"])),
    ).fetchone()
    return row is not None and row[0] > 0


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "NVDA"])
def test_real_ticker_filtered_full_history_matches_true_as_of(real_conn, ticker):
    if not _has_data(real_conn, ticker):
        pytest.skip(f"{ticker} not present in local market_data.sqlite")

    config = DivergenceConfig()
    full, _report, skip = detect(real_conn, ticker, Timeframe.DAILY, config)
    assert skip is None

    boundary_mismatches: list[tuple] = []
    for as_of in ["2016-12-31", "2018-12-31", "2020-12-31", "2021-12-31"]:
        asof_divs, _r, s = detect(real_conn, ticker, Timeframe.DAILY, config, as_of=as_of)
        assert s is None
        actual = {_key(d) for d in asof_divs}
        expected = _filtered_full(full, as_of)

        cutoff_ts = pd.Timestamp(as_of)
        for key in actual ^ expected:
            p2_ts = pd.Timestamp(key[3])
            age_days = (cutoff_ts - p2_ts).days
            entry = (ticker, as_of, key, age_days, "as_of_only" if key in actual else "filtered_only")
            assert age_days <= STALE_MISMATCH_DAYS, (
                "filtered full-history run diverges from a true as_of run for an event "
                f"far from the cutoff -- this is a bug, not pairing-boundary noise: {entry}"
            )
            boundary_mismatches.append(entry)

    # Boundary noise is tolerated but kept visible in -s runs; it should
    # stay rare (events whose pairing straddles a still-unconfirmed pivot
    # at the cutoff).
    if boundary_mismatches:
        print(f"\n{ticker}: {len(boundary_mismatches)} near-boundary pairing mismatch(es):")
        for entry in boundary_mismatches:
            print(f"  {entry}")

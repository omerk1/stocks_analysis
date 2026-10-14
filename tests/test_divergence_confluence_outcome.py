"""pit_confluence_at_confirmation: the per-event decision-time confluence
count behind the confluence-vs-outcome analysis
(src/analysis/divergence_confluence_outcome.py).

The contract under test: for every event e, the count equals
context.pit_confluence evaluated on the frame filtered to
`confirmed_at <= e.confirmed_at` — i.e. each event gets exactly the
cluster size a consumer acting at its confirmation could have computed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.divergence_confluence_outcome import (
    pit_confluence_at_confirmation,
    stratified_delta,
)
from src.signals.divergences.context import pit_confluence

BAR_INDEX = pd.bdate_range("2020-01-01", periods=120)


def _event(i: int, indicator: str, pos: int, confirmed_pos: int, form: str = "regular") -> dict:
    return {
        "id": f"c{i}",
        "indicator": indicator,
        "direction": "bearish",
        "form": form,
        "p2_date": BAR_INDEX[pos].isoformat(),
        "confirmed_at": BAR_INDEX[confirmed_pos].isoformat(),
    }


def test_slow_confirming_neighbor_counts_only_after_it_confirms():
    # rsi@20 confirms first; macd@21 confirms 5 bars later. The rsi event's
    # decision-time count is 1 (the macd pair wasn't knowable yet) even
    # though the stored full-run count would say 2 for both.
    events = pd.DataFrame(
        [
            _event(0, "rsi", 20, confirmed_pos=22),
            _event(1, "macd_hist", 21, confirmed_pos=27),
        ]
    )
    counts = pit_confluence_at_confirmation(events, BAR_INDEX, pairing_window=3)
    assert counts.tolist() == [1, 2]


def test_chain_split_when_bridging_member_is_not_yet_confirmed():
    # Positions 20/23/26 chain transitively through the middle member. The
    # outer event confirming before the middle one sees two fragments (gap
    # 6 > window), so it stays solo; the middle event, confirming last,
    # sees the full three-indicator chain.
    events = pd.DataFrame(
        [
            _event(0, "rsi", 20, confirmed_pos=21),
            _event(1, "macd_hist", 23, confirmed_pos=40),  # slow bridge
            _event(2, "obv", 26, confirmed_pos=28),
        ]
    )
    counts = pit_confluence_at_confirmation(events, BAR_INDEX, pairing_window=3)
    assert counts.tolist() == [1, 3, 1]


def test_matches_pit_confluence_filtered_to_each_events_confirmation():
    # The defining equivalence, on randomized events: every event's count
    # equals pit_confluence on the frame filtered to confirmed_at <= its
    # own confirmed_at. Since the implementation now delegates to
    # pit_confluence, this is an indexing/filtering check, not a
    # cross-implementation one — the clustering semantics themselves are
    # pinned by the two hand-computed tests above and by
    # tests/test_divergences_context.py's pit_confluence suite.
    rng = np.random.default_rng(7)
    rows = []
    for i in range(160):
        pos = int(rng.integers(0, 110))
        rows.append(
            {
                "id": f"r{i}",
                "indicator": rng.choice(["rsi", "macd_hist", "obv"]),
                "direction": rng.choice(["bearish", "bullish"]),
                "form": rng.choice(["regular", "hidden"]),
                "p2_date": BAR_INDEX[pos].isoformat(),
                "confirmed_at": BAR_INDEX[min(pos + int(rng.integers(0, 12)), 119)].isoformat(),
            }
        )
    rows[0]["p2_date"] = "1999-01-04T00:00:00"  # off-calendar: stays solo
    events = pd.DataFrame(rows)

    counts = pit_confluence_at_confirmation(events, BAR_INDEX, pairing_window=3)

    for idx in events.index:
        visible = events[events["confirmed_at"] <= events.loc[idx, "confirmed_at"]]
        expected = pit_confluence(visible, BAR_INDEX, pairing_window=3).loc[idx]
        assert counts.loc[idx] == expected, f"event {idx}"


def test_rejects_multi_ticker_input():
    events = pd.DataFrame(
        [
            {**_event(0, "rsi", 20, 21), "ticker": "AAPL"},
            {**_event(1, "macd_hist", 21, 22), "ticker": "MSFT"},
        ]
    )
    with pytest.raises(ValueError, match="one ticker"):
        pit_confluence_at_confirmation(events, BAR_INDEX, pairing_window=3)


def test_stratified_delta_only_compares_within_matched_cells():
    # Stratum A: hi=2.0 vs lo=1.0 (delta +1). Stratum B holds only lo rows
    # at an extreme value — it must contribute nothing, and its rows must
    # not leak into the effective-N counts.
    df = pd.DataFrame(
        {
            "direction": ["bearish"] * 5,
            "form": ["regular"] * 5,
            "indicator": ["rsi"] * 4 + ["obv"],
            "year": [2015] * 5,
            "p2_date": ["2015-01-05", "2015-01-05", "2015-02-03", "2015-03-02", "2015-04-01"],
            "v": [2.0, 2.0, 1.0, 1.0, 99.0],
        }
    )
    hi = pd.Series([True, True, False, False, False])
    lo = ~hi
    r = stratified_delta(df, hi, lo, "v")
    assert r["delta"] == pytest.approx(1.0)
    assert r["n_hi"] == 2 and r["n_lo"] == 2
    assert r["dates_hi"] == 1  # both hi rows share one p2 date


def test_stratified_delta_skips_nan_values():
    df = pd.DataFrame(
        {
            "direction": ["bearish"] * 3,
            "form": ["regular"] * 3,
            "indicator": ["rsi"] * 3,
            "year": [2015] * 3,
            "p2_date": ["2015-01-05", "2015-01-06", "2015-01-07"],
            "v": [2.0, np.nan, 1.0],
        }
    )
    hi = pd.Series([True, True, False])
    lo = ~hi
    r = stratified_delta(df, hi, lo, "v")
    assert r["delta"] == pytest.approx(1.0)
    assert r["n_hi"] == 1

"""Orchestration tests for `python -m src.signals.refresh_derived` -- the
step runners themselves (compute + upsert) are each module's own code with
their own tests, so these monkeypatch `_run_step`'s targets and check what
the refresh does AROUND them: step order, stop-on-failure, and when the
stale-row sweep may and may not run.
"""

import pandas as pd
import pytest

from src.foundation.market_common import derived_db
from src.signals import refresh_derived
from src.signals.relative_strength import store as rs_store


@pytest.fixture
def derived_conn():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    rs_store.create_relative_strength_tables(connection)
    yield connection
    connection.close()


def _rs_frame(ticker="AAPL"):
    return pd.DataFrame(
        {"ticker": [ticker], "date": [pd.Timestamp("2020-01-02")], "benchmark": ["SPY"],
         "rs_ratio": [1.0], "rs_mansfield": [1.0], "rs_weighted_return": [0.1], "rs_rating": [50.0]}
    )


def _breadth_frame():
    return pd.DataFrame({"n_constituents": [2]}, index=pd.to_datetime(["2020-01-02"]))


def _patch_runners(monkeypatch, derived_conn, skip_labels=(), fail_labels=(), calls=None):
    """Replace _run_step with a fake that stores real RS rows under a
    per-step run_id (so the sweep has something real to keep), records the
    call order, and skips/fails the named steps."""

    def fake_run_step(step, raw_conn, conn, start, end):
        if calls is not None:
            calls.append(step.label)
        if step.label in fail_labels:
            raise RuntimeError(f"boom in {step.label}")
        if step.label in skip_labels:
            frame = _breadth_frame() if step.kind == "breadth" else _rs_frame()
            return frame.iloc[:0], "no data", None
        run_id = f"run:{step.label}"
        if step.kind == "rs_stock":
            rs_store.upsert_relative_strength(conn, "vs_market", _rs_frame(), run_id)
            return _rs_frame(), None, run_id
        if step.kind == "rs_sector":
            sector = _rs_frame().rename(columns={"ticker": "sector"}).assign(sector="Technology")
            rs_store.upsert_sector_relative_strength(conn, sector, run_id)
            return sector, None, run_id
        return _breadth_frame(), None, run_id

    monkeypatch.setattr(refresh_derived, "_run_step", fake_run_step)


def _plant_stale_rows(derived_conn):
    rs_store.upsert_relative_strength(derived_conn, "vs_market", _rs_frame("DELISTED"), "old-run")
    sector = _rs_frame("STALE_SECTOR").rename(columns={"ticker": "sector"})
    rs_store.upsert_sector_relative_strength(derived_conn, sector, "old-run")


def _tickers(conn, table="relative_strength", column="ticker"):
    return {row[0] for row in conn.execute(f"SELECT DISTINCT {column} FROM {table}")}


def test_full_refresh_runs_every_step_in_order_and_sweeps_stale_rs_rows(monkeypatch, derived_conn):
    calls = []
    _plant_stale_rows(derived_conn)
    _patch_runners(monkeypatch, derived_conn, calls=calls)

    fully_fresh = refresh_derived.run_refresh(None, derived_conn)

    assert fully_fresh
    assert calls == [s.label for s in refresh_derived.REFRESH_STEPS]
    assert _tickers(derived_conn) == {"AAPL"}  # DELISTED swept
    assert _tickers(derived_conn, "sector_relative_strength", "sector") == {"Technology"}


def test_a_skipped_rs_step_blocks_that_tables_sweep_only(monkeypatch, derived_conn):
    _plant_stale_rows(derived_conn)
    _patch_runners(monkeypatch, derived_conn, skip_labels=("rs stock-vs-market nasdaq100",))

    fully_fresh = refresh_derived.run_refresh(None, derived_conn)

    assert not fully_fresh
    # The stock table's key space wasn't fully covered -- old rows survive.
    assert "DELISTED" in _tickers(derived_conn)
    # The sector tier did fully run, so its table is swept regardless.
    assert _tickers(derived_conn, "sector_relative_strength", "sector") == {"Technology"}


def test_a_failing_step_stops_before_later_steps_and_never_sweeps(monkeypatch, derived_conn):
    calls = []
    _plant_stale_rows(derived_conn)
    _patch_runners(monkeypatch, derived_conn, fail_labels=("breadth sp500 cap",), calls=calls)

    with pytest.raises(RuntimeError, match="boom"):
        refresh_derived.run_refresh(None, derived_conn)

    assert calls[-1] == "breadth sp500 cap"
    assert len(calls) == 3
    assert "DELISTED" in _tickers(derived_conn)
    assert "STALE_SECTOR" in _tickers(derived_conn, "sector_relative_strength", "sector")


def test_resuming_past_an_rs_step_blocks_the_stock_sweep_but_not_the_sector_sweep(monkeypatch, derived_conn):
    # Resume from step 6: step 5 (rs stock-vs-market sp500) ran in a
    # PREVIOUS invocation under a run_id this one doesn't know -- sweeping
    # relative_strength now would delete those fresh rows as "stale".
    calls = []
    _plant_stale_rows(derived_conn)
    _patch_runners(monkeypatch, derived_conn, calls=calls)

    fully_fresh = refresh_derived.run_refresh(None, derived_conn, from_step=6)

    assert not fully_fresh
    assert calls[0] == "rs stock-vs-market nasdaq100"
    assert "DELISTED" in _tickers(derived_conn)
    assert _tickers(derived_conn, "sector_relative_strength", "sector") == {"Technology"}


def test_resuming_within_the_breadth_steps_still_sweeps_both_rs_tables(monkeypatch, derived_conn):
    _plant_stale_rows(derived_conn)
    _patch_runners(monkeypatch, derived_conn)

    fully_fresh = refresh_derived.run_refresh(None, derived_conn, from_step=3)

    assert not fully_fresh  # breadth steps 1-2 didn't run here
    assert _tickers(derived_conn) == {"AAPL"}
    assert _tickers(derived_conn, "sector_relative_strength", "sector") == {"Technology"}

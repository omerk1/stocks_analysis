import sqlite3

import pytest

from src.market_common import derived_db
from src.sr_lines import store
from src.sr_lines.models import Event, EventType, Line, LineKind, LineRole, LineState, ScoreBreakdown, TouchCounts


@pytest.fixture
def derived_conn():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    store.create_sr_lines_tables(connection)
    yield connection
    connection.close()


def _line(
    center: float = 100.0, strength: float = 0.5, touch_wick: int = 2, n_events: int = 2,
) -> Line:
    events = [
        Event(type=EventType.TOUCH, start="2020-01-10", end="2020-01-10", penetration_atr=0.1, reaction_atr=1.0),
        Event(type=EventType.BODY_TOUCH, start="2020-01-20", end="2020-01-20", penetration_atr=0.2, reaction_atr=1.0),
    ][:n_events]
    return Line(
        id="h0", kind=LineKind.HORIZONTAL, role=LineRole.SUPPORT, state=LineState.ACTIVE,
        center=center, half_width=1.0, slope=None, intercept=None, origin_index=None,
        first_touch="2020-01-01", last_event="2020-01-20", regime_start="2020-01-01",
        events=events, scores=ScoreBreakdown(total=strength), strength=strength, proximity=0.5,
        origin_side="above", touch_counts=TouchCounts(wick=touch_wick, total=touch_wick),
        age_days_total=100, age_days_regime=100, days_since_last_event=5,
    )


def test_upsert_lines_is_idempotent_across_repeated_runs(derived_conn):
    line = _line()

    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-1")
    count_after_first = derived_conn.execute("SELECT COUNT(*) FROM sr_lines").fetchone()[0]
    assert count_after_first == 1

    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-2")
    count_after_second = derived_conn.execute("SELECT COUNT(*) FROM sr_lines").fetchone()[0]
    assert count_after_second == 1

    run_ids = {row[0] for row in derived_conn.execute("SELECT run_id FROM sr_lines").fetchall()}
    assert run_ids == {"run-2"}


def test_upsert_lines_preserves_id_across_reruns_despite_fresh_uuids(derived_conn):
    # Every upsert_lines call mints a fresh uuid4 per row (see _line_row) --
    # the ON CONFLICT DO UPDATE ... RETURNING id must discard that in favor
    # of the existing row's original id, the same guarantee upsert_gaps
    # provides for Gap.id.
    line = _line()

    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-1")
    id_after_first = derived_conn.execute("SELECT id FROM sr_lines").fetchone()[0]

    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-2")
    id_after_second = derived_conn.execute("SELECT id FROM sr_lines").fetchone()[0]

    assert id_after_first == id_after_second


def test_upsert_lines_updates_geometry_and_touch_counts_on_conflict(derived_conn):
    # Deliberate deviation from gaps: geometry (center) IS in the SET list,
    # since a Line's geometry can legitimately drift run-over-run as new
    # pivots join an existing cluster -- as long as the drift stays within
    # the same rounded geometry_bucket (part of the natural key itself; a
    # drift large enough to cross buckets is a separate scenario, covered
    # below).
    line = _line(center=100.001, strength=0.5, touch_wick=2)
    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-1")

    line.center = 100.004  # still rounds to the same 100.0 geometry_bucket
    line.strength = 0.9
    line.touch_counts = TouchCounts(wick=5, total=5)
    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-2")

    row = derived_conn.execute(
        "SELECT center, strength, touch_wick, touch_total, run_id FROM sr_lines"
    ).fetchone()
    assert row == (100.004, 0.9, 5, 5, "run-2")


def test_a_center_drift_crossing_into_a_new_geometry_bucket_creates_a_separate_row(derived_conn):
    # geometry_bucket is part of the natural key -- a center move large
    # enough to round to a different bucket is, by this key's own
    # definition, no longer "the same area," so it lands as a new row
    # rather than overwriting the old one.
    line = _line(center=100.0)
    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-1")

    line.center = 105.0  # rounds to a different geometry_bucket entirely
    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-2")

    count = derived_conn.execute("SELECT COUNT(*) FROM sr_lines").fetchone()[0]
    assert count == 2


def test_sr_line_events_are_rekeyed_to_the_persisted_id_on_conflict(derived_conn):
    line = _line(n_events=1)
    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-1")
    persisted_id = derived_conn.execute("SELECT id FROM sr_lines").fetchone()[0]
    events_after_first = derived_conn.execute(
        "SELECT line_id, type FROM sr_line_events"
    ).fetchall()
    assert events_after_first == [(persisted_id, "touch")]

    # Rerun with a different (larger) event set -- the child table must be
    # wholesale replaced, re-keyed to the same (preserved) parent id.
    line2 = _line(n_events=2)
    store.upsert_lines(derived_conn, [line2], "AAPL", "daily", "medium_term", run_id="run-2")

    persisted_id_after_rerun = derived_conn.execute("SELECT id FROM sr_lines").fetchone()[0]
    assert persisted_id_after_rerun == persisted_id
    events_after_second = derived_conn.execute(
        "SELECT line_id, type FROM sr_line_events ORDER BY seq"
    ).fetchall()
    assert events_after_second == [(persisted_id, "touch"), (persisted_id, "body_touch")]


def test_two_different_presets_for_the_same_ticker_timeframe_dont_collide(derived_conn):
    # preset is a first-class natural-key column -- a ticker legitimately
    # has independently-meaningful lines under medium_term vs long_term.
    line = _line()

    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-1")
    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "long_term", run_id="run-2")

    count = derived_conn.execute("SELECT COUNT(*) FROM sr_lines").fetchone()[0]
    assert count == 2
    presets = {row[0] for row in derived_conn.execute("SELECT preset FROM sr_lines").fetchall()}
    assert presets == {"medium_term", "long_term"}


def test_diagonal_geometry_bucket_uses_slope_atr_per_bar_not_center(derived_conn):
    line = _line()
    line.kind = LineKind.DIAGONAL
    line.center = None
    line.slope = 0.001
    line.slope_atr_per_bar = 0.25
    line.intercept = 4.6
    line.origin_index = 0

    store.upsert_lines(derived_conn, [line], "AAPL", "daily", "medium_term", run_id="run-1")

    row = derived_conn.execute("SELECT geometry_bucket, kind FROM sr_lines").fetchone()
    assert row == (0.25, "diagonal")

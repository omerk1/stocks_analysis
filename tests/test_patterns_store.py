import json

import pytest

from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.signals.patterns.models import PatternMatch, PatternStatus, PatternType
from src.signals.patterns.store import create_pattern_matches_table, upsert_pattern_matches


@pytest.fixture
def conn():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    create_pattern_matches_table(connection)
    yield connection
    connection.close()


def _match(match_id: str = "m1", confidence: float = 0.5, status: PatternStatus = PatternStatus.PENDING) -> PatternMatch:
    p1 = Pivot(kind=PivotKind.HIGH, timestamp="2020-01-15", value=130.0, confirmed_at="2020-01-15", threshold_at_pivot=1.0, bar_index=9)
    return PatternMatch(
        id=match_id,
        ticker="TST",
        timeframe=Timeframe.DAILY,
        pattern_type=PatternType.DOUBLE_TOP,
        direction=Direction.BEARISH,
        pivots=[p1],
        key_levels={"p1": 130.0, "neckline": 121.0, "p2": 129.0},
        target_price=112.5,
        stop_price=130.0,
        status=status,
        confidence=confidence,
        formation_start="2020-01-15",
        formation_end="2020-01-29",
        notes=["geometric_cleanliness: 0.99"],
    )


def test_create_and_upsert_round_trip(conn):
    upsert_pattern_matches(conn, [_match()], "run-1")

    row = conn.execute(
        "SELECT id, ticker, pattern_type, status, confidence, key_levels_json, notes_json, run_id "
        "FROM pattern_matches"
    ).fetchone()

    assert row[0] == "m1"
    assert row[1] == "TST"
    assert row[2] == "double_top"
    assert row[3] == "pending"
    assert row[4] == pytest.approx(0.5)
    assert json.loads(row[5]) == {"p1": 130.0, "neckline": 121.0, "p2": 129.0}
    assert json.loads(row[6]) == ["geometric_cleanliness: 0.99"]
    assert row[7] == "run-1"


def test_rerun_updates_mutable_fields_without_duplicating(conn):
    upsert_pattern_matches(conn, [_match(confidence=0.5, status=PatternStatus.PENDING)], "run-1")
    upsert_pattern_matches(conn, [_match(match_id="m2", confidence=0.9, status=PatternStatus.HIT_TARGET)], "run-2")

    count = conn.execute("SELECT COUNT(*) FROM pattern_matches").fetchone()[0]
    assert count == 1  # same natural key (ticker/timeframe/pattern_type/formation_start/formation_end)

    stored_id, status, confidence, run_id = conn.execute(
        "SELECT id, status, confidence, run_id FROM pattern_matches"
    ).fetchone()
    # id preserved from the first insert, mutable fields reflect the later run.
    assert stored_id == "m1"
    assert status == "hit_target"
    assert confidence == pytest.approx(0.9)
    assert run_id == "run-2"


def test_rerun_leaves_geometry_fields_untouched(conn):
    upsert_pattern_matches(conn, [_match()], "run-1")
    changed = _match(match_id="m2")
    changed.key_levels = {"p1": 999.0, "neckline": 1.0, "p2": 999.0}
    changed.target_price = -1.0
    upsert_pattern_matches(conn, [changed], "run-2")

    key_levels_json, target_price = conn.execute(
        "SELECT key_levels_json, target_price FROM pattern_matches"
    ).fetchone()
    assert json.loads(key_levels_json) == {"p1": 130.0, "neckline": 121.0, "p2": 129.0}
    assert target_price == pytest.approx(112.5)

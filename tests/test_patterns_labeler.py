import pytest

from src.foundation.market_common import derived_db
from src.signals.patterns.backtest.labeler import PatternLabel, create_pattern_labels_table, insert_label


@pytest.fixture
def conn():
    connection = derived_db.get_connection(":memory:")
    create_pattern_labels_table(connection)
    yield connection
    connection.close()


def test_insert_and_read_back_a_label(conn):
    label = PatternLabel(
        id="lbl-1", ticker="TST", timeframe="daily",
        window_start="2020-01-01", window_end="2020-03-01",
        pattern_type="head_and_shoulders", is_valid=True, notes="textbook",
        labeled_at="2020-03-02T00:00:00",
    )
    insert_label(conn, label)

    row = conn.execute(
        "SELECT ticker, pattern_type, is_valid, notes FROM pattern_labels WHERE id = 'lbl-1'"
    ).fetchone()
    assert row == ("TST", "head_and_shoulders", 1, "textbook")


def test_is_valid_false_stores_as_zero(conn):
    label = PatternLabel(
        id="lbl-2", ticker="TST", timeframe="daily",
        window_start="2020-01-01", window_end="2020-03-01",
        pattern_type="head_and_shoulders", is_valid=False, notes="",
        labeled_at="2020-03-02T00:00:00",
    )
    insert_label(conn, label)

    is_valid = conn.execute("SELECT is_valid FROM pattern_labels WHERE id = 'lbl-2'").fetchone()[0]
    assert is_valid == 0

"""Hidden-divergence detection (models.DivergenceForm.HIDDEN): the mirrored
inequalities on the same consecutive-pivot pairs regular detection already
evaluates. Synthetic fixtures follow test_divergences_synthetic's
conventions (hand-built bars + indicator series through detect_for_indicator;
monkeypatched detect() for confluence, matching test_divergences_confluence).
"""

import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.signals.divergences import detect as detect_mod
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.detect import detect, detect_for_indicator
from src.signals.divergences.models import Direction, Divergence, DivergenceForm, IndicatorKind
from src.signals.divergences.store import create_divergences_table, upsert_divergences
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe


def _bars(closes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=idx,
    )


def _series(values: list[float], like: pd.DataFrame) -> pd.Series:
    return pd.Series(values, index=like.index)


def _config(**overrides) -> DivergenceConfig:
    cfg = DivergenceConfig(
        atr_period=3, min_bars=0, warmup_bars=5, min_pivot_span_bars=5,
        indicators=["rsi"], rsi_reversal_points=5.0, pairing_window=3,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


# Price: HIGH pivots at bar_index 6 (130) and 16 (120) -- a LOWER high.
# RSI: HIGH pivots at the same bars, 70 then 80 -- a HIGHER high.
# => hidden bearish (price holds inside its prior extreme, indicator
# over-travels). The single interior LOW pivot on each side can't form a
# pair, so no bullish row of either form can appear.
_HIDDEN_BEARISH_CLOSES = [100, 101, 102, 103, 104, 105, 130, 115, 110, 105, 100, 95, 90, 96, 102, 110, 120, 112, 104, 96, 90, 85, 80, 75]
_INCREASING_RSI = [50, 52, 55, 58, 60, 65, 70, 60, 52, 45, 40, 35, 30, 38, 48, 60, 80, 70, 58, 46, 40, 36, 32, 28]

# Regular fixture copied from test_divergences_synthetic (price 120 -> 130
# higher high, RSI 80 -> 70 lower high) for the forms-gating and
# regular-unchanged tests below.
_REGULAR_BEARISH_CLOSES = [100, 101, 102, 103, 104, 105, 120, 115, 110, 105, 100, 95, 90, 100, 110, 120, 130, 125, 115, 105, 95, 90, 85, 80]
_DECREASING_RSI = [50, 52, 55, 58, 60, 65, 80, 75, 65, 55, 45, 35, 30, 40, 55, 65, 70, 60, 50, 40, 35, 30, 28, 25]

# Equal price highs (120, 120) with RSI higher high / lower high variants --
# only an extreme_equality_tolerance_atr > 0 makes these evaluable at all.
_EQUAL_HIGH_CLOSES = [100, 101, 102, 103, 104, 105, 120, 110, 100, 95, 90, 85, 80, 90, 100, 110, 120, 112, 104, 96, 90, 85, 80, 75]
_EQ_RSI_UP = [50, 52, 55, 58, 60, 65, 70, 60, 50, 42, 36, 32, 30, 40, 52, 64, 80, 70, 58, 46, 40, 36, 32, 28]
_EQ_RSI_DOWN = [50, 52, 55, 58, 60, 65, 80, 70, 60, 50, 40, 35, 30, 40, 52, 64, 70, 60, 50, 42, 36, 32, 30, 28]


def test_lower_price_high_with_higher_indicator_high_yields_hidden_bearish():
    bars = _bars(_HIDDEN_BEARISH_CLOSES)
    rsi = _series(_INCREASING_RSI, bars)

    divs = detect_for_indicator(bars, "rsi", rsi, _config(), "TST", Timeframe.DAILY)

    assert len(divs) == 1
    d = divs[0]
    assert d.form == DivergenceForm.HIDDEN
    assert d.direction == Direction.BEARISH
    assert d.indicator == IndicatorKind.RSI
    assert (d.p1_price, d.p2_price) == (130.0, 120.0)
    assert (d.i1_value, d.i2_value) == (70.0, 80.0)
    assert 0.0 < d.strength <= 1.0


def test_higher_price_low_with_lower_indicator_low_yields_hidden_bullish():
    # Same monotonic mirror transform test_divergences_synthetic uses for
    # its bullish case: HIGHs become LOWs, the RSI direction flips.
    bars = _bars([200 - c for c in _HIDDEN_BEARISH_CLOSES])
    rsi = _series([100 - v for v in _INCREASING_RSI], bars)

    divs = detect_for_indicator(bars, "rsi", rsi, _config(), "TST", Timeframe.DAILY)

    assert len(divs) == 1
    d = divs[0]
    assert d.form == DivergenceForm.HIDDEN
    assert d.direction == Direction.BULLISH
    assert (d.p1_price, d.p2_price) == (70.0, 80.0)
    assert (d.i1_value, d.i2_value) == (30.0, 20.0)


def test_regular_fixture_still_yields_exactly_one_regular_row_with_both_forms_enabled():
    # Hidden detection must be purely additive: the canonical regular
    # fixture's output is byte-identical to pre-hidden behavior, with the
    # row now carrying an explicit form.
    bars = _bars(_REGULAR_BEARISH_CLOSES)
    rsi = _series(_DECREASING_RSI, bars)

    divs = detect_for_indicator(bars, "rsi", rsi, _config(), "TST", Timeframe.DAILY)

    assert len(divs) == 1
    assert divs[0].form == DivergenceForm.REGULAR
    assert divs[0].direction == Direction.BEARISH


def test_forms_config_gates_each_form_independently():
    hidden_bars = _bars(_HIDDEN_BEARISH_CLOSES)
    hidden_rsi = _series(_INCREASING_RSI, hidden_bars)
    regular_bars = _bars(_REGULAR_BEARISH_CLOSES)
    regular_rsi = _series(_DECREASING_RSI, regular_bars)

    only_regular = _config(forms=["regular"])
    only_hidden = _config(forms=["hidden"])

    assert detect_for_indicator(hidden_bars, "rsi", hidden_rsi, only_regular, "TST", Timeframe.DAILY) == []
    assert detect_for_indicator(regular_bars, "rsi", regular_rsi, only_hidden, "TST", Timeframe.DAILY) == []
    # And each fixture still fires under the form it actually exhibits.
    assert len(detect_for_indicator(hidden_bars, "rsi", hidden_rsi, only_hidden, "TST", Timeframe.DAILY)) == 1
    assert len(detect_for_indicator(regular_bars, "rsi", regular_rsi, only_regular, "TST", Timeframe.DAILY)) == 1


def test_equal_highs_are_regular_with_a_weaker_indicator_and_nothing_with_a_stronger_one():
    # The tolerance loosening applies to REGULAR's price side only: equal
    # highs + weaker indicator is the classic double-top divergence
    # reading. Equal highs + STRONGER indicator is trend agreement, not a
    # hidden divergence -- hidden requires a strictly lower high, so the
    # tolerance band never converts agreement into a signal. Either way a
    # single pair emits at most one row.
    bars = _bars(_EQUAL_HIGH_CLOSES)
    config = _config(extreme_equality_tolerance_atr=1.0)

    up = detect_for_indicator(bars, "rsi", _series(_EQ_RSI_UP, bars), config, "TST", Timeframe.DAILY)
    down = detect_for_indicator(bars, "rsi", _series(_EQ_RSI_DOWN, bars), config, "TST", Timeframe.DAILY)

    assert up == []
    assert len(down) == 1
    assert down[0].form == DivergenceForm.REGULAR


def test_equal_highs_with_zero_tolerance_yield_nothing_in_either_form():
    # With tol=0 both price inequalities are strict, and exactly-equal
    # extremes satisfy neither -- the pre-hidden behavior, preserved.
    bars = _bars(_EQUAL_HIGH_CLOSES)
    config = _config(extreme_equality_tolerance_atr=0.0)

    assert detect_for_indicator(bars, "rsi", _series(_EQ_RSI_UP, bars), config, "TST", Timeframe.DAILY) == []
    assert detect_for_indicator(bars, "rsi", _series(_EQ_RSI_DOWN, bars), config, "TST", Timeframe.DAILY) == []


def test_unknown_or_empty_forms_config_raises_instead_of_silently_detecting_nothing():
    with pytest.raises(ValueError, match="forms"):
        DivergenceConfig(forms=["Hidden"])  # wrong case
    with pytest.raises(ValueError, match="forms"):
        DivergenceConfig(forms=["hiden"])  # typo
    with pytest.raises(ValueError, match="forms"):
        DivergenceConfig(forms=[])


def test_divergence_constructor_coerces_string_enum_fields():
    # A Divergence(**db_row) loader hands strings to every enum-typed
    # field; they must land as members (string str-enum equality passes ==
    # but hashes by value, silently splitting confluence's dict grouping).
    d = Divergence(
        id="x", ticker="T", timeframe="daily", indicator="rsi", direction="bearish",
        p1_date="2020-01-02T00:00:00", p2_date="2020-01-20T00:00:00",
        p1_price=130.0, p2_price=120.0, i1_value=70.0, i2_value=80.0,
        strength=0.5, duration_bars=10, price_move_atr=1.0,
        appeared_at="2020-01-20T00:00:00", confirmed_at="2020-01-22T00:00:00",
        form="hidden",
    )
    assert d.timeframe is Timeframe.DAILY
    assert d.indicator is IndicatorKind.RSI
    assert d.direction is Direction.BEARISH
    assert d.form is DivergenceForm.HIDDEN


# ---- confluence: within-form only (monkeypatched detect(), matching
# test_divergences_confluence's conventions) ----


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    idx = pd.bdate_range("2020-01-01", periods=60)
    closes = [100.0 + i for i in range(60)]
    frame = pd.DataFrame(
        {
            "timestamp": idx,
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
            "is_partial": [0] * len(closes),
        }
    ).set_index("timestamp")
    db.upsert_bars(connection, "bars_1d", "TST", db.YFINANCE_SPLIT_ONLY, frame)
    yield connection, idx
    connection.close()


def _divergence(indicator: str, p2_date: str, form: DivergenceForm) -> Divergence:
    return Divergence(
        id=f"id-{indicator}-{form.value}-{p2_date}", ticker="TST", timeframe=Timeframe.DAILY,
        indicator=IndicatorKind(indicator), direction=Direction.BEARISH, form=form,
        p1_date="2020-01-02T00:00:00", p2_date=p2_date,
        p1_price=100.0, p2_price=90.0, i1_value=80.0, i2_value=70.0,
        strength=0.5, duration_bars=10, price_move_atr=1.0,
        appeared_at=p2_date, confirmed_at=p2_date,
    )


def test_a_regular_and_a_hidden_row_on_the_same_swing_do_not_corroborate(conn, monkeypatch):
    connection, idx = conn
    p2 = idx[20].isoformat()
    fixed = [
        _divergence("rsi", p2, DivergenceForm.REGULAR),
        _divergence("macd_hist", p2, DivergenceForm.HIDDEN),
    ]
    monkeypatch.setattr(detect_mod, "detect_divergences", lambda *a, **k: fixed)

    divs, _report, skip = detect(
        connection, "TST", Timeframe.DAILY, DivergenceConfig(min_bars=0), as_of=idx[25].isoformat()
    )

    assert skip is None
    assert len(divs) == 2
    for d in divs:
        assert d.confluence_count == 1
        assert d.agreeing_indicators == d.indicator.value


def test_two_hidden_rows_on_the_same_swing_do_corroborate(conn, monkeypatch):
    connection, idx = conn
    fixed = [
        _divergence("rsi", idx[20].isoformat(), DivergenceForm.HIDDEN),
        _divergence("macd_hist", idx[21].isoformat(), DivergenceForm.HIDDEN),
    ]
    monkeypatch.setattr(detect_mod, "detect_divergences", lambda *a, **k: fixed)

    divs, _report, skip = detect(
        connection, "TST", Timeframe.DAILY, DivergenceConfig(min_bars=0), as_of=idx[25].isoformat()
    )

    assert skip is None
    assert len(divs) == 2
    for d in divs:
        assert d.confluence_count == 2
        assert d.agreeing_indicators == "macd_hist,rsi"


# ---- store: form round-trip + additive migration of a pre-form table ----


# The OLDEST schema a live table can have: pre-confluence (Done #44) and
# pre-form. This is what the shared derived DB actually contained when the
# first full-universe backfill ran (2026-10-04) -- a migration test
# starting from any newer snapshot silently skips the columns that
# actually bit.
_LEGACY_SCHEMA = """
CREATE TABLE divergences (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT, indicator TEXT,
    direction TEXT,
    p1_date TEXT, p2_date TEXT,
    p1_price REAL, p2_price REAL,
    i1_value REAL, i2_value REAL,
    strength REAL,
    duration_bars INTEGER, price_move_atr REAL, indicator_gap_raw REAL,
    appeared_at TEXT, confirmed_at TEXT,
    max_favorable_move_atr REAL, bars_to_max_favorable_move INTEGER,
    invalidated INTEGER, invalidated_at TEXT, outcome_computed_through TEXT,
    run_id TEXT,
    UNIQUE (ticker, timeframe, indicator, direction, p2_date)
);
"""


def test_store_roundtrips_form():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    create_divergences_table(connection)

    bars = _bars(_HIDDEN_BEARISH_CLOSES)
    rsi = _series(_INCREASING_RSI, bars)
    divs = detect_for_indicator(bars, "rsi", rsi, _config(), "TST", Timeframe.DAILY)
    assert len(divs) == 1
    upsert_divergences(connection, divs, "run-1")

    stored = connection.execute("SELECT form, direction FROM divergences").fetchone()
    assert stored == ("hidden", "bearish")
    connection.close()


def test_pre_form_table_is_migrated_and_legacy_rows_backfilled_as_regular():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    connection.execute(_LEGACY_SCHEMA)
    connection.execute(
        "INSERT INTO divergences (id, ticker, timeframe, indicator, direction, p2_date)"
        " VALUES ('legacy-1', 'OLD', 'daily', 'rsi', 'bearish', '2020-06-01T00:00:00')"
    )
    connection.commit()

    # Re-running table creation against the legacy table performs the
    # additive migration (same CREATE IF NOT EXISTS + ALTER pattern every
    # bootstrap path goes through).
    create_divergences_table(connection)

    assert connection.execute(
        "SELECT form, confluence_count, agreeing_indicators FROM divergences WHERE id = 'legacy-1'"
    ).fetchone() == ("regular", 1, None)

    # The DEFAULT also covers a column-omitting insert AFTER migration --
    # the shared derived DB can still be written by pre-form code from
    # another checkout, which a one-shot backfill UPDATE would miss.
    connection.execute(
        "INSERT INTO divergences (id, ticker, timeframe, indicator, direction, p2_date)"
        " VALUES ('legacy-2', 'OLD', 'daily', 'rsi', 'bearish', '2020-07-01T00:00:00')"
    )
    assert connection.execute(
        "SELECT form FROM divergences WHERE id = 'legacy-2'"
    ).fetchone() == ("regular",)

    # And a post-migration upsert of a hidden row works against the
    # migrated table.
    bars = _bars(_HIDDEN_BEARISH_CLOSES)
    rsi = _series(_INCREASING_RSI, bars)
    divs = detect_for_indicator(bars, "rsi", rsi, _config(), "TST", Timeframe.DAILY)
    upsert_divergences(connection, divs, "run-after-migration")
    assert connection.execute(
        "SELECT form FROM divergences WHERE ticker = 'TST'"
    ).fetchone() == ("hidden",)
    connection.close()

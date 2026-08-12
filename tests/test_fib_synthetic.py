import math

import pandas as pd
import pytest

from src.fibonacci.config import FibConfig
from src.fibonacci.engine import detect
from src.fibonacci.levels import compute_levels
from src.fibonacci.lifecycle import evaluate_lifecycle
from src.fibonacci.models import FibSetStatus, FibSwing, SwingDirection
from src.fibonacci.swings import detect_swings
from src.fibonacci import store as store_mod
from src.market_common import derived_db
from src.data_processing import db as raw_db


def _make_swing(
    origin_price, end_price, direction,
    origin_date="2020-01-01T00:00:00", end_date="2020-01-15T00:00:00",
    scale_mult=2.0, magnitude_atr=20.0, duration_bars=10, confirmed_at="2020-01-16T00:00:00",
):
    return FibSwing(
        origin_date=origin_date, origin_price=origin_price,
        end_date=end_date, end_price=end_price,
        direction=direction, scale_mult=scale_mult, magnitude_atr=magnitude_atr,
        duration_bars=duration_bars, confirmed_at=confirmed_at,
    )


def _ramp_close(legs: list[tuple[float, float, int]], start="2020-01-01") -> pd.Series:
    """legs: consecutive (start_price, end_price, n_bars) ramps, linear
    per-bar steps -- e.g. [(100, 300, 20), (300, 100, 20)] is a clean
    up-then-down zigzag with no internal noise, so pivot detection at any
    scale below the leg's own amplitude lands on exactly the same peak/
    trough bar regardless of scale (only confirmation *timing* differs) --
    the property several dedup tests below rely on."""
    values = [legs[0][0]]
    for s, e, n in legs:
        step = (e - s) / n
        values.extend(s + step * i for i in range(1, n + 1))
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx)


def _flat_atr(close: pd.Series, value: float = 10.0) -> pd.Series:
    return pd.Series(value, index=close.index)


# ---------------------------------------------------------------------------
# 1/2: retracement + extension prices for a clean up-swing, exact arithmetic
# ---------------------------------------------------------------------------

def test_up_swing_retracement_prices_match_formula():
    swing = _make_swing(origin_price=100.0, end_price=200.0, direction=SwingDirection.UP)
    config = FibConfig()

    levels = compute_levels(swing, config)
    retracements = {lvl.ratio: lvl.price for lvl in levels if lvl.kind.value == "retracement"}

    for r in config.retracement_ratios:
        expected = 200.0 - r * (200.0 - 100.0)
        assert retracements[r] == pytest.approx(expected)
    assert retracements[0.5] == pytest.approx(150.0)
    assert retracements[0.618] == pytest.approx(138.2)


def test_up_swing_extension_prices_match_formula():
    swing = _make_swing(origin_price=100.0, end_price=200.0, direction=SwingDirection.UP)
    config = FibConfig()

    levels = compute_levels(swing, config)
    extensions = {lvl.ratio: lvl.price for lvl in levels if lvl.kind.value == "extension"}

    for r in config.extension_ratios:
        expected = 100.0 + r * (200.0 - 100.0)
        assert extensions[r] == pytest.approx(expected)
    assert extensions[1.618] == pytest.approx(261.8)
    assert extensions[2.0] == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# 3: down-swing mirror
# ---------------------------------------------------------------------------

def test_down_swing_retracement_and_extension_are_the_mirror():
    swing = _make_swing(origin_price=150.0, end_price=100.0, direction=SwingDirection.DOWN)
    config = FibConfig()

    levels = compute_levels(swing, config)
    retracements = {lvl.ratio: lvl.price for lvl in levels if lvl.kind.value == "retracement"}
    extensions = {lvl.ratio: lvl.price for lvl in levels if lvl.kind.value == "extension"}

    for r in config.retracement_ratios:
        assert retracements[r] == pytest.approx(100.0 + r * (150.0 - 100.0))
    for r in config.extension_ratios:
        assert extensions[r] == pytest.approx(150.0 - r * (150.0 - 100.0))
    assert retracements[0.5] == pytest.approx(125.0)
    assert extensions[2.0] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# 4: log-scale mode
# ---------------------------------------------------------------------------

def test_log_scale_interpolation_differs_from_linear():
    swing = _make_swing(origin_price=100.0, end_price=200.0, direction=SwingDirection.UP)
    linear_levels = compute_levels(swing, FibConfig(price_scale="linear"))
    log_levels = compute_levels(swing, FibConfig(price_scale="log"))

    linear_50 = next(lvl.price for lvl in linear_levels if lvl.kind.value == "retracement" and lvl.ratio == 0.5)
    log_50 = next(lvl.price for lvl in log_levels if lvl.kind.value == "retracement" and lvl.ratio == 0.5)

    assert linear_50 == pytest.approx(150.0)
    # Log-space midpoint is the geometric mean, not the arithmetic mean.
    assert log_50 == pytest.approx(math.sqrt(100.0 * 200.0))
    assert log_50 != pytest.approx(linear_50)


# ---------------------------------------------------------------------------
# 5/6/7: multi-scale swing detection -- dedup + distinctness + magnitude filter
# ---------------------------------------------------------------------------

def test_same_swing_at_two_scales_within_tolerance_keeps_only_highest_scale():
    # A clean up-then-down-then-up zigzag (peak@bar20=300, trough@bar40=100).
    # ZigZag bootstrap semantics mean the series' own opening bar (bar0)
    # also becomes a confirmed pivot once price first moves away from it by
    # threshold -- so this shape actually yields 2 swings per scale: an
    # UP (bar0->bar20) and a DOWN (bar20->bar40) -- but since both are big
    # enough (200-pt legs) to confirm identically at scale=2 (thresh 20)
    # and scale=8 (thresh 80), all 4 raw swings collapse into these same 2,
    # each surviving only as its scale=8 instance.
    close = _ramp_close([(100, 300, 20), (300, 100, 20), (100, 300, 20)])
    atr = _flat_atr(close)
    config = FibConfig(scales=[2.0, 8.0], min_swing_atr=8.0, dedup_bar_tolerance=3)

    swings = detect_swings(close, atr, config)

    assert len(swings) == 2
    assert all(s.scale_mult == 8.0 for s in swings)
    up = next(s for s in swings if s.direction == SwingDirection.UP)
    down = next(s for s in swings if s.direction == SwingDirection.DOWN)
    assert (up.origin_price, up.end_price) == pytest.approx((100.0, 300.0))
    assert (down.origin_price, down.end_price) == pytest.approx((300.0, 100.0))


def test_distinct_swings_at_different_scales_are_not_deduped():
    # Block 1 (bars 0-40, amplitude 60: 100->160->100) only ever clears
    # scale=2's threshold (20), never scale=8's (80), so its UP/DOWN legs
    # only appear via the scale=2 pass. Block 2 (bars 40-80, amplitude
    # 220: 100->320->100) clears both scales -- its DOWN leg (bar60->80)
    # is a genuine cross-scale duplicate (same origin AND end bar at both
    # scales) and correctly collapses to one scale=8 instance. Its UP leg
    # is the interesting case: scale=2 sees it as bar40->bar60 (from block
    # 1's own trough) while scale=8's bootstrap never confirmed a pivot
    # until bar60 either, so scale=8 sees the *same* UP leg as bar0->bar60
    # (from the series' own opening bar). Both end at bar60/price 320, but
    # their origins differ by 40 bars (> dedup_bar_tolerance) -- sharing
    # only one endpoint is explicitly NOT a duplicate per spec, so both
    # must survive.
    close = _ramp_close(
        [(100, 160, 20), (160, 100, 20), (100, 320, 20), (320, 100, 20), (100, 320, 20)]
    )
    atr = _flat_atr(close)
    config = FibConfig(scales=[2.0, 8.0], min_swing_atr=5.0, dedup_bar_tolerance=3)

    swings = detect_swings(close, atr, config)

    assert len(swings) == 5

    ups_to_320 = [s for s in swings if s.direction == SwingDirection.UP and s.end_price == pytest.approx(320.0)]
    assert len(ups_to_320) == 2
    assert {s.origin_bar_index for s in ups_to_320} == {0, 40}
    assert abs(ups_to_320[0].origin_bar_index - ups_to_320[1].origin_bar_index) > config.dedup_bar_tolerance

    downs_from_320 = [s for s in swings if s.direction == SwingDirection.DOWN and s.origin_price == pytest.approx(320.0)]
    assert len(downs_from_320) == 1  # the true duplicate: deduped down to a single (scale=8) instance
    assert downs_from_320[0].scale_mult == 8.0

    small_block = [s for s in swings if s.end_price == pytest.approx(160.0) or s.origin_price == pytest.approx(160.0)]
    assert len(small_block) == 2
    assert all(s.scale_mult == 2.0 for s in small_block)  # never confirms at scale=8, so no dedup partner exists


def test_swing_below_min_swing_atr_is_discarded():
    # Same block-1 shape as above (amplitude 60, magnitude_atr = 60/10 = 6)
    # but with min_swing_atr raised above that -- must be dropped entirely.
    close = _ramp_close([(100, 160, 20), (160, 100, 20), (100, 160, 20)])
    atr = _flat_atr(close)
    config = FibConfig(scales=[2.0], min_swing_atr=8.0)

    swings = detect_swings(close, atr, config)

    assert swings == []


# ---------------------------------------------------------------------------
# 9: lifecycle / invalidation
# ---------------------------------------------------------------------------

def test_price_beyond_swing_end_stays_active():
    swing = _make_swing(
        origin_price=100.0, end_price=200.0, direction=SwingDirection.UP,
        end_date="2020-01-15T00:00:00",
    )
    close = pd.Series(
        [210.0, 250.0],
        index=pd.to_datetime(["2020-01-16", "2020-01-20"]),
    )

    status, invalidated_date = evaluate_lifecycle(swing, close)

    assert status == FibSetStatus.ACTIVE
    assert invalidated_date is None


def test_price_beyond_swing_origin_invalidates_and_stays_terminal():
    swing = _make_swing(
        origin_price=100.0, end_price=200.0, direction=SwingDirection.UP,
        end_date="2020-01-15T00:00:00",
    )
    close = pd.Series(
        [210.0, 250.0, 90.0, 150.0],  # breaches origin(100) on 2020-02-01, recovers after
        index=pd.to_datetime(["2020-01-16", "2020-01-20", "2020-02-01", "2020-02-05"]),
    )

    status, invalidated_date = evaluate_lifecycle(swing, close)

    assert status == FibSetStatus.INVALIDATED
    assert invalidated_date == pd.Timestamp("2020-02-01").isoformat()


def test_down_swing_invalidates_on_close_above_origin():
    swing = _make_swing(
        origin_price=200.0, end_price=100.0, direction=SwingDirection.DOWN,
        end_date="2020-01-15T00:00:00",
    )
    close = pd.Series(
        [90.0, 210.0],  # first stays inside/beyond end (fine), then breaches origin(200) upward
        index=pd.to_datetime(["2020-01-16", "2020-01-20"]),
    )

    status, invalidated_date = evaluate_lifecycle(swing, close)

    assert status == FibSetStatus.INVALIDATED
    assert invalidated_date == pd.Timestamp("2020-01-20").isoformat()


# ---------------------------------------------------------------------------
# 8: max_sets ranking -- only the top-K by weight are selected
# ---------------------------------------------------------------------------

def test_more_than_max_sets_qualifying_swings_keeps_only_top_k_by_weight(monkeypatch):
    # Fabricate 4 already-built swings with distinct, easily-ranked weights
    # by controlling magnitude_atr/duration_bars directly (weight is a pure
    # function of those plus bars_since_end -- see levels.compute_weight),
    # and drive engine.detect's selection logic without needing a real
    # multi-swing price series: monkeypatch detect_swings to return them.
    # bars_since_end (hence the recency weight component) is identical
    # across all four here -- none set origin/end_bar_index, so they
    # default to 0 -- so ranking below is driven purely by
    # magnitude_atr/duration_bars, which is enough on its own for an
    # unambiguous top-2. end_date values are just distinguishing labels.
    swings = [
        _make_swing(100, 200, SwingDirection.UP, magnitude_atr=40.0, duration_bars=250,
                    end_date="2020-06-01T00:00:00"),  # highest weight
        _make_swing(100, 190, SwingDirection.UP, magnitude_atr=30.0, duration_bars=200,
                    end_date="2020-05-01T00:00:00"),
        _make_swing(100, 180, SwingDirection.UP, magnitude_atr=20.0, duration_bars=150,
                    end_date="2020-04-01T00:00:00"),
        _make_swing(100, 170, SwingDirection.UP, magnitude_atr=1.0, duration_bars=1,
                    end_date="2020-01-02T00:00:00"),  # lowest weight
    ]
    monkeypatch.setattr("src.fibonacci.engine.detect_swings", lambda close, atr, config: swings)

    conn = raw_db.get_connection(":memory:")
    raw_db.create_tables(conn)
    idx = pd.bdate_range("2020-01-01", periods=200)
    bars = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000, "is_partial": 0},
        index=idx,
    )
    raw_db.upsert_bars(conn, "bars_1d", "TEST", raw_db.YFINANCE, bars)

    config = FibConfig(max_sets=2, min_bars=50)
    result = detect(conn, "TEST", "daily", config)

    assert len(result.all_sets) == 4
    assert len(result.selected_sets) == 2
    selected_end_dates = {s.swing.end_date for s in result.selected_sets}
    assert selected_end_dates == {"2020-06-01T00:00:00", "2020-05-01T00:00:00"}
    assert all(s1.weight >= s2.weight for s1, s2 in zip(result.all_sets, result.all_sets[1:]))


# ---------------------------------------------------------------------------
# 10: store upsert idempotency (real source bars, in-memory derived DB)
# ---------------------------------------------------------------------------

def test_rerunning_detection_and_storing_is_idempotent(sqlite_market_db):
    raw_conn = sqlite_market_db
    derived_conn = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(derived_conn)
    store_mod.create_tables(derived_conn)

    config = FibConfig()
    counts = []
    for _ in range(2):
        result = detect(raw_conn, "AAPL", "daily", config)
        run_id = derived_db.record_run(
            derived_conn, "fibonacci", "AAPL", "daily", None, "{}",
            result.quality.rows_dropped, result.quality.unreliable,
        )
        for fib_set in result.selected_sets:
            store_mod.upsert_fib_set(derived_conn, fib_set, run_id)
        n_sets = derived_conn.execute("SELECT COUNT(*) FROM fib_sets").fetchone()[0]
        n_levels = derived_conn.execute("SELECT COUNT(*) FROM fib_levels").fetchone()[0]
        counts.append((n_sets, n_levels))

    assert counts[0][0] > 0
    assert counts[0] == counts[1]

    # Every fib_levels row's fib_set_id must resolve to a real, still-unique
    # fib_sets row (child rows correctly re-tied to the same parent id on
    # the second run, not orphaned onto a freshly minted one).
    orphans = derived_conn.execute(
        "SELECT COUNT(*) FROM fib_levels WHERE fib_set_id NOT IN (SELECT id FROM fib_sets)"
    ).fetchone()[0]
    assert orphans == 0


@pytest.fixture
def sqlite_market_db():
    import pathlib
    db_path = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "market_data.sqlite"
    if not db_path.exists():
        pytest.skip("real market_data.sqlite not available")
    conn = raw_db.get_connection(str(db_path))
    yield conn
    conn.close()

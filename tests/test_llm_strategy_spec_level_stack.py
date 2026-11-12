"""The level-stack finder: detection on hand-built inputs (levels and divergences given
directly, ATR pinned to 1, price flat at 105 with one touch bar), the near-miss rings, the
control, the spec mapping and its refusals, and the inputs built from real detectors on a
synthetic ticker."""

import numpy as np
import pandas as pd
import pytest

from src.llm.strategy_spec import finders, level_stack
from src.llm.strategy_spec.finders import GroundingError
from src.llm.strategy_spec.level_stack import TickerInputs, find_level_stack, is_level_stack, plan
from src.llm.strategy_spec.schema import (
    Control, Duration, Proximity, Rule, Setting, Signal, Size, StrategySpec, Trigger)

N = 200
TOUCH = 150  # the touch bar's position
DATES = pd.bdate_range("2015-01-02", periods=N)


def spec(**overrides) -> StrategySpec:
    """The level-stack spec as elicited (done.md #185), filters on their defaults."""
    filters = [
        Signal(name="Support line", description="an S/R line", role="filter",
               uses=["detector:sr_line.touch", "detector:sr_line.body_touch"], defaults_ok=True),
        Signal(name="Fibonacci level", description="a retracement", role="filter",
               uses=["detector:fibonacci.retracement"], defaults_ok=True),
        Signal(name="Bullish divergence", description="a divergence", role="filter",
               uses=["detector:divergence.rsi", "detector:divergence.obv"], defaults_ok=True),
        Signal(name="AVWAP", description="an AVWAP", role="filter", uses=["detector:avwap"], defaults_ok=True),
        Signal(name="Gap fill", description="a gap", role="filter",
               uses=["detector:gap.classic", "detector:gap.fvg"], defaults_ok=True),
    ]
    fields = dict(
        name="stack", direction="long", timeframe="daily",
        duration=Duration(description="30 to 400 bars", min_bars=30, max_bars=400),
        size=Size(description="within 1 ATR", normalisation="atr", max=1.0),
        trigger=Trigger(description="the low touches the stack", price_basis="intraday", execution="next_open",
                        proximity=Proximity(normalisation="atr", max=0.3)),
        horizons_bars=[10, 21, 63],
        invalidation=[Rule(description="close below the zone bottom", phase="before_entry"),
                      Rule(description="close below the zone bottom", phase="after_entry")],
        filters_needed=2, supporting_signals=filters,
        control=Control(description="retests of a single level, not stacked"),
        uses=[u for f in filters for u in f.uses])
    return StrategySpec(**{**fields, **overrides})


def inputs(levels: list[tuple], touch_low: float = 100.2, touch_close: float = 101.0,
           divergences: list[int] = (), lows: dict[int, float] | None = None) -> TickerInputs:
    """Price at 105 (low 104.5), one touch bar at TOUCH. `levels`: (kind, lo, hi, formed
    position, first position it stands on); each stands from then to the end."""
    close = np.full(N, 105.0)
    low = np.full(N, 104.5)
    low[TOUCH], close[TOUCH] = touch_low, touch_close
    for p, v in (lows or {}).items():
        low[p] = v
    bars = pd.DataFrame({"open": close, "high": close + 0.5, "low": low, "close": close, "volume": 1e6},
                        index=DATES)
    rows = [(DATES[p], kind, lo, hi, DATES[formed], f"{kind}{i}", kind)
            for i, (kind, lo, hi, formed, first) in enumerate(levels) for p in range(first, N)]
    lv = pd.DataFrame(rows, columns=["date", "kind", "lo", "hi", "formed", "key", "label"])
    div = pd.DataFrame({"confirmed": [DATES[p] for p in divergences], "invalidated": pd.NaT,
                        "indicator": "rsi", "form": "regular", "p1_date": DATES[0], "p1_price": 100.0,
                        "p2_date": [DATES[p] for p in divergences], "p2_price": 99.0})
    div["invalidated"] = pd.to_datetime(div["invalidated"])
    return TickerInputs(bars, pd.Series(1.0, index=DATES), lv, div)


def panel(*tickers: str) -> pd.DataFrame:
    return pd.DataFrame([(t, d) for t in tickers for d in DATES[1:]], columns=["ticker", "date"])


SR = ("sr_line", 99.8, 100.0, 50, 60)    # top 100.0: the touch at 100.2 is 0.2 ATR above it
FIB = ("fib", 99.4, 99.4, 40, 60)        # 0.6 ATR below the top: in a 1-ATR stack
WIDE_FIB = ("fib", 98.8, 98.8, 40, 60)   # 1.2 ATR below: only in a 1.5-ATR stack


def run(levels, **kw):
    spec_kw = kw.pop("spec_kw", {})
    return find_level_stack(spec(**spec_kw), panel("AAA"), {"AAA": inputs(levels, **kw)}, progress=None)


def dates(cands):
    return [(c.ticker, c.date) for c in cands]


def test_two_kinds_within_the_width_touched_from_above_is_a_match():
    r = run([SR, FIB])
    assert dates(r.matches) == [("AAA", DATES[TOUCH])]
    stack = r.matches[0].stack
    assert stack.kinds == ("fib", "sr_line") and stack.zone == (99.4, 100.0)
    assert r.chart_bars["AAA"]["date"].iloc[0] == DATES[0]  # the traded bars the finder detected on


def test_a_touch_bar_closing_below_the_zone_bottom_does_not_fire():
    assert run([SR, FIB], touch_low=99.0, touch_close=99.3).matches == ()


def test_one_kind_is_not_a_stack_but_is_the_control_and_the_count_ring():
    r = run([SR])
    assert r.matches == ()
    assert [c.fails for c in r.near_misses] == ["kinds: only 1 kind, not 2"]
    control = find_level_stack(spec(), panel("AAA"), {"AAA": inputs([SR])}, control=True, progress=None)
    assert dates(control.matches) == [("AAA", DATES[TOUCH])] and control.near_misses == ()
    assert find_level_stack(spec(), panel("AAA"), {"AAA": inputs([SR, FIB])}, control=True,
                            progress=None).matches == ()  # a stack isn't a single-level retest


def test_the_chart_geometry_follows_each_level_and_names_it():
    i = inputs([SR, FIB], divergences=[TOUCH - 10])
    stack = find_level_stack(spec(), panel("AAA"), {"AAA": i}, progress=None).matches[0].stack
    assert stack.divergence_label == "bullish regular divergence (RSI)"
    sr = next(line for line in stack.lines if line.label.startswith("sr_line"))
    # As known at each previous close: the first point is the bar after the level first stood.
    assert sr.dates[0] == DATES[61] and sr.dates[-1] == DATES[TOUCH] and set(sr.values) == {100.0}


def test_a_touched_level_deeper_than_the_width_heads_no_stack():
    deep_gap = ("gap", 98.5, 100.1, 50, 60)  # 1.6 ATR deep: can't fit in a 1-ATR stack
    assert run([deep_gap, FIB]).matches == ()
    assert dates(run([deep_gap, SR, FIB]).matches) == [("AAA", DATES[TOUCH])]  # the S/R heads one instead


def test_two_levels_of_one_kind_count_once():
    assert run([SR, ("sr_line", 99.5, 99.6, 50, 60)]).matches == ()


def test_a_level_too_far_below_the_top_is_a_width_near_miss():
    r = run([SR, WIDE_FIB])
    assert r.matches == () and [c.fails.split(":")[0] for c in r.near_misses] == ["stack width"]


def test_a_touch_short_of_the_proximity_is_a_proximity_near_miss():
    r = run([SR, FIB], touch_low=100.4)  # 0.4 ATR above the top: within 0.45, not 0.3
    assert r.matches == () and [c.fails.split(":")[0] for c in r.near_misses] == ["how close"]


def test_level_age_bounds_apply_to_every_level_and_ring_each_way():
    young = ("fib", 99.4, 99.4, TOUCH - 25, TOUCH - 20)  # 25 bars old: under 30, over 20
    r = run([SR, young])
    assert r.matches == () and [c.fails.split(":")[0] for c in r.near_misses] == ["level age"]
    assert "under your 30" in r.near_misses[0].fails
    old = ("fib", 99.4, 99.4, 0, 60)
    r = run([SR, old], spec_kw={"duration": Duration(min_bars=30, max_bars=120)})  # 150 old: over 120, under 180
    assert r.matches == () and "over your 120" in r.near_misses[0].fails


def test_a_recent_bullish_divergence_counts_as_a_kind():
    assert dates(run([SR], divergences=[TOUCH - 10]).matches) == [("AAA", DATES[TOUCH])]
    r = run([SR], divergences=[TOUCH - 50])  # 50 bars back: within 60, not 40
    assert r.matches == () and r.near_misses[0].fails.startswith("divergence")
    r = run([SR], divergences=[TOUCH + 1])  # confirmed after the touch: not known then
    assert r.matches == ()


def test_an_invalidated_divergence_does_not_count():
    i = inputs([SR], divergences=[TOUCH - 10])
    i.divergences.loc[0, "invalidated"] = DATES[TOUCH - 2]
    assert find_level_stack(spec(), panel("AAA"), {"AAA": i}, progress=None).matches == ()


def test_levels_count_as_they_stood_at_the_previous_close():
    late = ("fib", 99.4, 99.4, 40, TOUCH)  # first stands at the touch bar's own close
    assert run([SR, late]).matches == ()


def test_only_the_first_bar_of_a_touch_run_fires():
    r = run([SR, FIB], lows={TOUCH - 1: 100.1})  # the bar before already touched
    assert DATES[TOUCH] not in [c.date for c in r.matches]


def test_a_level_above_the_previous_close_is_not_support():
    above = ("fib", 105.2, 105.2, 40, 60)
    assert run([("sr_line", 99.8, 100.0, 50, 60), above]).matches == ()


def test_the_rubric_says_where_each_rule_came_from():
    lines = {r.parameter: r for r in run([SR, FIB]).rubric}
    assert lines["stack width"].source == "spec" and "1 ATR" in lines["stack width"].value
    assert lines["how close price must come"].source == "spec" and "0.3 ATR" in lines["how close price must come"].value
    assert lines["kinds needed"].source == "spec" and lines["level age"].source == "spec"
    assert lines["zone bottom"].source == "default"
    assert lines["invalidation (after entry): close below the zone bottom"].value == "NOT APPLIED"
    assert lines["universe"].value == "1 of the panel's 1 tickers"


def test_the_spec_mapping():
    p = plan(spec())
    assert set(p.kinds) == {"sr_line", "fib", "divergence", "avwap", "gap"}
    assert p.gap_kinds == ("classic", "fvg") and p.divergence_indicators == ("obv", "rsi")
    assert (p.params.width, p.params.proximity, p.params.age_min, p.params.age_max, p.params.count) == \
        (1.0, 0.3, 30, 400, 2)


@pytest.mark.parametrize("change, reason", [
    ({"timeframe": "weekly"}, "weekly"),
    ({"direction": "short"}, "long side"),
    ({"size": Size(normalisation="pct", max=2.0)}, "ATR"),
    ({"filters_needed": None}, "isn't complete"),
])
def test_refusals(change, reason):
    with pytest.raises(GroundingError, match=reason):
        plan(spec(**change))


def test_a_filter_with_its_own_settings_is_refused():
    s = spec()
    s.supporting_signals[0].settings = [Setting(name="window_years", value="8")]
    with pytest.raises(GroundingError, match="settings"):
        plan(s)


# ---------------------------------------------------------------- inputs from the detectors


def _walk(n=600, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    close = 40 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, n)))
    open_ = close * np.exp(rng.normal(0, 0.015, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.008, n)))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.integers(10_000, 50_000, n).astype(float)}, index=idx)


@pytest.fixture(scope="module")
def walk():
    return _walk()


@pytest.fixture(scope="module")
def built(walk):
    return level_stack.ticker_inputs("RW", walk, None, walk.index[200], root=None,
                                     divergence_indicators=("rsi", "macd_hist", "obv"))


def test_inputs_divergences_equal_the_detectors_as_of_run(walk, built):
    from src.foundation.data_processing import db as raw_db
    from src.foundation.market_common.models import Timeframe
    from src.signals.divergences import detect as div_detect
    from src.signals.divergences.config import DivergenceConfig
    conn = raw_db.get_connection(":memory:")
    raw_db.create_tables(conn)
    raw_db.upsert_bars(conn, "bars_1d", "RW", raw_db.YFINANCE_SPLIT_ONLY, built.bars.assign(is_partial=0))
    config = DivergenceConfig(indicators=["rsi", "macd_hist", "obv"])
    seen = 0
    for t in built.bars.index[300::60]:
        found, _, _ = div_detect.detect(conn, "RW", Timeframe.DAILY, config, as_of=t)
        expected = sorted((pd.Timestamp(d.confirmed_at), d.indicator.value, round(d.p2_price, 9))
                          for d in found if d.direction.value == "bullish")
        mine = built.divergences[built.divergences["confirmed"] <= t]
        assert sorted(zip(mine["confirmed"], mine["indicator"], mine["p2_price"].round(9))) == expected, t
        seen += bool(expected)
    conn.close()
    assert seen, "fixture should have bullish divergences"


def test_inputs_gaps_are_the_unfilled_part_of_bullish_gaps(walk, built):
    from src.models.features import levels
    from src.signals.gaps.detect import detect_on_bars
    from src.signals.gaps.relevance import gap_states
    config = levels.default_configs()["gaps"]
    gaps, _ = detect_on_bars(built.bars, "RW", levels.DAILY, config)
    states = gap_states(built.bars, gaps, built.bars.index[199:], config)
    bullish = states[states["direction"] == "bullish"]
    mine = built.levels[built.levels["kind"] == "gap"]
    assert len(mine) == len(bullish) and len(states) > len(bullish)  # bearish gaps left out
    row = bullish.iloc[len(bullish) // 2]
    got = mine[(mine["date"] == row["date"]) & (mine["lo"] == row["zone_bottom"])]
    height = row["zone_top"] - row["zone_bottom"]
    assert np.isclose(got["hi"].iloc[0], row["zone_top"] - height * row["max_fill_pct"] / 100)


def test_inputs_avwap_is_its_line_and_fib_only_retracements(built):
    avwap = built.levels[built.levels["kind"] == "avwap"]
    assert len(avwap) and (avwap["lo"] == avwap["hi"]).all()
    assert set(built.levels["kind"]) <= {"sr_line", "fib", "avwap", "gap"}
    assert built.levels["key"].str.startswith("fib@").sum() and \
        built.levels.loc[built.levels["kind"] == "fib", "key"].str.contains("retracement_").all()


def test_dispatch_sends_a_stack_shaped_spec_here_and_nothing_else():
    assert is_level_stack(spec())
    assert finders.pick_finder(spec()) == level_stack.LEVEL_STACK
    ma = spec(uses=["detector:ma.first_touch"], supporting_signals=[])
    assert not is_level_stack(ma) and finders.pick_finder(ma) == "detector:ma.first_touch"
    no_price = spec(supporting_signals=[spec().supporting_signals[2]], filters_needed=1)
    assert not is_level_stack(no_price)  # a divergence alone has no level to touch

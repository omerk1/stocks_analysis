"""The first-touch instance finder (step 4): detection against an engineered panel,
near-miss rings, the rubric's source labels, and the refusals.

The synthetic panel is built from the *signal-bar* distance series directly (ATR pinned
to 1, the MA flat at 100), then lagged one bar exactly as the cached feature panel is —
so the tests assert the finder's unlag-and-detect against known bar positions, not
against a re-derivation of the detector.
"""

import pandas as pd
import pytest

from src.llm.strategy_spec import finders
from src.llm.strategy_spec.finders import GroundingError, find_first_touch
from src.llm.strategy_spec.schema import Rule, Signal, Size, StrategySpec, Trigger

QUIET = [0.5] * 10  # not away even relaxed (< 1.0/1.5), not a touch even relaxed (> 0.375)

# Signal-bar distance sequences; the bar to find is where the commented value sits.
MATCH = QUIET + [2.0] * 5 + [0.1] + QUIET              # away, then a clean touch
TOUCH_RING = QUIET + [2.0] * 5 + [0.3] + QUIET         # only comes within 0.3 ATR
AWAY_RING = QUIET + [0.8] * 5 + [0.1] + QUIET          # was never a full 1.0 ATR away
DAYS_RING = QUIET + [2.0] * 5 + [0.5] * 11 + [0.1] + QUIET  # touches on bar 12, not 10
SHORT_MATCH = [-x for x in MATCH]                      # the same setup from below


def panel(ticker_dists: dict[str, list[float]], start: str = "2015-01-02") -> pd.DataFrame:
    frames = []
    for ticker, dist in ticker_dists.items():
        dist = pd.Series(dist, dtype="float64")
        close = 100.0 + dist  # MA flat at 100, ATR pinned at 1: dist_atr == close - MA
        frames.append(pd.DataFrame({
            "ticker": ticker, "date": pd.bdate_range(start, periods=len(dist)),
            "open": close, "high": close + 0.5, "low": close - 0.5, "close": close,
            "sma_200": pd.Series(100.0, index=dist.index).shift(1),  # cache convention:
            "dist_atr_sma_200": dist.shift(1),                       # one-bar-lagged
        }))
    return (pd.concat(frames, ignore_index=True)
            .sort_values(["ticker", "date"]).reset_index(drop=True))


def spec(**overrides) -> StrategySpec:
    fields = dict(direction="both", timeframe="daily", size=Size(normalisation="atr", min=1.0),
                  uses=["detector:ma.first_touch"])
    return StrategySpec(**{**fields, **overrides})


def signal_date(dist: list[float], value: float, start: str = "2015-01-02") -> pd.Timestamp:
    return pd.bdate_range(start, periods=len(dist))[dist.index(value)]


def test_finds_the_match_on_its_signal_bar():
    result = find_first_touch(spec(), panel({"AAA": MATCH}))
    assert [(c.ticker, c.date) for c in result.matches] == [("AAA", signal_date(MATCH, 0.1))]
    assert result.matches[0].fails is None and result.near_misses == ()
    # The finder owns its chart geometry: the session runner draws what it declares.
    assert (result.overlay_column, result.overlay_name) == ("sma_200", "SMA 200")


def test_each_ring_yields_its_near_miss_and_no_match():
    result = find_first_touch(
        spec(), panel({"TCH": TOUCH_RING, "AWY": AWAY_RING, "DAY": DAYS_RING}))
    assert result.matches == ()
    by_ticker = {c.ticker: c for c in result.near_misses}
    assert set(by_ticker) == {"TCH", "AWY", "DAY"}
    assert by_ticker["TCH"].date == signal_date(TOUCH_RING, 0.3)
    assert "touch tolerance" in by_ticker["TCH"].fails and "0.375" in by_ticker["TCH"].fails
    assert by_ticker["AWY"].date == signal_date(AWAY_RING, 0.1)
    assert "relaxed" in by_ticker["AWY"].fails  # claims only what the construction guarantees
    assert by_ticker["DAY"].fails.startswith("touch window")
    # Near-misses are deduplicated on (ticker, date) even if rings were to overlap.
    assert len(result.near_misses) == len({(c.ticker, c.date) for c in result.near_misses})


def test_direction_filters_sides_and_an_unstated_direction_is_disclosed():
    both = panel({"UP": MATCH, "DN": SHORT_MATCH})
    assert {c.ticker for c in find_first_touch(spec(direction="long"), both).matches} == {"UP"}
    assert {c.ticker for c in find_first_touch(spec(direction="short"), both).matches} == {"DN"}
    assert {c.ticker for c in find_first_touch(spec(), both).matches} == {"UP", "DN"}
    # direction=None grounds both sides, but as a disclosed default — a long-only
    # trader's from-below rejections must not get misread as a trigger problem.
    result = find_first_touch(spec(direction=None), both)
    assert {c.ticker for c in result.matches} == {"UP", "DN"}
    direction = next(r for r in result.rubric if r.parameter == "direction")
    assert direction.source == "default" and "didn't state a direction" in direction.detail
    assert next(r for r in find_first_touch(spec(), both).rubric
                if r.parameter == "direction").source == "spec"


def test_a_relaxed_touch_in_a_run_that_still_fires_strictly_is_not_a_near_miss():
    # Day 2 after the run comes within 0.3 (relaxed tolerance only), day 4 within 0.1
    # (strict): the run fires under the spec as stated, so the 0.3 bar says nothing
    # about the tolerance and must not be shown as a near-miss.
    sequence = QUIET + [2.0] * 5 + [0.3, 0.5, 0.1] + QUIET
    result = find_first_touch(spec(), panel({"AAA": sequence}))
    assert [(c.ticker, c.date) for c in result.matches] == [("AAA", signal_date(sequence, 0.1))]
    assert result.near_misses == ()


def test_spec_away_distance_is_applied_and_credited_to_the_spec():
    # With the spec's away at 2.5 ATR, a 2.0-away run no longer qualifies strictly —
    # it becomes an away-ring near-miss (2.0 >= 2.5/1.5).
    result = find_first_touch(spec(size=Size(normalisation="atr", min=2.5)), panel({"AAA": MATCH}))
    assert result.matches == ()
    assert len(result.near_misses) == 1 and "away distance" in result.near_misses[0].fails
    rubric = {r.parameter: r for r in result.rubric}
    assert rubric["away distance"].source == "spec" and "2.5" in rubric["away distance"].value


def test_rubric_discloses_every_default_and_unapplied_filter():
    bare = spec(size=None, supporting_signals=[
        Signal(name="above SMA200", description="close above the 200-day", role="filter"),
        Signal(name="volume", description="rising volume", role="score")])
    rubric = {r.parameter: r for r in find_first_touch(bare, panel({"AAA": MATCH})).rubric}
    assert rubric["away distance"].source == "default"
    assert "didn't state this as a number" in rubric["away distance"].detail
    assert rubric["touch tolerance"].source == "default"
    assert rubric["touch window"].source == "default"
    assert rubric["moving average"].source == "run option"
    assert rubric["filter: above SMA200"].value == "NOT APPLIED"
    assert "filter: volume" not in rubric  # a score isn't a filter; nothing was skipped


def test_a_stated_upper_bound_and_before_entry_rules_are_disclosed():
    constrained = spec(
        size=Size(normalisation="atr", min=1.0, max=2.0),
        invalidation=[Rule(description="skip if earnings within 5 days", phase="before_entry"),
                      Rule(description="close back through the MA", phase="after_entry")])
    rubric = {r.parameter: r for r in find_first_touch(constrained, panel({"AAA": MATCH})).rubric}
    upper = rubric["away distance upper bound"]
    assert upper.value == "NOT APPLIED" and "2" in upper.detail  # stated, not silently dropped
    before = rubric["invalidation (before entry): skip if earnings within 5 days"]
    assert before.value == "NOT READ"
    assert not any("close back through" in key for key in rubric)  # after-entry: the trade, not the setup


def test_refusals_name_the_problem():
    with pytest.raises(GroundingError, match="ATR"):
        find_first_touch(spec(size=Size(normalisation="pct", min=5.0)), panel({"AAA": MATCH}))
    with pytest.raises(GroundingError, match="weekly"):
        find_first_touch(spec(timeframe="weekly"), panel({"AAA": MATCH}))
    with pytest.raises(GroundingError, match="doesn't state a timeframe"):
        # None must not silently become daily: a weekly trader's spec straight out of
        # extraction would otherwise ground as a daily idea.
        find_first_touch(spec(timeframe=None), panel({"AAA": MATCH}))
    with pytest.raises(GroundingError, match="no units"):
        # Numbers without a normalisation must never silently fall to the default away
        # distance (the rubric would then falsely claim no number was stated).
        find_first_touch(spec(size=Size(min=2.0, description="2 ATR above")), panel({"AAA": MATCH}))
    with pytest.raises(GroundingError, match="intraday"):
        find_first_touch(spec(trigger=Trigger(description="touch", price_basis="intraday")),
                         panel({"AAA": MATCH}))
    with pytest.raises(GroundingError, match="unknown moving average"):
        find_first_touch(spec(), panel({"AAA": MATCH}), ma="sma_37")
    with pytest.raises(GroundingError, match="not a feature panel"):
        find_first_touch(spec(), panel({"AAA": MATCH}).drop(columns=["dist_atr_sma_200"]))
    with pytest.raises(GroundingError, match="not a feature panel"):
        # The MA itself is needed too — it's the chart overlay.
        find_first_touch(spec(), panel({"AAA": MATCH}).drop(columns=["sma_200"]))


def test_registry_covers_catalogue_ids_only():
    from src.llm.strategy_spec import catalogue
    assert set(finders.FINDERS) <= catalogue.IDS
    assert all(key.startswith("detector:") for key in finders.FINDERS)

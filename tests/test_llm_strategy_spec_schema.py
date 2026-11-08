from typing import get_args

import pytest
from pydantic import ValidationError

from src.llm.strategy_spec.schema import (
    Control, Duration, Gap, Proximity, Rule, Setting, Signal, Size, SpecField, StrategySpec, Trigger,
    UnsupportedRequest, find_gaps, load_golden_specs)


def _complete(**overrides):
    fields = dict(
        name="x", direction="long", timeframe="daily",
        duration=Duration(min_bars=10, max_bars=40),
        size=Size(normalisation="atr", max=1.5),
        # Proximity is settled so a spec given level signals is asked only about them.
        trigger=Trigger(description="close above range high", price_basis="close", execution="next_open",
                        proximity=Proximity(through=True)),
        horizons_bars=[5, 20],
        invalidation=[Rule(description="close back inside the range", phase="after_entry")],
        control=Control(description="same dates, no pattern"),
    )
    return StrategySpec(**{**fields, **overrides})


def _gaps(spec):
    return {(g.field, g.kind) for g in find_gaps(spec)}


def test_complete_spec_has_no_gaps():
    assert find_gaps(_complete()) == []


def test_empty_spec_lists_every_required_field_as_missing():
    assert _gaps(StrategySpec()) == {
        (f, "missing") for f in
        ["direction", "timeframe", "duration", "size", "trigger", "horizons_bars", "invalidation", "control"]}


def test_described_but_unquantified():
    spec = _complete(duration=Duration(description="a few weeks"), size=Size(description="tight"),
                     trigger=Trigger(description="breaks out"))
    assert _gaps(spec) == {("duration", "unquantified"), ("size", "unquantified"), ("trigger", "unquantified")}
    reasons = {g.reason for g in find_gaps(spec) if g.field == "trigger"}
    assert any("next bar's open" in r for r in reasons)  # execution left open is a gap


def test_trigger_without_a_condition_is_one_gap():
    assert [(g.field, g.kind) for g in find_gaps(_complete(trigger=Trigger()))] == [("trigger", "missing")]


def test_guardrails_are_invalid():
    assert ("size", "invalid") in _gaps(_complete(size=Size(normalisation="raw_price", min=2.0)))
    assert ("trigger", "invalid") in _gaps(
        _complete(trigger=Trigger(description="x", price_basis="close", execution="same_close")))


def test_contradictions_are_invalid():
    assert ("duration", "invalid") in _gaps(_complete(duration=Duration(min_bars=40, max_bars=10)))
    assert ("duration", "invalid") in _gaps(_complete(duration=Duration(min_bars=0)))
    assert ("size", "invalid") in _gaps(_complete(size=Size(normalisation="atr", min=2.0, max=1.0)))
    assert ("horizons_bars", "invalid") in _gaps(_complete(horizons_bars=[0, 5]))
    assert ("horizons_bars", "invalid") in _gaps(_complete(horizons_bars=[20, 20]))
    assert ("size", "invalid") in _gaps(_complete(size=Size(normalisation="atr", max=-1.0)))
    assert ("size", "invalid") in _gaps(_complete(size=Size(normalisation="percentile", min=150)))


def test_not_applicable_is_an_answer():
    spec = _complete(duration=Duration(not_applicable=True), size=Size(not_applicable=True))
    assert find_gaps(spec) == []


def test_not_applicable_with_values_is_invalid():
    assert ("size", "invalid") in _gaps(_complete(size=Size(not_applicable=True, normalisation="raw_price", min=5)))
    assert ("duration", "invalid") in _gaps(_complete(duration=Duration(not_applicable=True, min_bars=40)))


def test_blank_text_is_not_an_answer():
    for bad in ({"control": {"description": "  "}},
                {"invalidation": [{"description": "", "phase": "after_entry"}]},
                {"trigger": {"description": ""}}):
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(bad)


def test_unknown_fields_and_values_are_rejected():
    with pytest.raises(ValidationError):
        StrategySpec.model_validate({"direction": "sideways"})
    with pytest.raises(ValidationError):
        StrategySpec.model_validate({"size": {"normalization": "atr"}})  # misspelled


def test_json_schema_round_trip():
    # Step 2 hands this schema to the LLM and validates its reply with the same model.
    assert "duration" in StrategySpec.model_json_schema()["properties"]
    spec = _complete()
    assert StrategySpec.model_validate_json(spec.model_dump_json()) == spec


def test_golden_specs_load_and_are_well_formed():
    golden = load_golden_specs()
    assert len(golden) == 3
    assert len({g.id for g in golden}) == len(golden)
    for g in golden:
        assert set(g.stated) <= set(StrategySpec.model_fields), g.id
        assert g.description and g.source


def test_golden_spec_gaps():
    gaps = {g.id: _gaps(g.spec) for g in load_golden_specs()}
    assert gaps["ma_touch_bounce"] == set()
    assert gaps["bullish_rsi_divergence_context"] == set()
    # As built, the pattern backtest enters on the breakout bar's own close and reports
    # bare outcome rates with no matched control: the checker catches both.
    assert gaps["vcp_breakout"] == {("trigger", "invalid"), ("control", "missing")}


def test_unsupported_request_blocks_and_keeps_the_users_words():
    spec = _complete(unsupported=[UnsupportedRequest(
        requested="earnings surprise", field="supporting_signals", reason="unsupported_data",
        detail="no earnings data")])
    assert find_gaps(spec) == [Gap("supporting_signals", "unsupported",
                                   "'earnings surprise': unsupported data (no earnings data)")]


def test_a_repeated_unsupported_request_is_kept_once_per_field():
    first = UnsupportedRequest(requested="15-minute bars", field="timeframe", reason="unsupported_timeframe")
    # Case, spacing, word-joining hyphens and end punctuation don't make a new request;
    # meaning-bearing symbols do (see test_request_wording_keeps_meaning_bearing_symbols).
    same = UnsupportedRequest(requested="15 Minute  Bars.", field="timeframe", reason="unsupported_timeframe")
    other_field = UnsupportedRequest(requested="15-minute bars", field="trigger", reason="unsupported_timeframe")
    spec = _complete(unsupported=[first, same, other_field])
    assert [(g.field, g.kind) for g in find_gaps(spec)] == [("timeframe", "unsupported"), ("trigger", "unsupported")]
    # Read at gap-check time, so a list extended after the spec was built is covered too.
    spec.unsupported.append(UnsupportedRequest(requested="15-MINUTE bars", field="timeframe",
                                               reason="unsupported_timeframe", detail="for the entry"))
    gaps = find_gaps(spec)
    assert len(gaps) == 2 and gaps[0].reason == "'15-minute bars': unsupported timeframe (for the entry)"
    assert gaps[1].reason == "'15-minute bars': unsupported timeframe"  # the detail stays with its field


def test_unsupported_gaps_come_in_field_order_with_details_merged():
    items = [UnsupportedRequest(requested="tick data", field="trigger", reason="unsupported_data"),
             UnsupportedRequest(requested="intraday", field="timeframe", reason="unsupported_timeframe",
                                detail="no intraday bars"),
             UnsupportedRequest(requested="intraday", field="timeframe", reason="unsupported_timeframe",
                                detail="No intraday  bars")]
    gaps = find_gaps(_complete(unsupported=items))
    assert [g.field for g in gaps] == ["timeframe", "trigger"]
    assert gaps[0].reason == "'intraday': unsupported timeframe (no intraday bars)"


def test_unsupported_gaps_sit_in_field_order_among_the_others_with_one_wording():
    items = [UnsupportedRequest(requested="15-minute bars", field="timeframe", reason="unsupported_timeframe"),
             UnsupportedRequest(requested="15-MINUTE BARS", field="trigger", reason="unsupported_timeframe")]
    gaps = find_gaps(_complete(control=None, unsupported=items))
    assert [(g.field, g.kind) for g in gaps] == [
        ("timeframe", "unsupported"), ("trigger", "unsupported"), ("control", "missing")]
    assert {g.reason for g in gaps[:2]} == {"'15-minute bars': unsupported timeframe"}


def test_request_wording_keeps_meaning_bearing_symbols():
    from src.llm.strategy_spec.schema import request_wording

    assert request_wording("15-Minute  Bars.") == request_wording("15 minute bars")
    assert request_wording('unusual "options" flow.') == request_wording("(unusual) options flow")
    # A minus sign isn't a hyphen, and comparison symbols change the ask.
    assert request_wording("z-score < -2") != request_wording("z-score < 2")
    assert request_wording("VIX > 30") != request_wording("VIX < 30")
    assert request_wording("a move of 10%") != request_wording("a move of $10")
    assert request_wording("...") not in ("", request_wording("??"))  # junk stays apart


def test_unsupported_timeframe_also_leaves_the_field_missing():
    spec = _complete(timeframe=None, unsupported=[UnsupportedRequest(
        requested="15-minute bars", field="timeframe", reason="unsupported_timeframe")])
    assert _gaps(spec) == {("timeframe", "missing"), ("timeframe", "unsupported")}


def test_unsupported_request_needs_a_known_field_and_reason():
    with pytest.raises(ValidationError):
        UnsupportedRequest(requested="x", field="examples", reason="other")
    with pytest.raises(ValidationError):
        UnsupportedRequest(requested="x", field="trigger", reason="too hard")
    with pytest.raises(ValidationError):
        UnsupportedRequest(requested=" ", field="trigger", reason="other")


def test_unsupported_fields_are_the_specs_decision_fields():
    assert set(get_args(SpecField)) == set(StrategySpec.model_fields) - {"name", "examples", "uses", "unsupported"}


def test_uses_must_name_catalogue_entries():
    assert find_gaps(_complete(uses=[" indicator:rsi\n", "control:matched"])) == []  # stripped
    with pytest.raises(ValidationError):
        StrategySpec(uses=[""])
    gaps = find_gaps(_complete(uses=["indicator:stochastic", "indicator:stochastic", "indicator:rsi"]))
    assert [(g.field, g.kind) for g in gaps] == [("uses", "invalid")]
    assert "'indicator:stochastic'" in gaps[0].reason


# --- supporting signals: how many must hold, and each filter's settings -------------


def _filter(name, uses=("detector:fibonacci.retracement",), **kw):
    return Signal(name=name, description=name, role="filter", uses=list(uses), **kw)


def test_two_or_more_filters_ask_how_many_must_hold():
    spec = _complete(supporting_signals=[_filter("fib", defaults_ok=True), _filter("line", defaults_ok=True)])
    [gap] = find_gaps(spec)
    assert (gap.field, gap.kind, gap.item) == ("filters_needed", "missing", None)
    assert "all 2 filters" in gap.reason and "fib; line" in gap.reason
    assert find_gaps(spec.model_copy(update={"filters_needed": 2})) == []
    # One filter, or filters plus a score input, has nothing to count.
    one = [_filter("fib", defaults_ok=True), Signal(name="rsi", description="rsi", role="score")]
    assert find_gaps(_complete(supporting_signals=one)) == []


def test_an_impossible_count_is_invalid():
    two = [_filter("fib", defaults_ok=True), _filter("line", defaults_ok=True)]
    for n in (0, 3):
        assert _gaps(_complete(supporting_signals=two, filters_needed=n)) == {("filters_needed", "invalid")}
    assert _gaps(_complete(filters_needed=1)) == {("filters_needed", "invalid")}  # no filters at all


def test_a_filter_is_asked_its_detectors_settings_until_given_or_defaulted():
    spec = _complete(supporting_signals=[_filter("fib level")])
    [gap] = find_gaps(spec)
    assert (gap.field, gap.kind, gap.item) == ("supporting_signals", "unquantified", "fib level")
    # The question names the settings, what they mean and their defaults.
    assert "min_swing_atr: the smallest swing" in gap.reason and "(default 8)" in gap.reason
    assert "retracement_ratios" in gap.reason and "defaults are fine" in gap.reason
    given = _filter("fib level", settings=[Setting(name="min_swing_atr", value="10 ATR")])
    assert find_gaps(_complete(supporting_signals=[given])) == []
    assert find_gaps(_complete(supporting_signals=[_filter("fib level", defaults_ok=True)])) == []


def _unsettled(**trigger):
    return Trigger(description="low tags the zone", price_basis="intraday", execution="next_open", **trigger)


def test_an_idea_built_on_levels_is_asked_how_close_price_must_come():
    fib = _filter("fib", defaults_ok=True)
    [gap] = find_gaps(_complete(trigger=_unsettled(), supporting_signals=[fib]))
    assert (gap.field, gap.kind, gap.item) == ("trigger", "unquantified", None)
    assert "how close must price come" in gap.reason and "trade through it" in gap.reason
    assert "isn't about reaching a level" in gap.reason  # the way out for an idea it doesn't fit
    # A level in the spec's own `uses`, or a level feature, asks too; a non-level idea doesn't.
    assert find_gaps(_complete(trigger=_unsettled(), uses=["feature:near_dn_w_sr_line"]))
    assert find_gaps(_complete(trigger=_unsettled(), uses=["detector:ma.first_touch"])) == []
    # Settled any of three ways: a distance, "must trade through it", or "doesn't apply".
    for p in (Proximity(normalisation="atr", max=0.3), Proximity(through=True), Proximity(not_applicable=True)):
        assert find_gaps(_complete(trigger=_unsettled(proximity=p), supporting_signals=[fib])) == []


@pytest.mark.parametrize("proximity, kind, words", [
    (Proximity(max=0.3), "unquantified", "in ATR, percent or log"),
    (Proximity(normalisation="atr"), "unquantified", "at most how far"),
    (Proximity(normalisation="raw_price", max=0.5), "invalid", "raw price"),
    (Proximity(normalisation="atr", max=-1.0), "invalid", "not negative"),
    (Proximity(normalisation="atr", max=float("nan")), "invalid", "a finite number"),
    (Proximity(normalisation="percentile", max=20.0), "invalid", "isn't a distance"),
    # Rejected units aren't followed by a request for a number in them.
    (Proximity(normalisation="percentile"), "invalid", "isn't a distance"),
    (Proximity(normalisation="atr", max=0.3, not_applicable=True), "invalid", "doesn't apply"),
    (Proximity(normalisation="atr", max=0.3, through=True), "invalid", "trade through"),
    (Proximity(through=True, not_applicable=True), "invalid", "both"),
])
def test_a_proximity_needs_units_and_a_distance(proximity, kind, words):
    [gap] = find_gaps(_complete(trigger=_unsettled(proximity=proximity)))
    assert (gap.field, gap.kind) == ("trigger", kind) and words in gap.reason


def test_a_proximity_follow_up_keeps_the_way_out_once():
    # A vague first answer must not force a distance: the follow-up still offers both outs.
    for p in (Proximity(), Proximity(normalisation="atr"), Proximity(normalisation="raw_price", max=1.0)):
        reasons = [g.reason for g in find_gaps(_complete(trigger=_unsettled(proximity=p)))]
        assert sum("trade through it" in r and "isn't about reaching a level" in r for r in reasons) == 1
    # It goes on the open question, not on an error next to it.
    gaps = [g for g in find_gaps(_complete(trigger=_unsettled(proximity=Proximity(max=-1.0)))) if g.field == "trigger"]
    assert len(gaps) == 2  # the units question and the negative distance
    assert ["trade through it" in g.reason for g in gaps] == [g.kind == "unquantified" for g in gaps]


def test_a_filter_mapped_to_a_level_feature_is_asked_its_detectors_settings():
    # The level-stack run's support line was mapped to this feature and never asked about.
    [gap] = find_gaps(_complete(supporting_signals=[_filter("support", uses=("feature:near_dn_w_sr_line",))]))
    assert (gap.field, gap.item) == ("supporting_signals", "support") and "window_years" in gap.reason


def test_only_filters_with_a_known_detector_are_asked():
    score = Signal(name="fib", description="fib", role="score", uses=["detector:fibonacci.retracement"])
    unmapped = _filter("news", uses=())
    no_settings = _filter("first touch", uses=("detector:ma.first_touch",))
    assert find_gaps(_complete(supporting_signals=[score])) == []
    assert find_gaps(_complete(supporting_signals=[unmapped, no_settings], filters_needed=2)) == []


def test_a_setting_or_id_the_catalogue_doesnt_list_is_invalid():
    wrong = _filter("fib", settings=[Setting(name="anchors", value="ath")])
    [gap] = [g for g in find_gaps(_complete(supporting_signals=[wrong])) if g.kind == "invalid"]
    assert gap.item == "fib" and "'anchors'" in gap.reason and "min_swing_atr" in gap.reason
    bad_id = _filter("fib", uses=("detector:fibonacci.retracement", "detector:elliott"), defaults_ok=True)
    gaps = find_gaps(_complete(supporting_signals=[bad_id]))
    # About the whole list: a per-signal (settings) answer can't change the detector.
    assert [(g.kind, g.item) for g in gaps] == [("invalid", None)]
    assert "'fib' uses 'detector:elliott'" in gaps[0].reason


def test_the_count_is_asked_before_the_signals_settings():
    spec = _complete(supporting_signals=[_filter("fib"), _filter("line")])
    assert [(g.field, g.item) for g in find_gaps(spec)] == [
        ("filters_needed", None), ("supporting_signals", "fib"), ("supporting_signals", "line")]

from typing import get_args

import pytest
from pydantic import ValidationError

from src.llm.strategy_spec.schema import (
    Control, Duration, Gap, Rule, Size, SpecField, StrategySpec, Trigger, UnsupportedRequest, find_gaps,
    load_golden_specs)


def _complete(**overrides):
    fields = dict(
        name="x", direction="long", timeframe="daily",
        duration=Duration(min_bars=10, max_bars=40),
        size=Size(normalisation="atr", max=1.5),
        trigger=Trigger(description="close above range high", price_basis="close", execution="next_open"),
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
    assert "executed at the next bar's open?" in reasons  # execution left open is a gap


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
    same = UnsupportedRequest(requested="15-Minute  Bars", field="timeframe", reason="unsupported_timeframe")
    other_field = UnsupportedRequest(requested="15-minute bars", field="trigger", reason="unsupported_timeframe")
    spec = _complete(unsupported=[first, same, other_field])
    assert spec.unsupported == [first, other_field]  # on the spec itself, for every reader
    assert [(g.field, g.kind) for g in find_gaps(spec)] == [("timeframe", "unsupported"), ("trigger", "unsupported")]


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

import pytest
from pydantic import ValidationError

from src.llm.strategy_spec.schema import (
    Control, Duration, Rule, Size, StrategySpec, Trigger, find_gaps, load_golden_specs)


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


def test_guardrails_are_invalid():
    assert ("size", "invalid") in _gaps(_complete(size=Size(normalisation="raw_price", min=2.0)))
    assert ("trigger", "invalid") in _gaps(
        _complete(trigger=Trigger(description="x", price_basis="close", execution="same_close")))


def test_contradictions_are_invalid():
    assert ("duration", "invalid") in _gaps(_complete(duration=Duration(min_bars=40, max_bars=10)))
    assert ("duration", "invalid") in _gaps(_complete(duration=Duration(min_bars=0)))
    assert ("size", "invalid") in _gaps(_complete(size=Size(normalisation="atr", min=2.0, max=1.0)))
    assert ("horizons_bars", "invalid") in _gaps(_complete(horizons_bars=[0, 5]))


def test_not_applicable_is_an_answer():
    spec = _complete(duration=Duration(not_applicable=True), size=Size(not_applicable=True))
    assert find_gaps(spec) == []


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
    # The pattern backtest reports bare outcome rates with no matched control: the
    # checker catches the decision that was never made.
    assert gaps["vcp_breakout"] == {("control", "missing")}

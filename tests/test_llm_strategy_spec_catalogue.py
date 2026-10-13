"""The capability catalogue can't drift from the code: every entry's `impl` imports, and
where the code has a fixed list, the catalogue matches it both ways."""

import importlib
import inspect
from typing import get_args

import pytest

from src.llm.strategy_spec import catalogue, schema
from src.llm.strategy_spec.catalogue import CATALOGUE, NOT_USER_FACING_INDICATORS


def _resolve(impl: str):
    module, attr = impl.split(":")
    return getattr(importlib.import_module(module), attr)


@pytest.mark.parametrize("cap", CATALOGUE, ids=lambda c: c.id)
def test_every_impl_imports(cap):
    assert _resolve(cap.impl) is not None


def test_ids_are_unique_and_prefixed_by_kind():
    ids = [c.id for c in CATALOGUE]
    assert len(ids) == len(set(ids))
    for c in CATALOGUE:
        assert c.kind in get_args(catalogue.Kind)
        assert c.id.startswith(f"{c.kind}:") and len(c.id) > len(c.kind) + 1
        assert c.description.strip()


def _suffixes(prefix: str) -> set[str]:
    return {c.id.removeprefix(prefix) for c in CATALOGUE if c.id.startswith(prefix)}


ENUMS = [
    ("detector:pattern.", "src.signals.patterns.models:PatternType"),
    ("detector:gap.", "src.signals.gaps.models:GapKind"),
    ("detector:divergence.", "src.signals.divergences.models:IndicatorKind"),
    ("detector:structure.", "src.signals.market_structure.models:StructureEvent"),
    ("detector:sr_line.", "src.signals.sr_lines.models:EventType"),
    ("detector:fibonacci.", "src.signals.fibonacci.models:FibLevelKind"),
]


@pytest.mark.parametrize("prefix, enum", ENUMS, ids=[p for p, _ in ENUMS])
def test_detector_entries_match_the_code_enum(prefix, enum):
    assert _suffixes(prefix) == {member.value for member in _resolve(enum)}


def test_feature_entries_match_the_registry_model_inputs():
    from src.models.features.registry import MODEL, REGISTRY

    assert _suffixes("feature:") == {f.name for f in REGISTRY if f.role == MODEL}


def test_every_public_indicator_function_is_listed_or_excluded():
    module = importlib.import_module("src.foundation.market_common.indicators")
    public = {name for name, fn in inspect.getmembers(module, inspect.isfunction)
              if fn.__module__ == module.__name__ and not name.startswith("_")}
    listed = {c.impl.split(":")[1] for c in CATALOGUE if c.impl.startswith(f"{module.__name__}:")}
    assert listed.isdisjoint(NOT_USER_FACING_INDICATORS)
    assert listed | set(NOT_USER_FACING_INDICATORS) == public


def test_render_lists_the_schema_choices_and_every_entry():
    text = catalogue.render()
    for literal in (schema.Timeframe, schema.Normalisation, schema.PriceBasis, schema.Execution):
        assert ", ".join(get_args(literal)) in text
    for c in CATALOGUE:
        assert f"- {c.id}: " in text


def test_catalogue_does_not_import_signal_code():
    # Rendering the prompt must stay cheap: no pandas, no feature registry.
    source = inspect.getsource(catalogue)
    assert "import pandas" not in source and "from src.signals" not in source and "from src.models" not in source

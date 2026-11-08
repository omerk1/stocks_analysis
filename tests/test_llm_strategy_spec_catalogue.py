"""The capability catalogue can't drift from the code: every entry's `impl` imports, and
where the code has a fixed list, the catalogue matches it both ways."""

import dataclasses
import enum
import importlib
import inspect
import subprocess
import sys
from pathlib import Path
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


SETTINGS = [(prefix, s) for prefix, settings in catalogue.SETTINGS.items() for s in settings]


@pytest.mark.parametrize("prefix, setting", SETTINGS, ids=[f"{p}{s.name}" for p, s in SETTINGS])
def test_every_setting_maps_to_its_config_field_and_default(prefix, setting):
    assert any(c.id.startswith(prefix) for c in CATALOGUE), "a family with no catalogue entry"
    module, _, attr = setting.impl.partition(":")
    owner_name, _, field_name = attr.partition(".")
    owner = _resolve(f"{module}:{owner_name}")
    if not field_name:  # a choice among an enum's members: every one is the default
        assert issubclass(owner, enum.Enum) and setting.default == "all of them"
        return
    fields = {f.name: f for f in dataclasses.fields(owner)}
    assert field_name in fields
    f = fields[field_name]
    default = f.default_factory() if f.default is dataclasses.MISSING else f.default
    assert setting.default == default


def test_sr_line_questions_name_the_long_term_preset():
    from src.signals.sr_lines.config import PRESETS
    asked = {s.name: s.question for s in catalogue.SETTINGS["detector:sr_line."]}
    assert f"uses {PRESETS['long_term'].window_years:g}" in asked["window_years"]
    assert f"uses {PRESETS['long_term'].pivot_atr_mult:g}" in asked["pivot_atr_mult"]


def test_avwap_anchor_question_names_every_anchor_type():
    from src.foundation.market_common.anchors import AnchorType
    words = {"ath": "all-time", "atl": "all-time", "52w_high": "52-week", "52w_low": "52-week",
             "cycle_high": "cycle", "cycle_low": "cycle", "regime_high": "regime", "regime_low": "regime"}
    anchors = next(s for s in catalogue.SETTINGS["detector:avwap"] if s.name == "anchors")
    for member in AnchorType:  # a new member fails here until the question names it
        assert words[member.value] in anchors.question


def test_settings_for_merges_a_family_and_ignores_the_rest():
    found = catalogue.settings_for(["detector:divergence.rsi", "detector:divergence.obv", "indicator:rsi"])
    assert list(found) == [s.name for s in catalogue.SETTINGS["detector:divergence."]]
    assert catalogue.settings_for(["detector:ma.first_touch"]) == {}


def test_a_level_feature_asks_its_detectors_settings():
    assert set(catalogue.FEATURE_FAMILY) <= catalogue.IDS
    sr = [s.name for s in catalogue.SETTINGS["detector:sr_line."]]
    assert list(catalogue.settings_for(["feature:near_dn_w_sr_line"])) == sr
    assert list(catalogue.settings_for(["feature:near_up_gap"])) == [s.name for s in catalogue.SETTINGS["detector:gap."]]
    # Mixed-source features and sources with no settings ask none.
    for feature in ("feature:density_dn_2", "feature:near_dn_vp", "feature:near_dn_ma"):
        assert catalogue.settings_for([feature]) == {}


def test_levels_are_detector_families_and_level_features():
    assert catalogue.LEVEL_FEATURES <= catalogue.IDS and "feature:near_dn_w_sr_line" in catalogue.LEVEL_FEATURES
    for prefix in catalogue.LEVEL_PREFIXES:  # each prefix still names a real detector
        assert any(i.startswith(prefix) for i in catalogue.IDS)
    assert catalogue.uses_levels(["detector:avwap"]) and catalogue.uses_levels(["feature:confluence_dn"])
    # Detectors that define their own touch, and level context that isn't a level, aren't.
    assert not catalogue.uses_levels(["detector:ma.first_touch", "detector:base_breakout.retest",
                                      "feature:density_dn_2", "indicator:rsi"])


def test_render_lists_the_schema_choices_and_every_entry():
    text = catalogue.render()
    for literal in (schema.Timeframe, schema.Normalisation, schema.PriceBasis, schema.Execution):
        assert ", ".join(get_args(literal)) in text
    for c in CATALOGUE:
        assert f"- {c.id}: " in text


def test_rendering_does_not_load_signal_code():
    # Rendering the prompt must stay cheap: no pandas, no feature registry. A fresh
    # interpreter, since this test session has already imported them.
    code = ("import sys; from src.llm.strategy_spec import catalogue; catalogue.render(); "
            "print([m for m in sys.modules if m == 'pandas' or m.startswith(('src.signals', 'src.models'))])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parents[1])
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"

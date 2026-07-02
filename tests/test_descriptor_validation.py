"""Descriptor validator tests (docs/CONFIGURABLE_INSTRUMENTS.md §17.6/§17.7).

Includes the builder<->descriptor source-scan: the ``add_parameter`` names in
``instruments/PUMA_instrument_definition.py`` must equal the descriptor's
``scannable_parameters`` exactly. Pure text scan -- no mcstasscript import.
"""
import dataclasses
import os
import re

import pytest

from instruments._descriptor_examples import in8_descriptor
from instruments.descriptor import AxisLimits
from instruments.puma_plugin import puma_descriptor
from instruments.validation import (
    DescriptorValidationError,
    assert_valid_descriptor,
    validate_descriptor,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUMA_MODULE_PATH = os.path.join(REPO_ROOT, "instruments", "PUMA_instrument_definition.py")


def test_puma_descriptor_valid_runnable():
    assert validate_descriptor(puma_descriptor(), runnable=True) == []


def test_in8_descriptor_valid_as_example():
    assert validate_descriptor(in8_descriptor(), runnable=False) == []


def test_in8_descriptor_rejected_as_runnable():
    errors = "\n".join(validate_descriptor(in8_descriptor(), runnable=True))
    assert "l1_source_mono" in errors
    assert "slab_width" in errors          # crystal completeness
    assert "source_types" in errors        # empty library


def test_assert_valid_descriptor_raises_with_messages():
    with pytest.raises(DescriptorValidationError, match="l1_source_mono"):
        assert_valid_descriptor(in8_descriptor(), runnable=True)
    assert_valid_descriptor(puma_descriptor(), runnable=True)  # must not raise


def _replace(d, **kwargs):
    return dataclasses.replace(d, **kwargs)


@pytest.mark.parametrize(
    ("mutate", "expected_substring"),
    [
        (lambda d: _replace(d, id="Puma!"), "must match [a-z0-9_]+"),
        (lambda d: _replace(d, display_name=""), "display_name"),
        (lambda d: _replace(d, mono_crystals=d.mono_crystals * 2), "duplicate id"),
        (
            lambda d: _replace(
                d, scannable_parameters=d.scannable_parameters + (d.scannable_parameters[0],)
            ),
            "duplicate name",
        ),
        (
            lambda d: _replace(
                d, scannable_parameters=(dataclasses.replace(d.scannable_parameters[0], name="1bad"),)
            ),
            "not a valid C identifier",
        ),
        (lambda d: _replace(d, primary_detector=""), "primary_detector"),
        (lambda d: _replace(d, detector_output_file="other.dat"), "detector_output_file"),
        (lambda d: _replace(d, detector_parser="2d_monitor"), "detector_parser"),
        (
            lambda d: _replace(d, modules=(dataclasses.replace(d.modules[0], default="Nope"),)),
            "not in options",
        ),
        (
            lambda d: _replace(
                d, collimation=(dataclasses.replace(d.collimation[0], default="99"),)
            ),
            "not in allowed",
        ),
        (
            lambda d: _replace(
                d, geometry=dataclasses.replace(d.geometry, l2_mono_sample=-1.0)
            ),
            "l2_mono_sample",
        ),
        (
            lambda d: _replace(d, axis_limits={"A1": AxisLimits(10.0, 20.0, 0.0)}),
            "lower <= default <= upper",
        ),
    ],
)
def test_structural_negative_cases(mutate, expected_substring):
    errors = "\n".join(validate_descriptor(mutate(puma_descriptor())))
    assert expected_substring in errors


def test_multi_select_collimation_may_default_to_empty():
    d = puma_descriptor()
    alpha_2 = next(slot for slot in d.collimation if slot.id == "alpha_2")
    assert alpha_2.multi_select and alpha_2.default == ""
    assert validate_descriptor(d) == []


def test_puma_build_declares_descriptor_params():
    """The builder's add_parameter set must equal the descriptor's parameter set."""
    with open(PUMA_MODULE_PATH, encoding="utf-8") as f:
        source = f.read()
    declared = set(re.findall(r'add_parameter\(\s*"(\w+)"', source))
    descriptor_names = {p.name for p in puma_descriptor().scannable_parameters}
    assert declared == descriptor_names, (
        f"builder-only: {sorted(declared - descriptor_names)}; "
        f"descriptor-only: {sorted(descriptor_names - declared)}"
    )


def test_monitor_ids_match_build_gates():
    """Descriptor monitors stay 1:1 with build()'s diagnostic_settings gates.

    Source scan -- the diagnostic dialog renders from the descriptor while
    build() keeps its literal gate blocks until Phase 3; this test is what
    stops the two from drifting apart in the meantime.
    """
    with open(PUMA_MODULE_PATH, encoding="utf-8") as f:
        source = f.read()
    gate_keys = set(re.findall(r"diagnostic_settings\.get\('([^']+)'\)", source))
    monitor_ids = {m.id for m in puma_descriptor().monitors}
    assert gate_keys == monitor_ids, (
        f"build-only: {sorted(gate_keys - monitor_ids)}; "
        f"descriptor-only: {sorted(monitor_ids - gate_keys)}"
    )
    assert len(puma_descriptor().monitors) == 19


def test_monitor_component_names_unique_and_set():
    names = [m.component_name for m in puma_descriptor().monitors]
    assert all(names)
    assert len(names) == len(set(names))


def test_sample_ids_match_build_ladder():
    """Descriptor sample ids stay 1:1 with build()'s sample_key ladder."""
    with open(PUMA_MODULE_PATH, encoding="utf-8") as f:
        source = f.read()
    ladder_keys = set(re.findall(r'sample_key == "(\w+)"', source))
    descriptor_ids = {
        s.id for s in puma_descriptor().samples if s.component_type is not None
    }
    assert ladder_keys == descriptor_ids, (
        f"build-only: {sorted(ladder_keys - descriptor_ids)}; "
        f"descriptor-only: {sorted(descriptor_ids - ladder_keys)}"
    )

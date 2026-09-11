"""Descriptor validator tests (docs/CONFIGURABLE_INSTRUMENTS.md §17.6/§17.7).

Includes the builder<->descriptor source-scan: the ``add_parameter`` names in
``instruments/puma/model.py`` must equal the descriptor's
``scannable_parameters`` exactly. Pure text scan -- no mcstasscript import.
"""
import dataclasses
import os
import re

import pytest

from instruments._descriptor_examples import in8_descriptor, in12_descriptor
from instruments.descriptor import AxisLimits, CurvatureAxis
from instruments.panda.plugin import panda_descriptor
from instruments.puma.plugin import puma_descriptor
from instruments.validation import (
    DescriptorValidationError,
    assert_valid_descriptor,
    validate_descriptor,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUMA_MODULE_PATH = os.path.join(REPO_ROOT, "instruments", "puma", "model.py")


def test_puma_descriptor_valid_runnable():
    assert validate_descriptor(puma_descriptor(), runnable=True) == []


def test_in8_descriptor_valid_runnable():
    # Phase 4: IN8 is a real, registered instrument -- startup gates on this.
    assert validate_descriptor(in8_descriptor(), runnable=True) == []


def test_in12_descriptor_valid_runnable():
    # IN12 is a real, registered instrument -- startup gates on this.
    assert validate_descriptor(in12_descriptor(), runnable=True) == []


def test_runnable_rejects_incomplete_descriptor():
    """The runnable gate still catches missing L1 and incomplete crystals."""
    d = in8_descriptor()
    broken = dataclasses.replace(
        d,
        geometry=dataclasses.replace(d.geometry, l1_source_mono=float("nan")),
        mono_crystals=(dataclasses.replace(
            d.mono_crystals[0], slab_width=None), ) + d.mono_crystals[1:],
    )
    errors = "\n".join(validate_descriptor(broken, runnable=True))
    assert "l1_source_mono" in errors
    assert "slab_width" in errors          # crystal completeness
    # ...but the same descriptor is still structurally valid as an example.
    assert validate_descriptor(broken, runnable=False) == []


def test_assert_valid_descriptor_raises_with_messages():
    d = in8_descriptor()
    broken = dataclasses.replace(
        d, geometry=dataclasses.replace(d.geometry, l1_source_mono=float("nan"))
    )
    with pytest.raises(DescriptorValidationError, match="l1_source_mono"):
        assert_valid_descriptor(broken, runnable=True)
    assert_valid_descriptor(puma_descriptor(), runnable=True)  # must not raise
    assert_valid_descriptor(in8_descriptor(), runnable=True)   # must not raise
    assert_valid_descriptor(in12_descriptor(), runnable=True)  # must not raise


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
    assert alpha_2.multi_select and alpha_2.default == "40"
    # An empty multi-select default ("nothing pre-selected") is also valid.
    empty_default = dataclasses.replace(alpha_2, default="")
    mutated = dataclasses.replace(
        d, collimation=tuple(
            empty_default if slot.id == "alpha_2" else slot for slot in d.collimation
        )
    )
    assert validate_descriptor(mutated) == []


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


def test_monitor_count_is_stable():
    """build() emits monitors straight from this table (Phase 3); the tree-level
    guarantees live in tests/test_puma_build_tree.py."""
    assert len(puma_descriptor().monitors) == 19


def test_monitor_component_names_unique_and_set():
    names = [m.component_name for m in puma_descriptor().monitors]
    assert all(names)
    assert len(names) == len(set(names))


# build() now mounts the sample straight from the shared library
# (tavi/sample_library.py); tree-level sample guarantees live in
# tests/test_puma_build_tree.py.


def _fixed_rva(radius=0.3, provenance="test"):
    return {"rva": CurvatureAxis(driven=False, fixed_radius_m=radius, provenance=provenance)}


def test_fixed_curvature_must_name_an_axis_that_side_has():
    """A typo fails open -- the scan is allowed and the pin bypassed.

    A monochromator can only fix rhm/rvm and an analyser only rha/rva, so
    "rva" on a mono is a typo and must not pass silently.
    """
    base = in8_descriptor()

    good = dataclasses.replace(
        base, ana_crystals=tuple(
            dataclasses.replace(c, curvature=_fixed_rva())
            for c in base.ana_crystals))
    assert [e for e in validate_descriptor(good) if "curvature" in e] == []

    wrong_side = dataclasses.replace(
        base, mono_crystals=tuple(
            dataclasses.replace(c, curvature=_fixed_rva())
            for c in base.mono_crystals))
    errs = [e for e in validate_descriptor(wrong_side) if "curvature" in e]
    assert errs and "is not one of" in errs[0]

    typo = dataclasses.replace(
        base, ana_crystals=tuple(
            dataclasses.replace(
                c, curvature={"rva_param": CurvatureAxis(
                    driven=False, fixed_radius_m=0.3, provenance="test")})
            for c in base.ana_crystals))
    assert any("curvature" in e and "is not one of" in e
               for e in validate_descriptor(typo))


def test_curvature_radius_without_provenance_is_invalid():
    """An unsourced number in a hardware-looking field must not pass."""
    base = in8_descriptor()
    bad = dataclasses.replace(
        base, ana_crystals=tuple(
            dataclasses.replace(
                c, curvature={"rva": CurvatureAxis(driven=False, fixed_radius_m=0.3)})
            for c in base.ana_crystals))
    errs = [e for e in validate_descriptor(bad) if "curvature" in e]
    assert any("provenance" in e for e in errs)


def test_fixed_axis_cannot_carry_travel_limits():
    base = in8_descriptor()
    bad = dataclasses.replace(
        base, ana_crystals=tuple(
            dataclasses.replace(
                c, curvature={"rva": CurvatureAxis(
                    driven=False, fixed_radius_m=0.3, min_radius_m=0.2,
                    provenance="test")})
            for c in base.ana_crystals))
    errs = [e for e in validate_descriptor(bad) if "curvature" in e]
    assert any("driven axis" in e for e in errs)


def test_curvature_min_must_not_exceed_max():
    base = in8_descriptor()
    bad = dataclasses.replace(
        base, ana_crystals=tuple(
            dataclasses.replace(
                c, curvature={"rha": CurvatureAxis(
                    driven=True, min_radius_m=2.0, max_radius_m=1.0,
                    provenance="test")})
            for c in base.ana_crystals))
    errs = [e for e in validate_descriptor(bad) if "curvature" in e]
    assert any("min_radius_m must be <= max_radius_m" in e for e in errs)


def test_fixed_curvature_reports_declared_fixed_axes():
    """IN12 PG(002) and PANDA PG(002) fix rva; the IN12 Heusler does not.

    IN8's crystals declare curvature (no clamps known) but nothing fixed, so
    they still report an empty tuple.
    """
    in12 = in12_descriptor()
    ana = {c.id: c for c in in12.ana_crystals}
    assert ana["pg002"].fixed_curvature == ("rva",)
    assert ana["heusler111"].fixed_curvature == ()

    panda_ana = {c.id: c for c in panda_descriptor().ana_crystals}
    assert panda_ana["pg002"].fixed_curvature == ("rva",)

    for spec in in8_descriptor().mono_crystals + in8_descriptor().ana_crystals:
        assert spec.fixed_curvature == ()

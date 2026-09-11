"""Regression: ``curvature_limits`` must resolve through
``effective_curvature_axis``, not read ``CrystalSpec.curvature`` raw (D17).

``effective_curvature_axis``'s own docstring names ``set_crystal_bending``,
the scan-command validator, and ``ideal_curvature`` as the three consumers
that must never answer this question independently -- ``curvature_limits``
is reached from two of those three (``set_crystal_bending``'s clamp and
``ideal_curvature``'s clamp) yet was itself still reading the crystal's raw
declaration, bypassing any override an instrument subclass or the live
module state applies. A subclass overriding ``effective_curvature_axis`` to
change a driven axis's travel is the direct probe: the raw read cannot see
it, the resolved one must.
"""
import pytest

pytest.importorskip("mcstasscript")

from instruments.descriptor import CurvatureAxis
from instruments.puma.model import PUMA_Instrument
from instruments.puma.plugin import puma_descriptor
from tavi.instrument_helpers import find_crystal_spec


class _WideTravelPUMA(PUMA_Instrument):
    """Overrides rha's travel only -- every other axis (including the
    crystal's own declared rha) must be unaffected."""

    def effective_curvature_axis(self, axis, crystal_spec, modules=None):
        if axis == "rha":
            return CurvatureAxis(driven=True, min_radius_m=9.0, max_radius_m=99.0)
        return super().effective_curvature_axis(axis, crystal_spec, modules=modules)


def test_curvature_limits_honours_a_subclass_travel_override():
    descriptor = puma_descriptor()
    ana_spec = find_crystal_spec(descriptor.ana_crystals, "pg002")
    declared_min, declared_max = ana_spec.curvature["rha"].min_radius_m, \
        ana_spec.curvature["rha"].max_radius_m

    state = _WideTravelPUMA()
    min_m, max_m = state.curvature_limits("rha", ana_spec, 20.0, 20.0)

    assert (min_m, max_m) == (9.0, 99.0)
    assert (min_m, max_m) != (declared_min, declared_max)


def test_curvature_limits_still_matches_the_raw_declaration_when_unoverridden():
    """Baseline: an axis with no override still reads the crystal's own
    declared travel, unchanged by routing through the resolver."""
    descriptor = puma_descriptor()
    mono_spec = find_crystal_spec(descriptor.mono_crystals, "pg002")
    declared = mono_spec.curvature["rhm"]

    state = PUMA_Instrument()
    min_m, max_m = state.curvature_limits("rhm", mono_spec, 20.0, 20.0)

    assert (min_m, max_m) == (declared.min_radius_m, declared.max_radius_m)

"""Illustrative descriptors: PUMA (real, from the plugin) and IN8 (skeleton).

Purpose: prove the ``InstrumentDescriptor`` of ``instruments/descriptor.py``
captures both reference instruments *without* baking in PUMA's shape -- the
"design against PUMA and IN8" check from ``docs/CONFIGURABLE_INSTRUMENTS.md``
§12.5. PUMA's descriptor is no longer defined here: the real one lives in
``instruments/puma_plugin.py`` (single source of truth) and is re-imported for
the side-by-side comparison.

IN8 values come from ``examples/vtas_reference/instruments_repository.xml``
(ILL vTAS). The IN8 skeleton is deliberately **incomplete** (``TODO``/``nan``
markers): it must pass ``validate_descriptor(...)`` structurally but *fail* with
``runnable=True`` -- run this module as a script to see both:

    python -m instruments._descriptor_examples

Targets Python 3.11 syntax.
"""
from __future__ import annotations

from instruments.descriptor import (
    AxisLimits,
    CrystalSpec,
    Geometry,
    InstrumentDescriptor,
    ParameterSpec,
    Sense,
)
from instruments.puma_plugin import puma_descriptor  # noqa: F401  (re-export)
from tavi.sample_library import default_sample_library

# Shared "core" TAS parameters every instrument needs; instrument-specific extras
# (slits, bending, selector) are appended per instrument. The sample-orientation /
# mount parameters are part of the core because they come from the generic
# sample-orientation hierarchy every TAVI instrument reuses.
_CORE_PARAMS = (
    ParameterSpec("A1_param", "Monochromator 2-theta angle"),
    ParameterSpec("A2_param", "Sample 2-theta angle"),
    ParameterSpec("A3_param", "Sample theta (phi) angle"),
    ParameterSpec("A4_param", "Analyzer 2-theta angle"),
    ParameterSpec("E0_param", "Source energy for monochromatic source", unit="meV"),
    ParameterSpec("saz_param", "Sample azimuthal angle (out-of-plane)"),
    ParameterSpec("chi_param", "User chi - out-of-plane tilt", default=0.0),
    ParameterSpec("kappa_param", "Kappa - chi alignment offset", default=0.0),
    ParameterSpec("mis_chi_param", "Hidden chi misalignment (training)", default=0.0),
    ParameterSpec("psi_param", "Psi - omega alignment offset", default=0.0),
    ParameterSpec("mis_omega_param", "Hidden omega misalignment (training)", default=0.0),
    ParameterSpec("chi_total", "Total chi = chi + kappa + mis_chi", default=0.0),
    ParameterSpec("omega_offset_total", "Total omega offset = psi + mis_omega", default=0.0),
    ParameterSpec("mount_rx_param", "Static sample mount rotation about x", default=0.0),
    ParameterSpec("mount_ry_param", "Static sample mount rotation about y", default=0.0),
    ParameterSpec("mount_rz_param", "Static sample mount rotation about z", default=0.0),
)


def in8_descriptor() -> InstrumentDescriptor:
    """ILL IN8 -- kinematic skeleton from vTAS; McStas "flesh" still TODO.

    What vTAS gives us (filled below): arm lengths L2/L3/L4, scattering senses,
    axis limits, mono/ana d-spacing. What it does NOT give (TODO from the
    instrument scientist): L1/source, crystal slab geometry, collimation, slits,
    focusing, sample environment, detector. FlatCone/IMPS are deferred (§14).
    """
    return InstrumentDescriptor(
        id="in8",
        display_name="ILL IN8",
        institute="ILL",
        geometry=Geometry(
            l1_source_mono=float("nan"),   # TODO: vTAS omits source->mono; needs IN8 docs
            l2_mono_sample=2.5,
            l3_sample_ana=1.35,
            l4_ana_det=0.65,
            # KEY DELTA vs PUMA: IN8 sample sense is RIGHT (vTAS ss = -1).
            sense_mono=Sense.LEFT,
            sense_sample=Sense.RIGHT,
            sense_ana=Sense.LEFT,
            sample_table_radius=0.3,
        ),
        # d-spacing known (PG[002]); slab geometry TODO -> kinematic-only is valid.
        mono_crystals=(CrystalSpec("pg002", "PG[002]", 3.355),),
        ana_crystals=(CrystalSpec("pg002", "PG[002]", 3.355),),
        samples=default_sample_library(),   # shared library: samples move between instruments
        scannable_parameters=_CORE_PARAMS,                  # shared core; extras TODO
        primary_detector="detector",
        mcstas_name="IN8_McScript",
        axis_limits={
            "A1": AxisLimits(-40.0, 77.256, 110.0),     # vTAS a2 (mono take-off)
            "A2": AxisLimits(-120.0, -111.08, 120.0),   # vTAS a4 (sample 2-theta)
            "A4": AxisLimits(-120.0, 83.957, 120.0),    # vTAS a6 (analyser take-off)
        },
        # modules: FlatCone / IMPS available on IN8 but multi-detector -> deferred past v1.
    )


if __name__ == "__main__":
    from instruments.validation import validate_descriptor

    for d in (puma_descriptor(), in8_descriptor()):
        g = d.geometry
        print(f"\n{d.display_name}  (id={d.id})")
        print(f"  arms L1/L2/L3/L4 = "
              f"{g.l1_source_mono}/{g.l2_mono_sample}/{g.l3_sample_ana}/{g.l4_ana_det}")
        print(f"  senses (mono/sample/ana) = "
              f"{g.sense_mono.value}/{g.sense_sample.value}/{g.sense_ana.value}")
        print(f"  mono d / ana d = {d.mono_crystals[0].d_spacing} / {d.ana_crystals[0].d_spacing}")
        print(f"  #scannable params = {len(d.scannable_parameters)}, "
              f"#samples = {len(d.samples)}, #modules = {len(d.modules)}")
        for runnable in (False, True):
            problems = validate_descriptor(d, runnable=runnable)
            label = "runnable" if runnable else "structural"
            if problems:
                print(f"  validate ({label}): {len(problems)} problem(s)")
                for p in problems:
                    print(f"    - {p}")
            else:
                print(f"  validate ({label}): OK")

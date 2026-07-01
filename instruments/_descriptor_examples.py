"""Phase-0 DRAFT (illustrative, NOT wired): PUMA and IN8 descriptors side by side.

Purpose: prove the ``InstrumentDescriptor`` of ``instruments/descriptor.py``
captures both reference instruments *without* baking in PUMA's shape. This is the
"design against PUMA and IN8" check from ``docs/CONFIGURABLE_INSTRUMENTS.md`` §12.5.

Values:
  - PUMA   <- ``instruments/PUMA_instrument_definition.py``
  - IN8    <- ``examples/vtas_reference/instruments_repository.xml`` (ILL vTAS)

Deliberately **incomplete** -- enough to exercise the dataclasses and surface the
real gaps (marked ``TODO``), not a migration. Running this module as a script
prints a short PUMA-vs-IN8 comparison.

Targets Python 3.11 syntax.
"""
from __future__ import annotations

from instruments.descriptor import (
    AxisLimits,
    CollimationSlot,
    CrystalSpec,
    Geometry,
    InstrumentDescriptor,
    ModuleKind,
    ModuleSpec,
    ParameterSpec,
    SampleSpec,
    Sense,
    SlitSpec,
    SourceType,
)

# --- shared crystal definitions (PUMA values) -----------------------------------
# id = stable slug (config key / objectName); display_name = GUI label. See §16.3.
PG002_MONO = CrystalSpec(
    id="pg002", display_name="PG[002]", d_spacing=3.355,
    slab_width=0.0202, slab_height=0.018, n_columns=13, n_rows=9,
    gap=0.0005, mosaic=35, r0=1.0, reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
)
PG002_ANA = CrystalSpec(
    id="pg002", display_name="PG[002]", d_spacing=3.355,
    slab_width=0.01, slab_height=0.0295, n_columns=21, n_rows=5,
    gap=0.0005, mosaic=35, r0=1.0, reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
)

# --- the scannable parameter set PUMA declares today (the per-point dict shape) --
# Shared "core" TAS parameters every instrument needs; instrument-specific extras
# (slits, bending, selector) are appended per instrument.
_CORE_PARAMS = (
    ParameterSpec("A1_param", "Monochromator 2-theta angle"),
    ParameterSpec("A2_param", "Sample 2-theta angle"),
    ParameterSpec("A3_param", "Sample theta (phi) angle"),
    ParameterSpec("A4_param", "Analyzer 2-theta angle"),
    ParameterSpec("E0_param", "Source energy for monochromatic source", unit="meV"),
    ParameterSpec("saz_param", "Sample azimuthal angle (out-of-plane)"),
    ParameterSpec("chi_total", "Total chi = chi + kappa + mis_chi"),
    ParameterSpec("omega_offset_total", "Total omega offset = psi + misalignments"),
)
_PUMA_PARAMS = _CORE_PARAMS + (
    ParameterSpec("nu_param", "Velocity selector frequency"),
    ParameterSpec("rhm_param", "Monochromator horizontal bending"),
    ParameterSpec("rvm_param", "Monochromator vertical bending"),
    ParameterSpec("rha_param", "Analyzer horizontal bending"),
    ParameterSpec("rva_param", "Analyzer vertical bending"),
    ParameterSpec("vbl_hgap_param", "Post-mono slit horizontal gap", unit="m"),
    ParameterSpec("pbl_hgap_param", "Pre-sample slit horizontal gap", unit="m"),
    ParameterSpec("pbl_vgap_param", "Pre-sample slit vertical gap", unit="m"),
    ParameterSpec("dbl_hgap_param", "Detector slit horizontal gap", unit="m"),
)


def puma_descriptor() -> InstrumentDescriptor:
    """PUMA (FRM-II) -- fully specified from the existing instrument definition."""
    return InstrumentDescriptor(
        id="puma",
        display_name="PUMA (FRM-II)",
        institute="FRM-II",
        geometry=Geometry(
            l1_source_mono=2.150,
            l2_mono_sample=2.290,
            l3_sample_ana=0.880,
            l4_ana_det=0.750,
            # PUMA's handedness is implicit in its arm rotations; encoded here
            # explicitly so the contract treats it uniformly with IN8.
            sense_mono=Sense.LEFT,
            sense_sample=Sense.LEFT,
            sense_ana=Sense.LEFT,
        ),
        mono_crystals=(PG002_MONO,),
        ana_crystals=(PG002_ANA,),
        samples=(
            SampleSpec("none", "No sample", None),
            SampleSpec("Al_rod_phonon", "Al: acoustic phonon", "Phonon_simple_SCATTER",
                       properties={"radius": 5e-3, "yheight": 30e-3, "T": 200}, split=10),
            SampleSpec("Al_bragg", "Al: Bragg", "Single_crystal",
                       properties={"reflections": '"Al.lau"', "mosaic": 5}, split=10),
            SampleSpec("Al_phonon_DFT", "Al: Phonon DFT", "Phonon_DFT",
                       properties={"T": 200}, split=10),
        ),
        scannable_parameters=_PUMA_PARAMS,
        primary_detector="detector",
        mcstas_name="PUMA_McScript",
        modules=(
            ModuleSpec("nmo", "NMO installed", ModuleKind.CHOICE,
                       options=("None", "Vertical", "Horizontal", "Both"), default="None"),
            ModuleSpec("v_selector", "Velocity selector", ModuleKind.TOGGLE, default=False),
        ),
        collimation=(
            CollimationSlot("alpha_1", "α1 (src-mono)", ("0", "20", "40", "60")),
            CollimationSlot("alpha_2", "α2 (mono-smp)", ("30", "40", "60"), multi_select=True),
            CollimationSlot("alpha_3", "α3 (smp-ana)", ("0", "10", "20", "30", "45", "60")),
            CollimationSlot("alpha_4", "α4 (ana-det)", ("0", "10", "20", "30", "45", "60")),
        ),
        slits=(
            SlitSpec("vbl_hgap", "Post-mono (width)", default_width_mm=88),
            SlitSpec("pbl", "Pre-sample (W×H)", has_height=True,
                     default_width_mm=100, default_height_mm=100),
            SlitSpec("dbl_hgap", "Detector (width)", default_width_mm=50),
        ),
        source_types=(
            SourceType("Maxwellian", "Maxwellian"),
            SourceType("Mono", "Mono", extra_params=("source_dE",)),
        ),
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
        samples=(SampleSpec("none", "No sample", None),),   # TODO: IN8 sample environment
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

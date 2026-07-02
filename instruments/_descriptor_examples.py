"""Side-by-side descriptor demo: PUMA and IN8, both real.

Purpose: prove the ``InstrumentDescriptor`` of ``instruments/descriptor.py``
captures both reference instruments *without* baking in PUMA's shape -- the
"design against PUMA and IN8" check from ``docs/CONFIGURABLE_INSTRUMENTS.md``
§12.5. Neither descriptor is defined here anymore: PUMA's lives in
``instruments/puma_plugin.py`` and IN8's in ``instruments/in8_plugin.py``
(single sources of truth, both runnable); they are re-imported for the
comparison printout:

    python -m instruments._descriptor_examples

``_CORE_PARAMS`` documents the shared "core" TAS parameter set every
instrument's ``scannable_parameters`` starts from (the sample-orientation /
mount hierarchy of ``tavi/instrument_helpers.py``); the real plugins inline
these in their full parameter tuples.

Targets Python 3.11 syntax.
"""
from __future__ import annotations

from instruments.descriptor import ParameterSpec
from instruments.in8_plugin import in8_descriptor  # noqa: F401  (re-export)
from instruments.puma_plugin import puma_descriptor  # noqa: F401  (re-export)

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

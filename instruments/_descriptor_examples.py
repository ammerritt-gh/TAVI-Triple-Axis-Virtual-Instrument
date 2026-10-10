"""Side-by-side descriptor demo: PUMA, IN8, IN12 and PANDA, all real.

Purpose: prove the ``InstrumentDescriptor`` of ``instruments/descriptor.py``
captures both reference instruments *without* baking in PUMA's shape -- the
"design against PUMA and IN8" check from ``docs/CONFIGURABLE_INSTRUMENTS.md``
§12.5. Neither descriptor is defined here anymore: PUMA's lives in
``instruments/puma/plugin.py``, IN8's in ``instruments/in8/plugin.py``,
IN12's in ``instruments/in12/plugin.py``, and PANDA's in
``instruments/panda/plugin.py`` (single sources of truth, all runnable); they are re-imported for the
comparison printout:

    python -m instruments._descriptor_examples

``_CORE_PARAMS`` documents the shared "core" TAS parameter set every
instrument's ``scannable_parameters`` starts from (the single sample arm of
``tavi/instrument_helpers.py``); the real plugins inline
these in their full parameter tuples.

Targets Python 3.11 syntax.
"""
from __future__ import annotations

from instruments.descriptor import ParameterSpec
from instruments.in8.plugin import in8_descriptor  # noqa: F401  (re-export)
from instruments.in12.plugin import in12_descriptor  # noqa: F401  (re-export)
from instruments.panda.plugin import panda_descriptor  # noqa: F401  (re-export)
from instruments.puma.plugin import puma_descriptor  # noqa: F401  (re-export)

# Shared "core" TAS parameters every instrument needs; instrument-specific extras
# (slits, bending, selector) are appended per instrument. The sample-arm
# parameters are part of the core because every TAVI instrument emits the same
# single sample arm (the stage at its readout angles and the crystal mount).
_CORE_PARAMS = (
    ParameterSpec("mono_two_theta_param", "Monochromator 2-theta angle",
                  quantity="mono_two_theta_deg"),
    ParameterSpec("sample_two_theta_param", "Sample 2-theta angle",
                  quantity="sample_two_theta_deg"),
    ParameterSpec("sample_rotation_param", "Sample rotation (turntable) readout, inspection only",
                  quantity="sample_rotation_deg"),
    ParameterSpec("analyzer_two_theta_param", "Analyzer 2-theta angle",
                  quantity="analyzer_two_theta_deg"),
    ParameterSpec("mono_theta_param", "Monochromator crystal theta (rotation)",
                  quantity="mono_theta_deg"),
    ParameterSpec("analyzer_theta_param", "Analyzer crystal theta (rotation)",
                  quantity="analyzer_theta_deg"),
    ParameterSpec("E0_param", "Source energy for monochromatic source", unit="meV"),
    ParameterSpec("sgl_param", "Lower arc sgl readout", default=0.0,
                  quantity="sample_lower_arc_deg"),
    ParameterSpec("sgu_param", "Upper arc sgu readout", default=0.0,
                  quantity="sample_upper_arc_deg"),
    ParameterSpec("sample_rx_param", "Sample arm rotation about x (stage and mount)", default=0.0),
    ParameterSpec("sample_ry_param", "Sample arm rotation about y (stage and mount)", default=0.0),
    ParameterSpec("sample_rz_param", "Sample arm rotation about z (stage and mount)", default=0.0),
)


if __name__ == "__main__":
    from instruments.validation import validate_descriptor

    for d in (puma_descriptor(), in8_descriptor(), in12_descriptor(), panda_descriptor()):
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
